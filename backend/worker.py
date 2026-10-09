#!/usr/bin/env python3
"""
worker.py - Motor de Sincronización y Pronóstico de Quiebre de Stock (EnvioBot Full)
Corre de forma periódica en el servidor (via Cron o Systemd Timer) o a demanda por API.
"""

import os
import sys
import time
from datetime import datetime, timedelta
import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_full")
DB_PORT = int(os.getenv("DB_PORT", 3306))

ML_CLIENT_ID = os.getenv("ML_SHARED_CLIENT_ID", "")
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

def refresh_ml_token(conn, user_id, refresh_token):
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
            new_refresh = data["refresh_token"]
            expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ml_credentials 
                    SET access_token=%s, refresh_token=%s, expires_at=%s, updated_at=NOW()
                    WHERE user_id=%s
                """, (new_access, new_refresh, expires_at, user_id))
            print(f"[{datetime.now()}] Token renovado con éxito para usuario {user_id}")
            return new_access
        else:
            print(f"[{datetime.now()}] Error renovando token usuario {user_id}: {r.text}")
            return None
    except Exception as e:
        print(f"[{datetime.now()}] Excepción renovando token usuario {user_id}: {e}")
        return None

def fetch_full_publications(access_token, meli_user_id):
    """
    Recupera todas las publicaciones del vendedor que tienen logística Fulfillment (Full).
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    all_items = []
    limit = 50
    offset = 0

    while True:
        url = f"{MELI_API}/users/{meli_user_id}/items/search?shipping_modes=fulfillment&limit={limit}&offset={offset}"
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 401:
                return None # Requiere refresh
            if r.status_code != 200:
                print(f"Aviso buscando items: {r.status_code} - {r.text}")
                break

            data = r.json()
            item_ids = data.get("results", [])
            if not item_ids:
                break

            # Multiget de items para detalles completos
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
            time.sleep(0.15) # Rate limit friendly
        except Exception as e:
            print(f"Error extrayendo publicaciones: {e}")
            break

    return all_items

def calculate_sales_velocity(access_token, meli_user_id, item_id):
    """
    Calcula las unidades vendidas en los últimos 7, 15 y 30 días para un item.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    date_from = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000-03:00")
    url = f"{MELI_API}/orders/search?seller={meli_user_id}&item={item_id}&order.date_created.from={date_from}&order.status=paid"

    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return 0, 0, 0

        orders = r.json().get("results", [])
        now = datetime.utcnow()
        v7, v15, v30 = 0, 0, 0

        for order in orders:
            try:
                date_str = order.get("date_created", "")[:19]
                order_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                diff_days = (now - order_date).days
            except Exception:
                diff_days = 0

            units = 0
            for it in order.get("order_items", []):
                if it.get("item", {}).get("id") == item_id:
                    units += it.get("quantity", 1)

            if diff_days <= 7:
                v7 += units
            if diff_days <= 15:
                v15 += units
            if diff_days <= 30:
                v30 += units

        return v7, v15, v30
    except Exception:
        return 0, 0, 0

def sync_user_full_inventory(conn, user):
    user_id = user["user_id"]
    access_token = user["access_token"]
    refresh_token = user["refresh_token"]
    meli_user_id = user["meli_user_id"]

    print(f"[{datetime.now()}] Iniciando sync para usuario {user_id} (ML: {meli_user_id})...")

    # Marcar estado de sincronización
    with conn.cursor() as cur:
        cur.execute("UPDATE ml_credentials SET sync_status='syncing' WHERE user_id=%s", (user_id,))
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone()
        if not settings:
            cur.execute("INSERT INTO user_settings (user_id) VALUES (%s)", (user_id,))
            default_lt = 7
            default_ss = 3
            target_cov = 30
        else:
            default_lt = settings["default_lead_time_days"]
            default_ss = settings["default_safety_stock_days"]
            target_cov = settings["target_coverage_days"]

    # Traer publicaciones en Full
    items = fetch_full_publications(access_token, meli_user_id)
    if items is None:
        # Reintentar tras refrescar token
        access_token = refresh_ml_token(conn, user_id, refresh_token)
        if access_token:
            items = fetch_full_publications(access_token, meli_user_id)

    if items is None:
        with conn.cursor() as cur:
            cur.execute("UPDATE ml_credentials SET sync_status='error', last_error='Error de autenticación' WHERE user_id=%s", (user_id,))
        return

    processed_count = 0
    today = datetime.utcnow().date()

    for item in items:
        item_id = item.get("id")
        title = item.get("title", "")
        sku = item.get("seller_custom_field") or ""
        stock = item.get("available_quantity", 0)
        thumbnail = item.get("thumbnail")
        permalink = item.get("permalink")

        # Guardar en full_items
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO full_items 
                (user_id, item_id, sku, title, thumbnail, permalink, current_stock_full, last_synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    sku = VALUES(sku),
                    title = VALUES(title),
                    thumbnail = VALUES(thumbnail),
                    permalink = VALUES(permalink),
                    current_stock_full = VALUES(current_stock_full),
                    last_synced_at = NOW()
            """, (user_id, item_id, sku, title, thumbnail, permalink, stock))

            cur.execute("SELECT lead_time_override, safety_stock_override FROM full_items WHERE user_id=%s AND item_id=%s", (user_id, item_id))
            item_row = cur.fetchone()
            lt = item_row["lead_time_override"] if item_row and item_row["lead_time_override"] is not None else default_lt
            ss = item_row["safety_stock_override"] if item_row and item_row["safety_stock_override"] is not None else default_ss

        # Calcular ventas históricas y run-rate (VPD)
        v7, v15, v30 = calculate_sales_velocity(access_token, meli_user_id, item_id)
        vpd = round((0.50 * (v7 / 7.0)) + (0.35 * (v15 / 15.0)) + (0.15 * (v30 / 30.0)), 2)

        # Proyección de quiebre y fecha de pedido
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

        # Determinación de estado del semáforo
        if stock <= 0:
            status = 'out_of_stock'
        elif days_left <= lt:
            status = 'critical'  # Ya no llega a tiempo con su tiempo de reposición normal
        elif days_left <= (lt + ss):
            status = 'warning'   # MOMENTO EXACTO PARA PREPARAR EL ENVÍO
        else:
            status = 'ok'

        # Guardar pronóstico
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

        processed_count += 1
        time.sleep(0.08) # Pausa mínima para no ahogar la API de MeLi

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ml_credentials 
            SET sync_status='idle', last_sync_at=NOW(), last_error=NULL 
            WHERE user_id=%s
        """, (user_id,))

    print(f"[{datetime.now()}] Finalizado sync usuario {user_id}. {processed_count} publicaciones procesadas.")

def run_worker():
    print(f"[{datetime.now()}] === EnvioBot Full Worker Iniciado ===")
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.user_id, c.access_token, c.refresh_token, c.meli_user_id
            FROM ml_credentials c
            JOIN users u ON u.id = c.user_id
            WHERE u.is_active = 1
        """)
        users = cur.fetchall()

    for user in users:
        try:
            sync_user_full_inventory(conn, user)
        except Exception as e:
            print(f"[{datetime.now()}] Error procesando usuario {user['user_id']}: {e}")

    conn.close()
    print(f"[{datetime.now()}] === EnvioBot Full Worker Finalizado ===")

if __name__ == "__main__":
    run_worker()
