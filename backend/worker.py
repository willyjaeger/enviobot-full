#!/usr/bin/env python3
"""
worker.py - Motor de Sincronización y Pronóstico de Quiebre de Stock (EnvioBot Full)
Compatible con la base de datos enviobot_web y soporte multi-cuenta de MercadoLibre.
"""

import os
import sys
import time
from datetime import datetime, timedelta
import pymysql
import requests
from dotenv import load_dotenv

import esquema
import proyeccion

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "enviobot")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", os.getenv("ML_SHARED_CLIENT_ID", "1845856849463362"))
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
MELI_API = "https://api.mercadolibre.com"

def get_db():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def refresh_ml_token(conn, cred_id, refresh_token):
    """Renueva el access_token de MeLi si está expirado o próximo a expirar."""
    url = f"{MELI_API}/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": refresh_token
    }
    try:
        r = requests.post(url, data=payload, timeout=12)
        if r.status_code == 200:
            data = r.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", refresh_token)
            expires_at = int(time.time() + data.get("expires_in", 21600))
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ml_credentials 
                    SET ml_access_token=%s, ml_refresh_token=%s, ml_token_expires_at=%s, updated_at=NOW()
                    WHERE id=%s
                """, (new_access, new_refresh, expires_at, cred_id))
            print(f"[{datetime.now()}] Token MeLi renovado (cred_id: {cred_id})")
            return new_access
        else:
            print(f"[{datetime.now()}] Error renovando token cred_id {cred_id}: {r.text}")
            return None
    except Exception as e:
        print(f"[{datetime.now()}] Excepción renovando token cred_id {cred_id}: {e}")
        return None

def get_valid_token_for_cred(conn, cred):
    """Devuelve token válido o lo refresca automáticamente."""
    expires_at = cred.get("ml_token_expires_at") or 0
    if time.time() < expires_at - 300:
        return cred.get("ml_access_token")
    return refresh_ml_token(conn, cred["id"], cred.get("ml_refresh_token"))

def fetch_fulfillment_stock(access_token, inventory_id, stock_cache):
    """
    Consulta el stock físico real y no disponible en depósitos de Full (Villa Celina)
    para un inventory_id específico. Utiliza stock_cache para no duplicar llamadas.
    """
    if not inventory_id:
        return None
    if inventory_id in stock_cache:
        return stock_cache[inventory_id]

    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{MELI_API}/inventories/{inventory_id}/stock/fulfillment"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            avail = data.get("available_quantity", 0)
            not_avail = data.get("not_available_quantity", 0)
            tot = data.get("total", avail + not_avail)
            res = (avail, not_avail, tot)
            stock_cache[inventory_id] = res
            return res
        else:
            stock_cache[inventory_id] = None
            return None
    except Exception as e:
        print(f"Error consultando stock fulfillment (inv_id: {inventory_id}): {e}")
        stock_cache[inventory_id] = None
        return None

def fetch_full_publications(access_token, meli_user_id):
    """
    Recupera todas las publicaciones del vendedor en Fulfillment (Full) activas o pausadas.
    Desglosa variaciones con su inventory_id correspondiente para evitar pérdida de datos.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    all_flat_items = []
    limit = 50
    offset = 0

    while True:
        # Filtrar active y paused para omitir publicaciones closed (finalizadas viejas)
        url = f"{MELI_API}/users/{meli_user_id}/items/search?logistic_type=fulfillment&status=active,paused&limit={limit}&offset={offset}"
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 401:
                return None
            if r.status_code != 200:
                break

            data = r.json()
            item_ids = data.get("results", [])
            if not item_ids:
                break

            # MercadoLibre /items?ids= permite un máximo estricto de 20 IDs por llamada
            for i in range(0, len(item_ids), 20):
                chunk = item_ids[i:i + 20]
                ids_chunk = ",".join(chunk)
                multiget_url = f"{MELI_API}/items?ids={ids_chunk}"
                m_resp = requests.get(multiget_url, headers=headers, timeout=12)
                if m_resp.status_code == 200:
                    for entry in m_resp.json():
                        if entry.get("code") == 200:
                            body = entry.get("body", {})
                            item_id = body.get("id")
                            title = body.get("title", "")
                            status = body.get("status", "active")
                            sub_status = ",".join(body.get("sub_status") or [])
                            listing_type = body.get("listing_type_id") or "gold_special"
                            is_catalog = bool(body.get("catalog_listing"))
                            thumbnail = body.get("thumbnail")
                            permalink = body.get("permalink")
                            parent_inv_id = body.get("inventory_id")

                            # Resolver SKU principal (seller_custom_field o atributo SELLER_SKU)
                            base_sku = (body.get("seller_custom_field") or "").strip()
                            if not base_sku:
                                for attr in body.get("attributes", []):
                                    if attr.get("id") in ("SELLER_SKU", "SKU"):
                                        base_sku = (attr.get("value_name") or "").strip()
                                        if base_sku:
                                            break

                            variations = body.get("variations", [])
                            if variations:
                                for v in variations:
                                    var_id = str(v.get("id")) if v.get("id") else ""
                                    var_inv_id = v.get("inventory_id") or parent_inv_id
                                    
                                    # SKU de la variación (seller_custom_field, attributes o seller_sku)
                                    var_sku = (v.get("seller_custom_field") or "").strip()
                                    if not var_sku:
                                        for attr in v.get("attributes", []):
                                            if attr.get("id") in ("SELLER_SKU", "SKU"):
                                                var_sku = (attr.get("value_name") or "").strip()
                                                if var_sku:
                                                    break
                                    if not var_sku:
                                        var_sku = (v.get("seller_sku") or "").strip()
                                    if not var_sku:
                                        var_sku = base_sku

                                    var_combs = v.get("attribute_combinations", [])
                                    var_name = " / ".join(f"{c.get('name')}: {c.get('value_name')}" for c in var_combs) if var_combs else None
                                    var_declared_stock = v.get("available_quantity", 0)

                                    all_flat_items.append({
                                        "item_id": item_id,
                                        "variation_id": var_id,
                                        "variation_name": var_name,
                                        "inventory_id": var_inv_id,
                                        "sku": var_sku,
                                        "title": title,
                                        "thumbnail": thumbnail,
                                        "permalink": permalink,
                                        "listing_type_id": listing_type,
                                        "is_catalog": is_catalog,
                                        "status": status,
                                        "sub_status": sub_status,
                                        "declared_stock": var_declared_stock
                                    })
                            else:
                                all_flat_items.append({
                                    "item_id": item_id,
                                    "variation_id": "",
                                    "variation_name": None,
                                    "inventory_id": parent_inv_id,
                                    "sku": base_sku,
                                    "title": title,
                                    "thumbnail": thumbnail,
                                    "permalink": permalink,
                                    "listing_type_id": listing_type,
                                    "is_catalog": is_catalog,
                                    "status": status,
                                    "sub_status": sub_status,
                                    "declared_stock": body.get("available_quantity", 0)
                                })

            offset += limit
            if offset >= data.get("paging", {}).get("total", 0):
                break
        except Exception as e:
            print(f"Error consultando items Full: {e}")
            break

    # Retroalimentar SKUs a publicaciones de catálogo u homónimas que comparten inventory_id
    inv_sku_map = {}
    for fitm in all_flat_items:
        inv = fitm.get("inventory_id")
        sku = fitm.get("sku")
        if inv and sku and inv not in inv_sku_map:
            inv_sku_map[inv] = sku

    for fitm in all_flat_items:
        if not fitm.get("sku") and fitm.get("inventory_id") in inv_sku_map:
            fitm["sku"] = inv_sku_map[fitm["inventory_id"]]

    return all_flat_items

