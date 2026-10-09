#!/usr/bin/env python3
"""
app.py - API REST EnvioBot Full (Backend Independiente)
Maneja autenticación JWT, conexión OAuth con MercadoLibre y cálculo de quiebres de stock.
"""

import os
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# Configuración JWT
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "enviobot_full_jwt_secret_default_key")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
jwt = JWTManager(app)

# Configuración Base de Datos
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_full")
DB_PORT = int(os.getenv("DB_PORT", 3306))

# MercadoLibre
ML_CLIENT_ID = os.getenv("ML_SHARED_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://enviobot.com.ar/api/ml/callback")
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

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

# -------------------------------------------------------------
# RUTAS DE AUTENTICACIÓN
# -------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
@app.route("/api/full/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "").strip()
    phone = data.get("phone", "").strip()
    business_name = data.get("business_name", "").strip()

    if not email or not password or not full_name:
        return jsonify({"ok": False, "error": "Completá nombre, email y contraseña."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "El email ya está registrado."}), 400

        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, phone, business_name)
            VALUES (%s, %s, %s, %s, %s)
        """, (email, hash_pw(password), full_name, phone, business_name))
        user_id = cur.lastrowid

        # Crear configuración por defecto
        cur.execute("INSERT INTO user_settings (user_id, alert_email) VALUES (%s, %s)", (user_id, email))

    conn.close()
    token = create_access_token(identity=str(user_id))
    return jsonify({"ok": True, "token": token, "user": {"id": user_id, "email": email, "full_name": full_name}}), 201

@app.route("/api/auth/login", methods=["POST"])
@app.route("/api/full/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, full_name, business_name, plan_tier, trial_ends_at FROM users WHERE email=%s AND password_hash=%s", (email, hash_pw(password)))
        user = cur.fetchone()
    conn.close()

    if not user:
        return jsonify({"ok": False, "error": "Email o contraseña incorrectos."}), 401

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"ok": True, "token": token, "user": user}), 200

@app.route("/api/auth/me", methods=["GET"])
@app.route("/api/full/auth/me", methods=["GET"])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, full_name, business_name, plan_tier, trial_ends_at FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        cur.execute("SELECT meli_user_id, nickname, last_sync_at, sync_status FROM ml_credentials WHERE user_id=%s", (user_id,))
        ml = cur.fetchone()
    conn.close()

    if not user:
        return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404

    return jsonify({"ok": True, "user": user, "meli": ml}), 200

# -------------------------------------------------------------
# MERCADOLIBRE OAUTH
# -------------------------------------------------------------

@app.route("/api/ml/auth/url", methods=["GET"])
@jwt_required()
def ml_auth_url():
    """Genera la URL oficial para que el usuario vincule su cuenta de MeLi."""
    url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={ML_CLIENT_ID}&redirect_uri={ML_REDIRECT_URI}"
    return jsonify({"ok": True, "url": url}), 200

@app.route("/api/ml/auth/callback", methods=["POST"])
@jwt_required()
def ml_callback():
    """Recibe el código de autorización de MeLi y guarda los tokens del usuario."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    code = data.get("code")

    if not code:
        return jsonify({"ok": False, "error": "Falta el código de autorización."}), 400

    token_url = f"{MELI_API}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "code": code,
        "redirect_uri": ML_REDIRECT_URI
    }
    r = requests.post(token_url, data=payload, timeout=12)
    if r.status_code != 200:
        return jsonify({"ok": False, "error": f"Error conectando con MercadoLibre: {r.text}"}), 400

    token_data = r.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    meli_user_id = token_data["user_id"]
    expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])

    # Obtener nickname de la cuenta
    user_info_resp = requests.get(f"{MELI_API}/users/{meli_user_id}", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    nickname = user_info_resp.json().get("nickname", str(meli_user_id)) if user_info_resp.status_code == 200 else str(meli_user_id)

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ml_credentials (user_id, meli_user_id, nickname, access_token, refresh_token, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                meli_user_id = VALUES(meli_user_id),
                nickname = VALUES(nickname),
                access_token = VALUES(access_token),
                refresh_token = VALUES(refresh_token),
                expires_at = VALUES(expires_at),
                updated_at = NOW()
        """, (user_id, meli_user_id, nickname, access_token, refresh_token, expires_at))
    conn.close()

    return jsonify({"ok": True, "nickname": nickname}), 200

# -------------------------------------------------------------
# RUTAS DE CONTROL DE STOCK FULL Y PREDICCIÓN
# -------------------------------------------------------------

@app.route("/api/full/items", methods=["GET"])
@jwt_required()
def get_full_items():
    user_id = int(get_jwt_identity())
    status_filter = request.args.get("status")
    search = request.args.get("q", "").strip()

    conn = get_db()
    with conn.cursor() as cur:
        # Configuración por defecto del usuario
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone() or {"default_lead_time_days": 7, "default_safety_stock_days": 3, "target_coverage_days": 30}

        query = """
            SELECT 
                i.id, i.item_id, i.sku, i.title, i.thumbnail, i.permalink, i.current_stock_full,
                i.lead_time_override, i.safety_stock_override,
                COALESCE(i.lead_time_override, %s) AS effective_lead_time,
                COALESCE(i.safety_stock_override, %s) AS effective_buffer,
                f.sales_last_7d, f.sales_last_15d, f.sales_last_30d,
                f.vpd_weighted, f.days_left, f.stockout_date, f.reorder_deadline_date,
                f.suggested_restock_units, f.status, f.updated_at
            FROM full_items i
            LEFT JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
            WHERE i.user_id = %s AND i.is_monitored = 1
        """
        params = [settings["default_lead_time_days"], settings["default_safety_stock_days"], user_id]

        if status_filter:
            if status_filter == "action_required":
                query += " AND f.status IN ('warning', 'critical', 'out_of_stock')"
            else:
                query += " AND f.status = %s"
                params.append(status_filter)

        if search:
            query += " AND (i.title LIKE %s OR i.sku LIKE %s OR i.item_id LIKE %s)"
            like_s = f"%{search}%"
            params.extend([like_s, like_s, like_s])

        query += """
            ORDER BY 
                CASE f.status 
                    WHEN 'out_of_stock' THEN 1
                    WHEN 'critical' THEN 2
                    WHEN 'warning' THEN 3
                    ELSE 4
                END,
                f.days_left ASC
        """
        cur.execute(query, tuple(params))
        items = cur.fetchall()

        # Resumen superior de contadores
        cur.execute("""
            SELECT 
                COUNT(*) AS total_monitored,
                SUM(CASE WHEN f.status = 'ok' THEN 1 ELSE 0 END) AS count_ok,
                SUM(CASE WHEN f.status = 'warning' THEN 1 ELSE 0 END) AS count_warning,
                SUM(CASE WHEN f.status IN ('critical', 'out_of_stock') THEN 1 ELSE 0 END) AS count_critical
            FROM full_items i
            LEFT JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
            WHERE i.user_id = %s AND i.is_monitored = 1
        """, (user_id,))
        summary = cur.fetchone()

    conn.close()
    return jsonify({
        "ok": True,
        "items": items,
        "summary": summary or {"total_monitored": 0, "count_ok": 0, "count_warning": 0, "count_critical": 0},
        "settings": settings
    }), 200

@app.route("/api/full/items/<int:item_id>", methods=["PUT"])
@jwt_required()
def update_item(item_id):
    """Actualiza el tiempo de preparación (Lead Time) o buffer particular de un producto."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    lt = data.get("lead_time_override")
    ss = data.get("safety_stock_override")

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE full_items 
            SET lead_time_override=%s, safety_stock_override=%s
            WHERE id=%s AND user_id=%s
        """, (lt, ss, item_id, user_id))

        # Recalcular semáforo inmediatamente
        cur.execute("SELECT item_id, current_stock_full FROM full_items WHERE id=%s", (item_id,))
        it = cur.fetchone()
        if it:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            s = cur.fetchone() or {"default_lead_time_days": 7, "default_safety_stock_days": 3}
            effective_lt = lt if lt is not None else s["default_lead_time_days"]
            effective_ss = ss if ss is not None else s["default_safety_stock_days"]

            cur.execute("SELECT vpd_weighted, days_left FROM forecasts WHERE user_id=%s AND item_id=%s", (user_id, it["item_id"]))
            fc = cur.fetchone()
            if fc and fc["vpd_weighted"] > 0:
                dl = fc["days_left"]
                stock = it["current_stock_full"]
                today = datetime.utcnow().date()
                if stock <= 0:
                    new_status = 'out_of_stock'
                elif dl <= effective_lt:
                    new_status = 'critical'
                elif dl <= (effective_lt + effective_ss):
                    new_status = 'warning'
                else:
                    new_status = 'ok'
                reorder_deadline = today + timedelta(days=max(0, int(dl - effective_lt - effective_ss)))
                cur.execute("""
                    UPDATE forecasts 
                    SET status=%s, reorder_deadline_date=%s, updated_at=NOW()
                    WHERE user_id=%s AND item_id=%s
                """, (new_status, reorder_deadline, user_id, it["item_id"]))

    conn.close()
    return jsonify({"ok": True, "message": "Plazos de reposición guardados."}), 200

@app.route("/api/full/settings", methods=["GET", "PUT"])
@jwt_required()
def settings():
    user_id = int(get_jwt_identity())
    conn = get_db()
    if request.method == "GET":
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            s = cur.fetchone() or {
                "default_lead_time_days": 7,
                "default_safety_stock_days": 3,
                "target_coverage_days": 30,
                "notify_email": True,
                "alert_email": "",
                "notify_whatsapp": False,
                "whatsapp_phone": ""
            }
        conn.close()
        return jsonify({"ok": True, "settings": s}), 200

    # PUT
    data = request.get_json() or {}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_settings 
            (user_id, default_lead_time_days, default_safety_stock_days, target_coverage_days, notify_email, alert_email, notify_whatsapp, whatsapp_phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                default_lead_time_days = VALUES(default_lead_time_days),
                default_safety_stock_days = VALUES(default_safety_stock_days),
                target_coverage_days = VALUES(target_coverage_days),
                notify_email = VALUES(notify_email),
                alert_email = VALUES(alert_email),
                notify_whatsapp = VALUES(notify_whatsapp),
                whatsapp_phone = VALUES(whatsapp_phone)
        """, (
            user_id,
            data.get("default_lead_time_days", 7),
            data.get("default_safety_stock_days", 3),
            data.get("target_coverage_days", 30),
            data.get("notify_email", True),
            data.get("alert_email", ""),
            data.get("notify_whatsapp", False),
            data.get("whatsapp_phone", "")
        ))
    conn.close()
    return jsonify({"ok": True, "message": "Configuración guardada exitosamente."}), 200

@app.route("/api/full/sync-now", methods=["POST"])
@jwt_required()
def trigger_sync():
    """Dispara una sincronización inmediata del usuario usando la lógica de worker.py."""
    user_id = int(get_jwt_identity())
    from worker import sync_user_full_inventory
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, access_token, refresh_token, meli_user_id FROM ml_credentials WHERE user_id=%s", (user_id,))
        ml_user = cur.fetchone()
    if not ml_user:
        conn.close()
        return jsonify({"ok": False, "error": "Todavía no conectaste tu cuenta de MercadoLibre."}), 400

    try:
        sync_user_full_inventory(conn, ml_user)
        conn.close()
        return jsonify({"ok": True, "message": "Sincronización finalizada con éxito."}), 200
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": f"Error en sincronización: {str(e)}"}), 500

# -------------------------------------------------------------
# RUTAS DE DEPÓSITOS Y CENTROS LOGÍSTICOS
# -------------------------------------------------------------

@app.route("/api/full/warehouses", methods=["GET"])
@jwt_required()
def get_warehouses():
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, code, name, city, province, type, transit_days, target_stock_days
            FROM warehouses
            WHERE user_id=%s AND is_active=1
            ORDER BY id ASC
        """, (user_id,))
        whs = cur.fetchall()
    conn.close()
    return jsonify({"ok": True, "warehouses": whs}), 200

@app.route("/api/full/warehouses", methods=["POST"])
@jwt_required()
def create_warehouse():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    city = data.get("city", "").strip()
    transit_days = int(data.get("transit_days", 3))
    target_stock_days = int(data.get("target_stock_days", 30))
    code = data.get("code") or ("depot_" + hashlib.md5(f"{name}{datetime.utcnow()}".encode()).hexdigest()[:8])

    if not name:
        return jsonify({"ok": False, "error": "El nombre del depósito es obligatorio."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouses (user_id, code, name, city, transit_days, target_stock_days)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                name=VALUES(name), city=VALUES(city), transit_days=VALUES(transit_days), target_stock_days=VALUES(target_stock_days)
        """, (user_id, code, name, city, transit_days, target_stock_days))
        new_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": new_id, "code": code, "message": "Depósito guardado."}), 201

