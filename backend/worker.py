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

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", os.getenv("ML_SHARED_CLIENT_ID", "1845856849463362"))
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q")
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

def fetch_full_publications(access_token, meli_user_id):
    """Recupera todas las publicaciones del vendedor en Fulfillment (Full)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    all_items = []
    limit = 50
    offset = 0

    while True:
        url = f"{MELI_API}/users/{meli_user_id}/items/search?shipping_modes=fulfillment&limit={limit}&offset={offset}"
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

            ids_chunk = ",".join(item_ids)
            multiget_url = f"{MELI_API}/items?ids={ids_chunk}"
            m_resp = requests.get(multiget_url, headers=headers, timeout=12)
            if m_resp.status_code == 200:
                for entry in m_resp.json():
                    if entry.get("code") == 200:
                        all_items.append(entry.get("body"))

            offset += limit
            if offset >= data.get("paging", {}).get("total", 0):
                break
        except Exception as e:
            print(f"Error consultando items Full: {e}")
            break

    return all_items

def calculate_sales_velocity(access_token, meli_user_id, item_id):
    """Calcula unidades vendidas en los últimos 7, 15 y 30 días."""
    headers = {"Authorization": f"Bearer {access_token}"}
    now = datetime.utcnow()
    date_from_30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000-00:00")
    date_to = now.strftime("%Y-%m-%dT23:59:59.000-00:00")

    url = f"{MELI_API}/orders/search?seller={meli_user_id}&item={item_id}&order.date_created.from={date_from_30d}&order.date_created.to={date_to}&limit=50"
    sales_7d, sales_15d, sales_30d = 0, 0, 0
    t_7d = now - timedelta(days=7)
    t_15d = now - timedelta(days=15)

    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return 0, 0, 0

        orders = r.json().get("results", [])
        for order in orders:
            if order.get("status") in ("cancelled", "invalid"):
                continue
            date_created_str = order.get("date_created", "")
            try:
                order_dt = datetime.fromisoformat(date_created_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                order_dt = now

            for item_ordered in order.get("order_items", []):
                if item_ordered.get("item", {}).get("id") == item_id:
                    qty = item_ordered.get("quantity", 1)
                    sales_30d += qty
                    if order_dt >= t_15d:
                        sales_15d += qty
                    if order_dt >= t_7d:
                        sales_7d += qty

        return sales_7d, sales_15d, sales_30d
    except Exception:
        return 0, 0, 0

def sync_account_full_catalog(user_id, cred_id, access_token, meli_user_id):
    """Sincroniza una cuenta de MercadoLibre específica."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            settings = cur.fetchone() or {
                "default_lead_time_days": 7,
                "default_safety_stock_days": 3,
                "target_coverage_days": 30
            }
            default_lt = settings["default_lead_time_days"]
            default_ss = settings["default_safety_stock_days"]
            target_cov = settings["target_coverage_days"]

        items = fetch_full_publications(access_token, meli_user_id)
        if items is None:
            return

        today = datetime.utcnow().date()
        for item in items:
            item_id = item.get("id")
            title = item.get("title", "")
            sku = item.get("seller_custom_field") or ""
            stock = item.get("available_quantity", 0)
            thumbnail = item.get("thumbnail")
            permalink = item.get("permalink")

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO full_items 
                    (user_id, ml_credential_id, item_id, sku, title, thumbnail, permalink, current_stock_full, last_synced_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        ml_credential_id = VALUES(ml_credential_id),
                        sku = VALUES(sku),
                        title = VALUES(title),
                        thumbnail = VALUES(thumbnail),
                        permalink = VALUES(permalink),
                        current_stock_full = VALUES(current_stock_full),
                        last_synced_at = NOW()
                """, (user_id, cred_id, item_id, sku, title, thumbnail, permalink, stock))

                cur.execute("SELECT lead_time_override, safety_stock_override FROM full_items WHERE user_id=%s AND item_id=%s", (user_id, item_id))
                irow = cur.fetchone()
                lt = irow["lead_time_override"] if irow and irow["lead_time_override"] is not None else default_lt
                ss = irow["safety_stock_override"] if irow and irow["safety_stock_override"] is not None else default_ss

            # Calcular ventas y pronóstico
            v7, v15, v30 = calculate_sales_velocity(access_token, meli_user_id, item_id)
            vpd = round((0.50 * (v7 / 7.0)) + (0.35 * (v15 / 15.0)) + (0.15 * (v30 / 30.0)), 2)

            if vpd > 0:
                days_left = round(stock / vpd, 1)
                stockout_date = today + timedelta(days=int(days_left))
                days_until_prep = days_left - (lt + ss)
                reorder_deadline = today + timedelta(days=max(0, int(days_until_prep)))
                suggested_restock = max(0, int(round((target_cov * vpd) - stock)))
            else:
                days_left = 999.0
                stockout_date = None
                reorder_deadline = None
                suggested_restock = 0

            if stock <= 0:
                status = 'out_of_stock'
            elif days_left <= lt:
                status = 'critical'
            elif days_left <= (lt + ss):
                status = 'warning'
            else:
                status = 'ok'

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO forecasts 
                    (user_id, item_id, sales_last_7d, sales_last_15d, sales_last_30d, vpd_weighted, days_left, stockout_date, reorder_deadline_date, suggested_restock_units, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                """, (user_id, item_id, v7, v15, v30, vpd, days_left, stockout_date, reorder_deadline, suggested_restock, status))

        print(f"[{datetime.now()}] Sync completada: user_id={user_id}, cred_id={cred_id}, {len(items)} items procesados.")
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
    conn.close()

    # Disparar evaluación de alertas para el usuario
    try:
        from alerts_engine import procesar_alertas_usuario
        res_alert = procesar_alertas_usuario(user_id)
        print(f"[{datetime.now()}] Alertas evaluadas para user_id={user_id}: {res_alert}")
    except Exception as e:
        print(f"[{datetime.now()}] Error evaluando alertas para user_id={user_id}: {e}")

def run_periodic_sync(skip_alerts: bool = False):
    """Ejecutado por Cron en producción para todos los clientes."""
    print(f"[{datetime.now()}] === Iniciando Sync Periódica EnvioBot Full ===")
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.user_id, c.ml_user_id, c.ml_access_token, c.ml_refresh_token, c.ml_token_expires_at, c.ml_nickname
            FROM ml_credentials c
            JOIN users u ON u.id = c.user_id
            WHERE u.active = 1
        """)
        creds = cur.fetchall()

    usuarios_procesados = set()
    for cred in creds:
        try:
            token = get_valid_token_for_cred(conn, cred)
            if token and cred.get("ml_user_id"):
                sync_account_full_catalog(cred["user_id"], cred["id"], token, cred["ml_user_id"])
                usuarios_procesados.add(cred["user_id"])
        except Exception as e:
            print(f"Error procesando cred {cred.get('id')}: {e}")

    conn.close()
    print(f"[{datetime.now()}] === Sync Periódica Finalizada ({len(usuarios_procesados)} usuarios sincronizados) ===")

    # Disparar motor de alertas para todos los usuarios sincronizados
    if not skip_alerts:
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
    else:
        run_periodic_sync()