def calculate_sales_velocity(access_token, meli_user_id, item_id, variation_id=None):
    """Calcula unidades vendidas en los últimos 7, 15 y 30 días con paginación completa."""
    headers = {"Authorization": f"Bearer {access_token}"}
    now = datetime.utcnow()
    date_from_30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000-00:00")
    date_to = now.strftime("%Y-%m-%dT23:59:59.000-00:00")

    sales_7d, sales_15d, sales_30d = 0, 0, 0
    t_7d = now - timedelta(days=7)
    t_15d = now - timedelta(days=15)
    offset = 0
    limit = 50

    try:
        while True:
            url = f"{MELI_API}/orders/search?seller={meli_user_id}&item={item_id}&order.date_created.from={date_from_30d}&order.date_created.to={date_to}&limit={limit}&offset={offset}&sort=date_desc"
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                break

            data = r.json()
            orders = data.get("results", [])
            if not orders:
                break

            for order in orders:
                if order.get("status") in ("cancelled", "invalid"):
                    continue
                date_created_str = order.get("date_created", "")
                try:
                    order_dt = datetime.fromisoformat(date_created_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    order_dt = now

                for item_ordered in order.get("order_items", []):
                    ord_item = item_ordered.get("item", {})
                    if ord_item.get("id") == item_id:
                        # Si filtramos por variación específica
                        if variation_id and ord_item.get("variation_id") and str(ord_item.get("variation_id")) != str(variation_id):
                            continue
                        qty = item_ordered.get("quantity", 1)
                        sales_30d += qty
                        if order_dt >= t_15d:
                            sales_15d += qty
                        if order_dt >= t_7d:
                            sales_7d += qty

            offset += limit
            total_orders = data.get("paging", {}).get("total", 0)
            if offset >= total_orders or offset >= 1000:
                break

        return sales_7d, sales_15d, sales_30d
    except Exception as e:
        print(f"Error calculando ventas de {item_id}: {e}")
        return sales_7d, sales_15d, sales_30d

def registrar_y_contar_dias_sin_stock(conn, user_id, item_id, var_id, stock, stock_es_real, hoy=None):
    """Anota la foto de hoy del stock (si la tabla existe y el dato viene de ML) y devuelve cuántos
    días de los últimos 7, 15 y 30 el producto estuvo sin stock. Sin la tabla devuelve ceros y la
    velocidad queda como siempre. Un día cuenta como sin stock si el máximo del día fue 0."""
    hoy = hoy or datetime.utcnow().date()
    try:
        with conn.cursor() as cur:
            if not esquema.tiene_tabla(cur, "stock_daily"):
                return 0, 0, 0
            if stock_es_real:
                cur.execute("""
                    INSERT INTO stock_daily (user_id, item_id, variation_id, day, stock_min, stock_max)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        stock_min = LEAST(stock_min, VALUES(stock_min)),
                        stock_max = GREATEST(stock_max, VALUES(stock_max))
                """, (user_id, item_id, var_id or "", hoy, stock, stock))
            cur.execute("""
                SELECT SUM(stock_max = 0 AND day > %s) AS sin7,
                       SUM(stock_max = 0 AND day > %s) AS sin15,
                       SUM(stock_max = 0) AS sin30
                FROM stock_daily
                WHERE user_id = %s AND item_id = %s AND variation_id = %s AND day > %s
            """, (hoy - timedelta(days=7), hoy - timedelta(days=15), user_id, item_id, var_id or "", hoy - timedelta(days=30)))
            f = cur.fetchone() or {}
            return int(f.get("sin7") or 0), int(f.get("sin15") or 0), int(f.get("sin30") or 0)
    except Exception as e:
        print(f"No se pudo registrar/leer el historial de stock de {item_id}: {e}")
        return 0, 0, 0


def sync_account_full_catalog(user_id, cred_id, access_token, meli_user_id):
    """
    Sincroniza el catálogo en Fulfillment con exactitud física desde el WMS de Mercado Libre.
    Aplica desglose de stock disponible real, retenciones y tiempo de preparación de pedidos.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            settings = cur.fetchone() or {
                "default_lead_time_days": 5,
                "default_safety_stock_days": 2,
                "target_coverage_days": 30
            }
            default_lt = settings.get("default_lead_time_days", 5)       # Tiempo para preparar pedido
            default_ss = settings.get("default_safety_stock_days", 2)      # Colchón de seguridad
            default_transit = 2                                            # Demora flete Villa Celina
            target_cov = settings.get("target_coverage_days", 30)

        items = fetch_full_publications(access_token, meli_user_id)
        if items is None:
            return

        stock_cache = {}
        today = datetime.utcnow().date()
        for it in items:
            item_id = it["item_id"]
            var_id = it["variation_id"]
            var_name = it["variation_name"]
            inv_id = it["inventory_id"]
            sku = it["sku"]
            title = it["title"]
            thumbnail = it["thumbnail"]
            permalink = it["permalink"]
            listing_type_id = it["listing_type_id"]
            is_catalog = it["is_catalog"]
            status = it["status"]
            declared_stock = it["declared_stock"]

            # Obtener stock físico real desde la API de inventarios de MeLi
            stock_info = fetch_fulfillment_stock(access_token, inv_id, stock_cache)
            stock_es_real = bool(stock_info)
            if stock_info:
                stock_real, not_available, _ = stock_info
            else:
                stock_real = declared_stock
                not_available = 0

            var_id = it.get("variation_id") or ""
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO full_items 
                    (user_id, ml_credential_id, item_id, variation_id, variation_name, inventory_id, sku, title, thumbnail, permalink, 
                     listing_type_id, is_catalog, status, current_stock_full, not_available_stock_full, last_synced_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        ml_credential_id = VALUES(ml_credential_id),
                        variation_name = VALUES(variation_name),
                        inventory_id = VALUES(inventory_id),
                        sku = VALUES(sku),
                        title = VALUES(title),
                        thumbnail = VALUES(thumbnail),
                        permalink = VALUES(permalink),
                        listing_type_id = VALUES(listing_type_id),
                        is_catalog = VALUES(is_catalog),
                        status = VALUES(status),
                        current_stock_full = VALUES(current_stock_full),
                        not_available_stock_full = VALUES(not_available_stock_full),
                        last_synced_at = NOW()
                """, (user_id, cred_id, item_id, var_id, var_name, inv_id, sku, title, thumbnail, permalink,
                      listing_type_id, is_catalog, status, stock_real, not_available))
                # Motivo de la pausa (migración 002): si la columna todavía no existe, se omite.
                if esquema.tiene_columna(cur, "full_items", "sub_status"):
                    cur.execute("UPDATE full_items SET sub_status = %s WHERE user_id=%s AND item_id=%s AND variation_id=%s",
                                (it.get("sub_status") or None, user_id, item_id, var_id))

                # Leer overrides específicos si existen
                cur.execute("SELECT lead_time_override, safety_stock_override FROM full_items WHERE user_id=%s AND item_id=%s AND variation_id=%s", (user_id, item_id, var_id))
                irow = cur.fetchone()
                lt = irow["lead_time_override"] if irow and irow.get("lead_time_override") is not None else default_lt
                ss = irow["safety_stock_override"] if irow and irow.get("safety_stock_override") is not None else default_ss

            # Calcular ventas y ritmo de demanda
            v7, v15, v30 = calculate_sales_velocity(access_token, meli_user_id, item_id, var_id)
            sin7, sin15, sin30 = registrar_y_contar_dias_sin_stock(conn, user_id, item_id, var_id, stock_real, stock_es_real)
            vpd = proyeccion.vpd_ponderado(v7, v15, v30, sin7, sin15, sin30)

            total_advance = lt + ss + default_transit
            if vpd > 0:
                days_left = round(stock_real / vpd, 1)
                stockout_date = today + timedelta(days=int(days_left))
                days_until_prep = days_left - total_advance
                reorder_deadline = today + timedelta(days=max(0, int(days_until_prep)))
                suggested_restock = max(0, int(round((target_cov * vpd) - stock_real)))
            else:
                days_left = 999.0
                stockout_date = None
                reorder_deadline = None
                suggested_restock = 0

            if stock_real <= 0:
                calc_status = 'out_of_stock'
            elif days_left <= (lt + default_transit):
                calc_status = 'critical'
            elif days_left <= total_advance:
                calc_status = 'warning'
            else:
                calc_status = 'ok'

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO forecasts 
                    (user_id, item_id, variation_id, sales_last_7d, sales_last_15d, sales_last_30d, vpd_weighted, days_left, stockout_date, reorder_deadline_date, suggested_restock_units, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        sales_last_7d = VALUES(sales_last_7d),
                        sales_last_15d = VALUES(sales_last_15d),
                        sales_last_30d = VALUES(sales_last_30d),
                        vpd_weighted = VALUES(vpd_weighted),
                        days_left = VALUES(days_left),
                        stockout_date = VALUES(stockout_date),
                        reorder_deadline_date = VALUES(reorder_deadline_date),
                        suggested_restock_units = VALUES(suggested_restock_units),
                        status = VALUES(status),
                        updated_at = NOW()
                """, (user_id, item_id, var_id, v7, v15, v30, vpd, days_left, stockout_date, reorder_deadline, suggested_restock, calc_status))

        print(f"[{datetime.now()}] Sync completada: user_id={user_id}, cred_id={cred_id}, {len(items)} items/variantes procesados.")
    finally:
        conn.close()

def sync_all_accounts_for_user(user_id):
    """Sincroniza todas las cuentas de MeLi del usuario."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, user_id, ml_user_id, ml_access_token, ml_refresh_token, ml_token_expires_at FROM ml_credentials WHERE user_id=%s", (user_id,))
        creds = cur.fetchall()

    for cred in creds:
        token = get_valid_token_for_cred(conn, cred)
        if token and cred.get("ml_user_id"):
            sync_account_full_catalog(user_id, cred["id"], token, cred["ml_user_id"])

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_settings (user_id, last_sync_at) 
                VALUES (%s, NOW())
                ON DUPLICATE KEY UPDATE last_sync_at = NOW()
            """, (user_id,))
    except Exception as e:
        print(f"[{datetime.now()}] Error guardando last_sync_at para user_id={user_id}: {e}")
    finally:
        conn.close()

    # Disparar evaluación de alertas para el usuario
    try:
        from alerts_engine import procesar_alertas_usuario
        res_alert = procesar_alertas_usuario(user_id)
        print(f"[{datetime.now()}] Alertas evaluadas para user_id={user_id}: {res_alert}")
    except Exception as e:
        print(f"[{datetime.now()}] Error evaluando alertas para user_id={user_id}: {e}")

def run_periodic_sync(skip_alerts: bool = False, force: bool = False):
    """Ejecutado por Cron en producción respetando la frecuencia configurada de cada usuario."""
    print(f"[{datetime.now()}] === Iniciando Sync Periódica EnvioBot Full ===")
    conn = get_db()
    with conn.cursor() as cur:
        # Traer configuración de frecuencia y última sincronización de cada usuario activo
        cur.execute("""
            SELECT u.id as user_id, 
                   COALESCE(s.sync_frequency_hours, 4) as sync_frequency_hours,
                   s.last_sync_at
            FROM users u
            LEFT JOIN user_settings s ON s.user_id = u.id
            WHERE u.active = 1
        """)
        users_settings = {r["user_id"]: r for r in cur.fetchall()}

        cur.execute("""
            SELECT c.id, c.user_id, c.ml_user_id, c.ml_access_token, c.ml_refresh_token, c.ml_token_expires_at, c.ml_nickname
            FROM ml_credentials c
            JOIN users u ON u.id = c.user_id
            WHERE u.active = 1
        """)
        creds = cur.fetchall()

    now = datetime.now()
    creds_by_user = {}
    for c in creds:
        creds_by_user.setdefault(c["user_id"], []).append(c)

    usuarios_procesados = set()
    for uid, user_creds in creds_by_user.items():
        us = users_settings.get(uid, {})
        freq = us.get("sync_frequency_hours") or 4
        last_sync = us.get("last_sync_at")

        should_sync = force
        if not should_sync:
            if not last_sync:
                should_sync = True
            else:
                elapsed_hours = (now - last_sync).total_seconds() / 3600.0
                # Margen de 10 minutos (0.16h) para compensar desfasajes de tiempo de cron
                if elapsed_hours >= (freq - 0.16):
                    should_sync = True
                else:
                    print(f"[{datetime.now()}] [SKIP] user_id={uid}: frecuencia configurada={freq}h, última sync fue hace {elapsed_hours:.1f}h")

        if should_sync:
            print(f"[{datetime.now()}] [RUN] user_id={uid}: sincronizando {len(user_creds)} credenciales (frecuencia configurada: {freq}h)")
            for cred in user_creds:
                try:
                    token = get_valid_token_for_cred(conn, cred)
                    if token and cred.get("ml_user_id"):
                        sync_account_full_catalog(uid, cred["id"], token, cred["ml_user_id"])
                        usuarios_procesados.add(uid)
                except Exception as e:
                    print(f"Error procesando cred {cred.get('id')}: {e}")

            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_settings (user_id, last_sync_at)
                        VALUES (%s, NOW())
                        ON DUPLICATE KEY UPDATE last_sync_at = NOW()
                    """, (uid,))
            except Exception as e:
                print(f"Error actualizando last_sync_at para user_id={uid}: {e}")

    conn.close()
    print(f"[{datetime.now()}] === Sync Periódica Finalizada ({len(usuarios_procesados)} usuarios sincronizados) ===")

    # Disparar motor de alertas para todos los usuarios sincronizados
    if not skip_alerts and usuarios_procesados:
        try:
            from alerts_engine import ejecutar_motor_alertas_global
            ejecutar_motor_alertas_global()
        except Exception as e:
            print(f"[{datetime.now()}] Error ejecutando motor de alertas global: {e}")

if __name__ == "__main__":
    if "--alerts-only" in sys.argv:
        from alerts_engine import ejecutar_motor_alertas_global
        ejecutar_motor_alertas_global()
    elif "--user" in sys.argv:
        try:
            idx = sys.argv.index("--user")
            target_uid = int(sys.argv[idx + 1])
            sync_all_accounts_for_user(target_uid)
        except Exception as ex:
            print(f"Uso: python worker.py --user <user_id> (Error: {ex})")
    elif "--force" in sys.argv:
        run_periodic_sync(force=True)
    else:
        run_periodic_sync()