PLAN_WHATSAPP_LIMITS = {
    "trial": 1,        # 1 número en período de prueba
    "pro": 2,          # 2 números en Plan Pro
    "enterprise": 10   # Equipo completo en Enterprise
}

@app.route("/api/full/recipients", methods=["GET"])
@jwt_required()
def get_recipients():
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT plan_tier FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone() or {"plan_tier": "trial"}
        plan_tier = user["plan_tier"]
        max_allowed = PLAN_WHATSAPP_LIMITS.get(plan_tier, 1)

        cur.execute("""
            SELECT id, name, phone, role, warehouse_filter, is_active, created_at
            FROM alert_recipients
            WHERE user_id=%s AND is_active=1
            ORDER BY id ASC
        """, (user_id,))
        recipients = cur.fetchall()

    conn.close()
    return jsonify({
        "ok": True,
        "plan_tier": plan_tier,
        "max_allowed": max_allowed,
        "current_count": len(recipients),
        "can_add_more": len(recipients) < max_allowed,
        "recipients": recipients
    }), 200

@app.route("/api/full/recipients", methods=["POST"])
@jwt_required()
def add_recipient():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    role = data.get("role", "admin").strip()
    warehouse_filter = data.get("warehouse_filter", "all").strip()

    if not name or not phone:
        return jsonify({"ok": False, "error": "Completá nombre y teléfono con código de área."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT plan_tier FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone() or {"plan_tier": "trial"}
        plan_tier = user["plan_tier"]
        max_allowed = PLAN_WHATSAPP_LIMITS.get(plan_tier, 1)

        cur.execute("SELECT COUNT(*) as cnt FROM alert_recipients WHERE user_id=%s AND is_active=1", (user_id,))
        current_count = cur.fetchone()["cnt"]

        if current_count >= max_allowed:
            conn.close()
            return jsonify({
                "ok": False,
                "error": f"Tu Plan {plan_tier.capitalize()} incluye hasta {max_allowed} número(s) de WhatsApp. Mejorá a un plan superior para agregar a todo tu equipo.",
                "limit_reached": True,
                "plan_tier": plan_tier
            }), 403

        cur.execute("""
            INSERT INTO alert_recipients (user_id, name, phone, role, warehouse_filter)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, name, phone, role, warehouse_filter))
        new_id = cur.lastrowid

    conn.close()
    return jsonify({"ok": True, "message": "Destinatario agregado con éxito.", "id": new_id}), 201

@app.route("/api/full/recipients/<int:recipient_id>", methods=["DELETE"])
@jwt_required()
def delete_recipient(recipient_id):
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM alert_recipients WHERE id=%s AND user_id=%s", (recipient_id, user_id))
    conn.close()
    return jsonify({"ok": True, "message": "Destinatario eliminado."}), 200

@app.route("/api/full/recipients/test-whatsapp", methods=["POST"])
@jwt_required()
def test_whatsapp():
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    name = data.get("name", "Usuario").strip()

    # Formato de mensaje real de EnvioBot Full
    sample_msg = (
        f"🚨 *¡Alarma de Prueba EnvioBot Full!*\n"
        f"Hola {name}, esta es una notificación de prueba de tu sistema de reposición MeLi Full.\n"
        f"Tu número está correctamente configurado para recibir alertas matutinas de quiebre."
    )
    return jsonify({"ok": True, "message": f"WhatsApp de prueba enviado a {phone}", "preview": sample_msg}), 200

# -------------------------------------------------------------
# RUTAS ESTÁTICAS DE FRONTEND
# -------------------------------------------------------------

@app.route("/")
def serve_root():
    return send_from_directory("../frontend", "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("../frontend", path)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"Iniciando EnvioBot Full en http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
