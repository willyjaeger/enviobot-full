#!/usr/bin/env python3
"""
app.py - API REST EnvioBot Full (Backend Unificado con EnvioBot Web)
Maneja autenticación unificada, suscripciones con 30 días de prueba,
multicuenta MeLi, multiusuario y cálculo de quiebres de stock Full.
"""

import os
import time
import base64
import hashlib
import hmac
import re
import secrets
import threading
from urllib.parse import urlencode
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, redirect, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
)
import pymysql
import requests
from dotenv import load_dotenv

from whatsapp_service import (
    enviar_mensaje_whatsapp, enviar_contacto_vcard, enviar_verificacion_whatsapp,
    WHATSAPP_SIMULATION_MODE, EVOLUTION_API_URL, WHATSAPP_GATEWAY_URL
)
from alerts_engine import procesar_alertas_usuario
from email_service import enviar_email, enviar_email_prueba, enviar_email_bienvenida_verificacion
import equipo as _equipo
from inbound_service import render_remito_html

load_dotenv()

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# Configuración JWT
if not os.getenv("JWT_SECRET_KEY"):
    raise RuntimeError("Falta JWT_SECRET_KEY en el .env: la app no arranca sin clave propia.")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=30)
jwt = JWTManager(app)

# Configuración Base de Datos (Conectado a enviobot_web)
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

# MercadoLibre App (EnvioBot Full)
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", os.getenv("ML_SHARED_CLIENT_ID", "1845856849463362"))
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://enviobot.com.ar/api/full/ml/auth/callback")
MELI_API = "https://api.mercadolibre.com"

# Límites según el plan configurado en admin.enviobot.com.ar
PLAN_LIMITS = {
    "trial": {"name": "Prueba Gratis (30 días)", "max_ml_accounts": 1, "max_recipients": 2, "max_warehouses": 2},
    "gratis": {"name": "Gratis", "max_ml_accounts": 1, "max_recipients": 1, "max_warehouses": 1},
    "pro": {"name": "Pro", "max_ml_accounts": 3, "max_recipients": 5, "max_warehouses": 5},
    "plus": {"name": "Pro Plus", "max_ml_accounts": 5, "max_recipients": 10, "max_warehouses": 10},
    "empresarial": {"name": "Empresarial", "max_ml_accounts": 999, "max_recipients": 999, "max_warehouses": 999},
}

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

def init_verification_tables():
    """Inicializa la tabla de códigos de verificación y columnas de estado."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_codes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    channel VARCHAR(20) NOT NULL,
                    destination VARCHAR(255) NOT NULL,
                    code VARCHAR(10) NOT NULL,
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verified_at TIMESTAMP NULL,
                    INDEX idx_user_dest (user_id, channel, destination),
                    INDEX idx_code (code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            try:
                cur.execute("SHOW COLUMNS FROM user_settings LIKE 'email_verified'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE user_settings ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM user_settings LIKE 'sync_frequency_hours'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE user_settings ADD COLUMN sync_frequency_hours INT NOT NULL DEFAULT 4")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM user_settings LIKE 'last_sync_at'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE user_settings ADD COLUMN last_sync_at DATETIME NULL")
            except Exception:
                pass

            # Migración automática para Co-Branding y Personalización de Marca
            for b_col, b_def in [
                ("brand_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("brand_name", "VARCHAR(150) NULL"),
                ("brand_logo_url", "MEDIUMTEXT NULL"),
                ("brand_primary_color", "VARCHAR(25) NULL"),
                ("brand_show_powered_by", "BOOLEAN NOT NULL DEFAULT TRUE")
            ]:
                try:
                    cur.execute(f"SHOW COLUMNS FROM user_settings LIKE '{b_col}'")
                    if not cur.fetchone():
                        cur.execute(f"ALTER TABLE user_settings ADD COLUMN {b_col} {b_def}")
                except Exception:
                    pass

            try:
                cur.execute("SHOW COLUMNS FROM alert_recipients LIKE 'is_verified'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE alert_recipients ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT FALSE")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'is_blocked'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT FALSE")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'admin_notes'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN admin_notes TEXT NULL")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'must_change_password'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM user_features LIKE 'is_blocked'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE user_features ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT FALSE")
            except Exception:
                pass

            try:
                cur.execute("SHOW COLUMNS FROM user_features LIKE 'admin_notes'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE user_features ADD COLUMN admin_notes TEXT NULL")
            except Exception:
                pass

            # Asegurar columnas de inventario físico y consolidación en full_items
            full_items_cols = [
                ("ml_credential_id", "INT NULL"),
                ("variation_id", "VARCHAR(50) NULL"),
                ("variation_name", "VARCHAR(150) NULL"),
                ("inventory_id", "VARCHAR(50) NULL"),
                ("listing_type_id", "VARCHAR(50) NULL"),
                ("is_catalog", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("status", "VARCHAR(30) NOT NULL DEFAULT 'active'"),
                ("current_stock_full", "INT NOT NULL DEFAULT 0"),
                ("not_available_stock_full", "INT NOT NULL DEFAULT 0"),
                ("lead_time_override", "INT NULL"),
                ("safety_stock_override", "INT NULL"),
            ]
            for col_name, col_def in full_items_cols:
                try:
                    cur.execute(f"SHOW COLUMNS FROM full_items LIKE '{col_name}'")
                    if not cur.fetchone():
                        cur.execute(f"ALTER TABLE full_items ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

            try:
                cur.execute("SHOW COLUMNS FROM ml_credentials LIKE 'ml_nickname'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE ml_credentials ADD COLUMN ml_nickname VARCHAR(100) NULL AFTER ml_user_id")
            except Exception:
                pass

            # Tablas de Colectas e Inbound Shipments a Mercado Libre Full
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inbound_shipments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    ml_credential_id INT NULL,
                    shipment_code VARCHAR(50) NOT NULL UNIQUE,
                    destination_warehouse VARCHAR(50) NOT NULL DEFAULT 'meli_full',
                    destination_name VARCHAR(150) NOT NULL DEFAULT 'Mercado Envíos Full (Villa Celina)',
                    status ENUM('draft', 'scheduled', 'in_transit', 'delivered', 'cancelled') NOT NULL DEFAULT 'scheduled',
                    target_coverage_days INT NOT NULL DEFAULT 30,
                    lead_time_days INT NOT NULL DEFAULT 2,
                    transit_days INT NOT NULL DEFAULT 3,
                    total_items INT NOT NULL DEFAULT 0,
                    total_units INT NOT NULL DEFAULT 0,
                    total_boxes INT NOT NULL DEFAULT 1,
                    packaging_type VARCHAR(50) NOT NULL DEFAULT 'cajas_master',
                    carrier_notes TEXT NULL,
                    pickup_date DATE NULL,
                    estimated_arrival_date DATE NULL,
                    meli_inbound_id VARCHAR(100) NULL,
                    meli_inbound_status VARCHAR(50) NULL,
                    meli_sync_payload TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user_shipments (user_id, status),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS inbound_shipment_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    shipment_id INT NOT NULL,
                    item_id VARCHAR(50) NOT NULL,
                    inventory_id VARCHAR(50) NULL,
                    variation_id VARCHAR(50) NULL,
                    variation_name VARCHAR(150) NULL,
                    sku VARCHAR(100) NULL,
                    title VARCHAR(255) NOT NULL,
                    current_full_stock INT NOT NULL DEFAULT 0,
                    vpd DECIMAL(10,2) NOT NULL DEFAULT 0,
                    suggested_units INT NOT NULL DEFAULT 0,
                    units_to_send INT NOT NULL DEFAULT 0,
                    units_per_box INT NOT NULL DEFAULT 0,
                    box_count INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_shipment_items (shipment_id),
                    FOREIGN KEY (shipment_id) REFERENCES inbound_shipments(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

        conn.close()
    except Exception as e:
        print(f"[Verification Tables Init Notice] {e}")

try:
    init_verification_tables()
except Exception:
    pass

# -------------------------------------------------------------
# HASHING Y VERIFICACIÓN COMPATIBLE CON ENVIOBOT PEDIDOS (SCRYPT/MD5/SHA256)
# -------------------------------------------------------------
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_LEGACY_MD5_RE = re.compile(r'^[0-9a-f]{32}$')

def hash_pw(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode('utf-8'), salt=salt,
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return 'scrypt${}${}${}${}${}'.format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode('ascii'),
        base64.b64encode(dk).decode('ascii')
    )

def verify_pw(password_input: str, password_hash: str) -> bool:
    if not password_hash or not password_input:
        return False
    if password_hash.startswith('scrypt$'):
        try:
            _, n, r, p, salt_b64, dk_b64 = password_hash.split('$')
            expected = base64.b64decode(dk_b64)
            dk = hashlib.scrypt(
                password_input.encode('utf-8'), salt=base64.b64decode(salt_b64),
                n=int(n), r=int(r), p=int(p), dklen=len(expected)
            )
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False
    # Compatibilidad con SHA-256
    if len(password_hash) == 64 and not password_hash.startswith('scrypt'):
        return hmac.compare_digest(hashlib.sha256(password_input.encode()).hexdigest(), password_hash)
    # Compatibilidad con MD5 legacy
    if _LEGACY_MD5_RE.match(password_hash):
        return hmac.compare_digest(hashlib.md5(password_input.encode()).hexdigest(), password_hash)
    return False

def get_user_full_subscription(user_id, conn):
    """
    Verifica suscripción a EnvioBot Full consultando directamente los campos de la tabla users:
    - has_full: TINYINT(1) -> 1 si tiene acceso a Full, 0 si no.
    - has_pedidos: TINYINT(1) -> 1 si tiene acceso a Pedidos, 0 si no.
    - is_blocked: TINYINT(1) -> 1 si está bloqueado.
    - admin_notes: TEXT -> Observaciones.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, email, 
                   COALESCE(has_full, 0) AS has_full,
                   COALESCE(has_pedidos, 1) AS has_pedidos,
                   COALESCE(has_inbound, 0) AS has_inbound,
                   COALESCE(is_blocked, 0) AS is_blocked,
                   COALESCE(is_admin, 0) AS is_admin,
                   COALESCE(admin_notes, '') AS admin_notes
            FROM users WHERE id=%s
        """, (user_id,))
        u = cur.fetchone()

    if not u:
        return {
            "has_full_access": False,
            "has_inbound": False,
            "is_active": False,
            "is_blocked": False,
            "is_expired": False,
            "subscription_status": "not_found",
            "plan_tier": "none",
            "plan_name": "Usuario no encontrado",
            "can_start_trial": True,
            "trial_days_left": 0,
            "trial_ends_at": None,
            "admin_notes": "",
            "has_pedidos": False,
            "has_full": False,
            "limits": PLAN_LIMITS["trial"]
        }

    email = (u.get("email") or "").lower()
    is_admin = bool(u.get("is_admin", 0)) or email in ("guillermo.jaeger@gmail.com", "admin@enviobot.com.ar")

    is_blocked = bool(u.get("is_blocked", 0))
    if is_blocked:
        return {
            "has_full_access": False,
            "has_inbound": False,
            "is_active": False,
            "is_blocked": True,
            "is_expired": False,
            "subscription_status": "blocked",
            "plan_tier": "none",
            "plan_name": "Usuario Bloqueado",
            "can_start_trial": False,
            "trial_days_left": 0,
            "trial_ends_at": None,
            "admin_notes": u.get("admin_notes", ""),
            "has_pedidos": bool(u.get("has_pedidos", 1)),
            "has_full": False,
            "limits": PLAN_LIMITS["trial"]
        }

    has_full = bool(u.get("has_full", 0)) or is_admin
    has_inbound = bool(u.get("has_inbound", 0)) or is_admin

    return {
        "has_full_access": has_full,
        "has_inbound": has_inbound,
        "is_active": has_full,
        "is_blocked": False,
        "is_expired": False,
        "subscription_status": "active" if has_full else "not_subscribed",
        "plan_tier": "pro" if has_full else "none",
        "plan_name": "EnvioBot Full" if has_full else "Sin acceso a Full",
        "can_start_trial": not has_full,
        "trial_days_left": 30 if has_full else 0,
        "trial_ends_at": None,
        "admin_notes": u.get("admin_notes", ""),
        "has_pedidos": bool(u.get("has_pedidos", 1)),
        "has_full": has_full,
        "limits": PLAN_LIMITS["pro"] if has_full else PLAN_LIMITS["trial"]
    }

def get_user_plan_info(user_id, conn):
    """Alias compatible con llamadas previas."""
    return get_user_full_subscription(user_id, conn)

def is_admin_user(user_id):
    """Verifica si el usuario actual tiene permisos de administrador."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT email, COALESCE(is_admin, 0) AS is_admin FROM users WHERE id=%s", (user_id,))
        u = cur.fetchone()
    conn.close()
    if not u:
        return False
    if u.get("is_admin"):
        return True
    email = (u.get("email") or "").lower()
    return email in ("guillermo.jaeger@gmail.com", "admin@enviobot.com.ar")

def get_account_user_id(user_id, conn=None):
    """
    Retorna el ID de la cuenta titular.
    Si el usuario es un colaborador o empleado invitado (owner_id no nulo),
    retorna owner_id. Si es la cuenta principal, retorna su propio ID.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, owner_id FROM users WHERE id=%s", (user_id,))
            u = cur.fetchone()
            if u and u.get("owner_id"):
                return int(u["owner_id"])
            # Equipo prendido: un usuario vinculado al abono de otro (por ejemplo uno de
            # EnvioBot Pedidos) trabaja sobre la cuenta del titular. Sin "equipo", igual que siempre.
            try:
                cur.execute("SELECT abono_de FROM users WHERE id=%s", (user_id,))
                ab = cur.fetchone()
                if ab and ab.get("abono_de") and _equipo.equipo_activo(cur, user_id):
                    return int(_equipo.raiz(cur, user_id))
            except Exception:
                pass
            return int(user_id)
    finally:
        if should_close:
            conn.close()


def _mail_equipo(to_email, to_name, asunto, html, texto):
    """True solo si el mail salió de verdad (en modo simulación no cuenta como enviado)."""
    r = enviar_email(to_email, asunto, texto, html)
    return bool(r.get("ok")) and not r.get("simulated")


# Pantalla Equipo (roles, invitaciones y cuentas visibles). Apagada salvo que el admin la
# prenda a mano para un abono: ver backend/equipo.py.
_equipo.init(app, get_db, _mail_equipo, enviar_mensaje_whatsapp, hash_pw,
             os.getenv("APP_URL", "https://enviobot.com.ar/full"))


def _equipo_prendido(user_id):
    """¿Tiene "equipo" prendido este usuario? Para frenar los endpoints viejos de equipo."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            return _equipo.equipo_activo(cur, user_id)
    except Exception:
        return False
    finally:
        conn.close()

# -------------------------------------------------------------
# RUTAS DE AUTENTICACIÓN (LOGIN / SIGNUP FACILITADO)
# -------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
@app.route("/api/full/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    full_name = data.get("full_name", "").strip() or email.split("@")[0]
    business_name = data.get("business_name", "").strip()

    if not email or not password:
        return jsonify({"ok": False, "error": "Completá email y contraseña."}), 400

    if len(password) < 6:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 6 caracteres."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, email, password_hash, full_name, business_name, 
                   COALESCE(is_blocked, 0) AS is_blocked,
                   COALESCE(has_pedidos, 1) AS has_pedidos,
                   COALESCE(has_full, 0) AS has_full
            FROM users WHERE email=%s LIMIT 1
        """, (email,))
        existing_user = cur.fetchone()

        if existing_user:
            # El email ya existe en EnvioBot (por ejemplo, cliente de Pedidos)
            if existing_user.get("is_blocked"):
                conn.close()
                return jsonify({"ok": False, "blocked": True, "error": "Tu cuenta se encuentra bloqueada por la administración. Comunicate con soporte."}), 403

            # Validar si usó la misma contraseña
            if verify_pw(password, existing_user["password_hash"]):
                user_id = existing_user["id"]
                # Habilitar Full con un tilde
                cur.execute("UPDATE users SET has_full = 1 WHERE id = %s", (user_id,))
                
                # Cuentas MeLi vinculadas
                cur.execute("""
                    SELECT id, ml_user_id, ml_nickname,
                           (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_valid
                    FROM ml_credentials WHERE user_id = %s ORDER BY id ASC
                """, (user_id,))
                ml_accounts = cur.fetchall() or []

                conn.close()
                token = create_access_token(identity=str(user_id))
                return jsonify({
                    "ok": True,
                    "token": token,
                    "existing_user_linked": True,
                    "message": "Detectamos tu cuenta existente de EnvioBot. Se habilitó EnvioBot Full con tu contraseña habitual.",
                    "user": {
                        "id": user_id,
                        "email": existing_user["email"],
                        "full_name": existing_user["full_name"],
                        "business_name": existing_user["business_name"],
                        "is_admin": is_admin_user(user_id),
                        "is_blocked": False,
                        "has_full_access": True,
                        "has_pedidos": bool(existing_user.get("has_pedidos", 1)),
                        "has_full": True,
                        "subscription_status": "active",
                        "can_start_trial": False,
                        "plan_tier": "full",
                        "plan_name": "EnvioBot Full",
                        "trial_days_left": 30,
                        "ml_accounts": ml_accounts
                    },
                    "requires_ml_connect": len(ml_accounts) == 0
                }), 200
            else:
                conn.close()
                return jsonify({
                    "ok": False,
                    "already_registered": True,
                    "error": "Ya tenés una cuenta en EnvioBot con este correo. Ingresá la misma contraseña que usás en EnvioBot Pedidos para activar Full."
                }), 400

        # Crear nuevo usuario si no existía previamente
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, business_name, platform, has_pedidos, has_full)
            VALUES (%s, %s, %s, %s, 'ml', 0, 1)
        """, (email, hash_pw(password), full_name, business_name))
        user_id = cur.lastrowid

        cur.execute("""
            INSERT IGNORE INTO user_settings (user_id, alert_email)
            VALUES (%s, %s)
        """, (user_id, email))

    conn.close()
    token = create_access_token(identity=str(user_id))
    return jsonify({
        "ok": True,
        "token": token,
        "existing_user_linked": False,
        "message": "Cuenta creada con éxito. Activamos tu prueba en EnvioBot Full.",
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "business_name": business_name,
            "is_admin": is_admin_user(user_id),
            "is_blocked": False,
            "has_full_access": True,
            "has_pedidos": False,
            "has_full": True,
            "subscription_status": "active",
            "can_start_trial": False,
            "plan_tier": "full",
            "plan_name": "EnvioBot Full",
            "trial_days_left": 30,
            "ml_accounts": []
        },
        "requires_ml_connect": True
    }), 201

@app.route("/api/auth/login", methods=["POST"])
@app.route("/api/full/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"ok": False, "error": "Ingresá email y contraseña."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, email, password_hash, full_name, business_name, owner_id, employee_label,
                   COALESCE(has_pedidos, 0) AS has_pedidos, COALESCE(has_full, 0) AS has_full,
                   COALESCE(must_change_password, 0) AS must_change_password,
                   COALESCE(is_blocked, 0) AS is_blocked, admin_notes
            FROM users
            WHERE email = %s LIMIT 1
        """, (email,))
        user = cur.fetchone()

        if not user or not verify_pw(password, user["password_hash"]):
            conn.close()
            # Si el usuario ya existe en EnvioBot Pedidos y prueba con 123456
            if user and password == "123456" and user.get("has_pedidos"):
                return jsonify({
                    "ok": False,
                    "is_pedidos_user": True,
                    "error": "Detectamos que ya tenés cuenta en EnvioBot Pedidos. Para ingresar a EnvioBot Full debés usar la contraseña habitual que utilizás en la otra aplicación (no la clave inicial 123456)."
                }), 401
            return jsonify({"ok": False, "error": "Email o contraseña incorrectos."}), 401

        if user.get("is_blocked"):
            conn.close()
            return jsonify({"ok": False, "blocked": True, "error": "Tu cuenta se encuentra bloqueada por la administración. Comunicate con soporte."}), 403

        user_id = user["id"]
        account_id = get_account_user_id(user_id, conn)

        # Cuentas de MeLi vinculadas (de la cuenta titular)
        cur.execute("""
            SELECT id, ml_user_id, ml_nickname,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_valid
            FROM ml_credentials
            WHERE user_id = %s
            ORDER BY id ASC
        """, (account_id,))
        ml_accounts = cur.fetchall()

    with conn.cursor() as cur:
        visibles = _equipo.cuentas_visibles(cur, user_id)
    if visibles is not None:
        ml_accounts = [a for a in ml_accounts if a["ml_user_id"] in visibles]
    plan_info = get_user_plan_info(account_id, conn)
    conn.close()

    token = create_access_token(identity=str(user_id))
    must_change = bool(user.get("must_change_password", 0)) or (password == "123456" and not user.get("has_pedidos"))

    return jsonify({
        "ok": True,
        "token": token,
        "must_change_password": must_change,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "business_name": user["business_name"],
            "owner_id": user.get("owner_id"),
            "employee_label": user.get("employee_label"),
            "is_admin": is_admin_user(user_id),
            "is_blocked": bool(user.get("is_blocked", 0)),
            "admin_notes": user.get("admin_notes") or "",
            "has_full_access": plan_info["has_full_access"],
            "can_start_trial": plan_info["can_start_trial"],
            "is_expired": plan_info.get("is_expired", False),
            "plan_tier": plan_info["plan_tier"],
            "plan_name": plan_info["plan_name"],
            "subscription_status": plan_info["subscription_status"],
            "trial_days_left": plan_info["trial_days_left"],
            "trial_ends_at": plan_info["trial_ends_at"],
            "must_change_password": must_change,
            "has_pedidos": bool(user.get("has_pedidos", 0)),
            "has_full": bool(user.get("has_full", 0)),
            "ml_accounts": ml_accounts or []
        }
    }), 200

@app.route("/api/auth/change-password", methods=["POST"])
@app.route("/api/full/auth/change-password", methods=["POST"])
@jwt_required()
def change_user_password():
    """Permite al usuario (o colaborador que ingresó con clave temporal) establecer su nueva clave personal."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    new_password = data.get("new_password", "").strip()

    if len(new_password) < 6:
        return jsonify({"ok": False, "error": "La nueva contraseña debe tener al menos 6 caracteres."}), 400
    if new_password == "123456":
        return jsonify({"ok": False, "error": "Debés elegir una contraseña personal diferente a la clave inicial 123456."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        p_hash = hash_pw(new_password)
        cur.execute("""
            UPDATE users
            SET password_hash = %s, must_change_password = 0
            WHERE id = %s
        """, (p_hash, user_id))
    conn.close()
    return jsonify({"ok": True, "message": "Contraseña actualizada exitosamente."}), 200

@app.route("/api/auth/me", methods=["GET"])
@app.route("/api/full/auth/me", methods=["GET"])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, email, full_name, business_name, owner_id, employee_label,
                   COALESCE(is_blocked, 0) AS is_blocked, admin_notes
            FROM users WHERE id=%s
        """, (user_id,))
        user = cur.fetchone()
        if not user:
            conn.close()
            return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404

        if user.get("is_blocked"):
            conn.close()
            return jsonify({"ok": False, "blocked": True, "error": "Tu cuenta ha sido bloqueada por la administración."}), 403

        account_id = get_account_user_id(user_id, conn)

        cur.execute("""
            SELECT id, ml_user_id, ml_nickname,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_valid
            FROM ml_credentials
            WHERE user_id = %s
            ORDER BY id ASC
        """, (account_id,))
        ml_accounts = cur.fetchall()
        visibles = _equipo.cuentas_visibles(cur, user_id)
        if visibles is not None:
            ml_accounts = [a for a in ml_accounts if a["ml_user_id"] in visibles]

    plan_info = get_user_plan_info(account_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "business_name": user["business_name"],
            "owner_id": user.get("owner_id"),
            "employee_label": user.get("employee_label"),
            "is_admin": is_admin_user(user_id),
            "is_blocked": bool(user.get("is_blocked", 0)),
            "admin_notes": user.get("admin_notes") or "",
            "has_full_access": plan_info["has_full_access"],
            "can_start_trial": plan_info["can_start_trial"],
            "is_expired": plan_info.get("is_expired", False),
            "plan_tier": plan_info["plan_tier"],
            "plan_name": plan_info["plan_name"],
            "subscription_status": plan_info["subscription_status"],
            "trial_days_left": plan_info["trial_days_left"],
            "trial_ends_at": plan_info["trial_ends_at"],
            "limits": plan_info["limits"],
            "ml_accounts": ml_accounts or []
        }
    }), 200

@app.route("/api/auth/activate-trial", methods=["POST"])
@app.route("/api/full/auth/activate-trial", methods=["POST"])
@jwt_required()
def activate_full_trial():
    """Activa los 30 días de prueba gratuita de EnvioBot Full para un usuario existente."""
    user_id = int(get_jwt_identity())
    conn = get_db()

    sub = get_user_full_subscription(user_id, conn)
    if sub.get("is_blocked"):
        conn.close()
        return jsonify({
            "ok": False,
            "error": "Tu cuenta se encuentra bloqueada por la administración."
        }), 403
    if sub.get("has_full_access"):
        conn.close()
        return jsonify({
            "ok": True,
            "message": "Ya contás con acceso activo a EnvioBot Full.",
            "plan_info": sub
        }), 200

    if not sub.get("can_start_trial") and sub.get("is_expired"):
        conn.close()
        return jsonify({
            "ok": False,
            "error": "Tu período de prueba de 30 días de EnvioBot Full ya venció. Contactate con nosotros o desde admin.enviobot.com.ar para activar tu plan."
        }), 400

    with conn.cursor() as cur:
        cur.execute("UPDATE users SET has_full = 1 WHERE id = %s", (user_id,))
        cur.execute("INSERT IGNORE INTO user_settings (user_id) VALUES (%s)", (user_id,))
    conn.close()

    conn2 = get_db()
    new_sub = get_user_full_subscription(user_id, conn2)
    conn2.close()

    return jsonify({
        "ok": True,
        "message": "¡EnvioBot Full habilitado con éxito!",
        "requires_ml_connect": True,
        "plan_info": new_sub
    }), 200

# -------------------------------------------------------------
# MERCADOLIBRE OAUTH PKCE (MULTICUENTA Y CONEXIÓN AL REGISTRO)
# -------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def generate_pkce_pair():
    code_verifier = _b64url(secrets.token_bytes(64))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode('ascii')).digest())
    return code_verifier, code_challenge

def save_oauth_state(state: str, user_id, code_verifier: str):
    """Guarda estado OAuth PKCE en MySQL para soportar múltiples workers de Gunicorn."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM oauth_states WHERE created_at < NOW() - INTERVAL 30 MINUTE")
            cur.execute("""
                INSERT INTO oauth_states (state, user_id, code_verifier)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE user_id=VALUES(user_id), code_verifier=VALUES(code_verifier), created_at=NOW()
            """, (state, user_id, code_verifier))
    except Exception as e:
        print(f"Error guardando oauth_state: {e}")
    finally:
        conn.close()

def pop_oauth_state(state: str):
    """Recupera y consume de forma atómica el estado OAuth PKCE."""
    if not state:
        return None
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, code_verifier FROM oauth_states WHERE state=%s", (state,))
            row = cur.fetchone()
            if row:
                cur.execute("DELETE FROM oauth_states WHERE state=%s", (state,))
            return row
    except Exception as e:
        print(f"Error recuperando oauth_state: {e}")
        return None
    finally:
        conn.close()

@app.route("/api/ml/auth/login", methods=["GET"])
@app.route("/api/full/ml/auth/login", methods=["GET"])
def ml_auth_login():
    """Genera URL oficial OAuth PKCE de MercadoLibre. Soporta tanto usuarios logueados como nuevos clientes en prueba."""
    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        jwt_id = get_jwt_identity()
        if jwt_id:
            user_id = int(jwt_id)
    except Exception:
        user_id = None

    if user_id:
        conn = get_db()
        cuenta_id = user_id
        with conn.cursor() as cur:
            # Equipo prendido: solo un administrador conecta cuentas, y quedan en la cuenta del negocio.
            if _equipo.equipo_activo(cur, user_id):
                if _equipo.rol_de(cur, user_id) != "admin":
                    conn.close()
                    return jsonify({"ok": False, "error": "Solo un administrador de tu equipo puede conectar cuentas de MercadoLibre."}), 403
                cuenta_id = get_account_user_id(user_id, conn)
        plan_info = get_user_plan_info(cuenta_id, conn)
        max_accs = plan_info["limits"]["max_ml_accounts"]
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM ml_credentials WHERE user_id=%s", (cuenta_id,))
            current_accs = cur.fetchone()["count"]
        conn.close()

        if current_accs >= max_accs:
            return jsonify({
                "ok": False,
                "error": f"Tu plan actual ({plan_info['plan_name']}) permite hasta {max_accs} cuenta(s) de MercadoLibre. Contactate para mejorar tu plan si necesitás más."
            }), 403

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    save_oauth_state(state, user_id, code_verifier)

    params = {
        'response_type': 'code',
        'client_id': ML_CLIENT_ID,
        'redirect_uri': ML_REDIRECT_URI,
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256'
    }
    auth_url = 'https://auth.mercadolibre.com.ar/authorization?' + urlencode(params)
    return jsonify({'ok': True, 'auth_url': auth_url}), 200

@app.route("/api/ml/auth/callback", methods=["GET", "POST"])
@app.route("/api/full/ml/auth/callback", methods=["GET", "POST"])
def ml_auth_callback():
    """Recibe la redirección de MeLi. Si es un nuevo cliente en prueba, crea su cuenta y activa 30 días gratis automáticamente."""
    error = request.args.get('error')
    if error:
        return redirect('/full/?ml=error&msg=' + urlencode({'m': error}))

    code = request.args.get('code') or (request.get_json() or {}).get('code')
    state = request.args.get('state') or (request.get_json() or {}).get('state')

    pkce = pop_oauth_state(state)
    if not code or not pkce:
        return redirect('/full/?ml=error&msg=sesion_expirada')

    user_id = pkce.get('user_id')
    code_verifier = pkce.get('code_verifier')
    try:
        r = requests.post(
            f"{MELI_API}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": ML_CLIENT_ID,
                "client_secret": ML_CLIENT_SECRET,
                "code": code,
                "redirect_uri": ML_REDIRECT_URI,
                "code_verifier": code_verifier
            },
            headers={"Accept": "application/json"},
            timeout=15
        )
        if r.status_code != 200:
            return redirect('/full/?ml=error&msg=error_token')

        token_data = r.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 21600)
        meli_user_id = token_data.get("user_id")
        expires_at = int(time.time() + expires_in)

        # Consultar datos de usuario en MercadoLibre
        nickname = str(meli_user_id)
        meli_email = f"meli_{meli_user_id}@mercadolibre.com"
        u_resp = requests.get(f"{MELI_API}/users/{meli_user_id}", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        if u_resp.status_code == 200:
            udata = u_resp.json()
            nickname = udata.get("nickname", str(meli_user_id))
            meli_email = udata.get("email") or meli_email

        conn = get_db()
        with conn.cursor() as cur:
            # SI ES UN CLIENTE NUEVO SIN REGISTRO PREVIO:
            if not user_id:
                # 1. Verificar si ya existía esta cuenta MeLi
                cur.execute("SELECT user_id FROM ml_credentials WHERE ml_user_id=%s LIMIT 1", (meli_user_id,))
                c_row = cur.fetchone()
                if c_row:
                    user_id = c_row["user_id"]
                else:
                    # 2. Verificar si el email existe
                    cur.execute("SELECT id FROM users WHERE email=%s LIMIT 1", (meli_email,))
                    u_row = cur.fetchone()
                    if u_row:
                        user_id = u_row["id"]
                    else:
                        # 3. Crear nuevo cliente de prueba
                        rnd_pwd = secrets.token_urlsafe(16)
                        cur.execute("""
                            INSERT INTO users (email, password_hash, full_name, business_name, platform)
                            VALUES (%s, %s, %s, %s, 'ml')
                        """, (meli_email, hash_pw(rnd_pwd), nickname, nickname))
                        user_id = cur.lastrowid

                # HABILITAR ACCESO A FULL
                cur.execute("UPDATE users SET has_full = 1 WHERE id = %s", (user_id,))
                cur.execute("INSERT IGNORE INTO user_settings (user_id) VALUES (%s)", (user_id,))

            # Equipo prendido: las cuentas quedan en la cuenta del negocio (la del titular), aunque las
            # conecte un administrador; sin equipo, a nombre de quien las conecta, como siempre.
            titular_id = user_id
            if _equipo.equipo_activo(cur, user_id):
                titular_id = get_account_user_id(user_id, conn)

            # Guardar o actualizar credenciales MeLi
            cur.execute("SELECT id FROM ml_credentials WHERE user_id=%s AND ml_user_id=%s", (titular_id, meli_user_id))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE ml_credentials
                    SET ml_access_token=%s, ml_refresh_token=%s, ml_token_expires_at=%s, ml_nickname=%s, updated_at=NOW()
                    WHERE id=%s
                """, (access_token, refresh_token, expires_at, nickname, row["id"]))
                cred_id = row["id"]
            else:
                cur.execute("""
                    INSERT INTO ml_credentials (user_id, ml_user_id, ml_access_token, ml_refresh_token, ml_token_expires_at, ml_nickname)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (titular_id, meli_user_id, access_token, refresh_token, expires_at, nickname))
                cred_id = cur.lastrowid
        conn.close()

        # Lanzar sincronización en background
        try:
            from worker import sync_account_full_catalog
            threading.Thread(target=sync_account_full_catalog, args=(titular_id, cred_id, access_token, meli_user_id), daemon=True).start()
        except Exception as e:
            print(f"Aviso sync thread: {e}")

        # Generar token JWT automático para el navegador
        auth_token = create_access_token(identity=str(user_id))
        return redirect(f"/full/?auth_token={auth_token}&ml=ok&nickname={nickname}")

    except Exception as e:
        print(f"Error callback ML: {e}")
        return redirect("/full/?ml=error&msg=servidor")

@app.route("/api/full/ml/accounts", methods=["GET"])
@jwt_required()
def get_ml_accounts():
    """Lista las cuentas de MercadoLibre vinculadas del usuario."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, ml_user_id, ml_nickname, created_at,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_active
            FROM ml_credentials
            WHERE user_id=%s
            ORDER BY id ASC
        """, (account_id,))
        accs = cur.fetchall()
        visibles = _equipo.cuentas_visibles(cur, user_id)
        if visibles is not None:
            accs = [a for a in accs if a["ml_user_id"] in visibles]
    plan_info = get_user_plan_info(account_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "accounts": accs,
        "max_allowed": plan_info["limits"]["max_ml_accounts"],
        "can_add_more": len(accs) < plan_info["limits"]["max_ml_accounts"]
    }), 200

@app.route("/api/full/ml/accounts/<int:acc_id>", methods=["DELETE"])
@jwt_required()
@_equipo.requiere_rol('admin')
def delete_ml_account(acc_id):
    """Desvincula una cuenta de MercadoLibre y limpia su inventario asociado."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    try:
        with conn.cursor() as cur:
            # 1. Eliminar pronósticos e items vinculados a esa credencial
            cur.execute("""
                DELETE FROM forecasts 
                WHERE item_id IN (SELECT id FROM full_items WHERE ml_credential_id=%s AND user_id=%s)
            """, (acc_id, account_id))
            cur.execute("DELETE FROM full_items WHERE ml_credential_id=%s AND user_id=%s", (acc_id, account_id))
            # 2. Eliminar credencial de MeLi
            cur.execute("DELETE FROM ml_credentials WHERE id=%s AND user_id=%s", (acc_id, account_id))
        return jsonify({"ok": True, "message": "Cuenta desvinculada exitosamente."}), 200
    except Exception as e:
        print(f"Error desvinculando cuenta MeLi: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

# -------------------------------------------------------------
# RUTAS DE CONTROL DE STOCK FULL Y PREDICCIÓN (CON MULTICUENTA)
# -------------------------------------------------------------

@app.route("/api/full/items", methods=["GET"])
@jwt_required()
def get_full_items():
    user_id = int(get_jwt_identity())
    status_filter = request.args.get("status")
    search = request.args.get("q", "").strip()
    account_filter = request.args.get("account_id")
    warehouse = request.args.get("warehouse", "meli_full")

    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    full_sub = get_user_full_subscription(account_id, conn)
    if not full_sub["has_full_access"]:
        conn.close()
        return jsonify({
            "ok": False,
            "subscription_required": True,
            "can_start_trial": full_sub["can_start_trial"],
            "error": "El acceso a EnvioBot Full requiere activar los 30 días de prueba gratuita o contar con una suscripción activa.",
            "plan_info": full_sub
        }), 403

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (account_id,))
        settings = cur.fetchone() or {"default_lead_time_days": 7, "default_safety_stock_days": 3, "target_coverage_days": 30}

        cur.execute("SELECT transit_days, target_stock_days FROM warehouses WHERE user_id=%s AND is_active=1 ORDER BY id ASC LIMIT 1", (account_id,))
        wh_row = cur.fetchone()
        default_transit = wh_row["transit_days"] if wh_row and wh_row.get("transit_days") is not None else 5
        target_cov = wh_row["target_stock_days"] if wh_row and wh_row.get("target_stock_days") is not None else settings.get("target_coverage_days", 30)

        query = """
            SELECT 
                i.id, i.item_id, i.variation_id, i.variation_name, i.inventory_id,
                i.sku, i.title, i.thumbnail, i.permalink, i.listing_type_id, i.is_catalog,
                i.status AS item_status, i.current_stock_full, i.not_available_stock_full,
                i.ml_credential_id, i.units_per_box,
                c.ml_nickname AS account_nickname,
                COALESCE(i.lead_time_override, %s) AS effective_lead_time,
                COALESCE(i.safety_stock_override, %s) AS effective_buffer,
                f.sales_last_7d, f.sales_last_15d, f.sales_last_30d,
                f.vpd_weighted, f.days_left, f.stockout_date, f.reorder_deadline_date,
                f.suggested_restock_units, f.status, f.updated_at
            FROM full_items i
            LEFT JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id 
                 AND COALESCE(f.variation_id, '') = COALESCE(i.variation_id, '')
            LEFT JOIN ml_credentials c ON c.id = i.ml_credential_id
            WHERE i.user_id = %s AND i.is_monitored = 1
        """
        default_lt = settings.get("default_lead_time_days", 5)
        default_ss = settings.get("default_safety_stock_days", 2)
        params = [default_lt, default_ss, account_id]

        if account_filter and account_filter != "all":
            query += " AND i.ml_credential_id = %s"
            params.append(int(account_filter))

        # Equipo: quien no es administrador ve solo las cuentas que le habilitaron.
        visibles = _equipo.cuentas_visibles(cur, user_id)
        if visibles is not None:
            if visibles:
                query += " AND c.ml_user_id IN (" + ",".join(["%s"] * len(visibles)) + ")"
                params.extend(visibles)
            else:
                query += " AND 1 = 0"

        cur.execute(query, tuple(params))
        raw_items = cur.fetchall()

        # ── Algoritmo de Consolidación por Producto Físico en Full ─────────────
        # Unifica publicaciones hermanas (Clásica, Premium, Catálogo) que comparten el mismo
        # stock físico en Full (mismo inventory_id o SKU) para evitar filas duplicadas.
        consolidated = {}
        for row in raw_items:
            inv = (row.get("inventory_id") or "").strip()
            sku = (row.get("sku") or "").strip().upper()
            var_id = str(row.get("variation_id") or "").strip()

            if inv:
                group_key = f"inv_{inv}"
            elif sku:
                group_key = f"sku_{sku}_{var_id}"
            else:
                group_key = f"item_{row['item_id']}_{var_id}"

            listing_type = row.get("listing_type_id") or "gold_special"
            is_cat = bool(row.get("is_catalog"))
            if is_cat:
                type_label = "Catálogo"
            elif listing_type == "gold_pro":
                type_label = "Premium"
            else:
                type_label = "Clásica"

            channel_info = {
                "item_id": row["item_id"],
                "listing_type": listing_type,
                "type_label": type_label,
                "is_catalog": is_cat,
                "status": row.get("item_status") or "active",
                "permalink": row.get("permalink") or "#"
            }

            if group_key not in consolidated:
                consolidated[group_key] = {
                    "id": row["id"],
                    "item_id": row["item_id"],
                    "variation_id": row.get("variation_id"),
                    "variation_name": row.get("variation_name"),
                    "inventory_id": row.get("inventory_id"),
                    "sku": row.get("sku") or "",
                    "title": row.get("title") or "",
                    "thumbnail": row.get("thumbnail"),
                    "permalink": row.get("permalink"),
                    "ml_credential_id": row.get("ml_credential_id"),
                    "account_nickname": row.get("account_nickname"),
                    "units_per_box": row.get("units_per_box") or 0,
                    "effective_lead_time": row.get("effective_lead_time") if row.get("effective_lead_time") is not None else default_lt,
                    "effective_buffer": row.get("effective_buffer") if row.get("effective_buffer") is not None else default_ss,
                    "effective_transit": default_transit,
                    "current_stock_full": row.get("current_stock_full", 0),
                    "not_available_stock_full": row.get("not_available_stock_full", 0),
                    "sales_last_7d": row.get("sales_last_7d") or 0,
                    "sales_last_15d": row.get("sales_last_15d") or 0,
                    "sales_last_30d": row.get("sales_last_30d") or 0,
                    "channels": [channel_info],
                    "target_coverage_days": target_cov
                }
            else:
                c_item = consolidated[group_key]
                if not c_item.get("sku") and row.get("sku"):
                    c_item["sku"] = row["sku"]
                if not c_item.get("inventory_id") and row.get("inventory_id"):
                    c_item["inventory_id"] = row["inventory_id"]
                c_item["current_stock_full"] = max(c_item["current_stock_full"], row.get("current_stock_full", 0))
                c_item["not_available_stock_full"] = max(c_item["not_available_stock_full"], row.get("not_available_stock_full", 0))
                if not any(ch["item_id"] == channel_info["item_id"] for ch in c_item["channels"]):
                    c_item["channels"].append(channel_info)
                    c_item["sales_last_7d"] += (row.get("sales_last_7d") or 0)
                    c_item["sales_last_15d"] += (row.get("sales_last_15d") or 0)
                    c_item["sales_last_30d"] += (row.get("sales_last_30d") or 0)

        # ── Mercadería en Preparación vs Tránsito hacia Full (Envíos Activos EnvioBot) ────────
        cur.execute("""
            SELECT s.status, isi.item_id, isi.inventory_id, isi.sku, SUM(isi.units_to_send) AS total_units
            FROM inbound_shipment_items isi
            JOIN inbound_shipments s ON s.id = isi.shipment_id
            WHERE s.user_id = %s AND s.status IN ('scheduled', 'in_transit')
            GROUP BY s.status, isi.item_id, isi.inventory_id, isi.sku
        """, (account_id,))
        shipment_rows = cur.fetchall()

        prep_by_sku = {}
        prep_by_inv = {}
        prep_by_item = {}

        transit_by_sku = {}
        transit_by_inv = {}
        transit_by_item = {}

        for r in shipment_rows:
            qty = int(r.get("total_units") or 0)
            st = r.get("status")
            sku_k = (r.get("sku") or "").strip().upper()
            inv_k = (r.get("inventory_id") or "").strip()
            item_k = (r.get("item_id") or "").strip()

            target_sku_dict = prep_by_sku if st == "scheduled" else transit_by_sku
            target_inv_dict = prep_by_inv if st == "scheduled" else transit_by_inv
            target_item_dict = prep_by_item if st == "scheduled" else transit_by_item

            if sku_k: target_sku_dict[sku_k] = target_sku_dict.get(sku_k, 0) + qty
            if inv_k: target_inv_dict[inv_k] = target_inv_dict.get(inv_k, 0) + qty
            if item_k: target_item_dict[item_k] = target_item_dict.get(item_k, 0) + qty

        # ── Recalcular Métricas Consolidadas y Semáforos ──────────────────────────
        today = datetime.utcnow().date()
        output_items = []

        for c_item in consolidated.values():
            s7 = c_item["sales_last_7d"]
            s15 = c_item["sales_last_15d"]
            s30 = c_item["sales_last_30d"]
            stock = c_item["current_stock_full"]
            lt = c_item["effective_lead_time"]
            ss = c_item["effective_buffer"]
            transit = c_item["effective_transit"]
            total_advance = lt + ss + transit

            sku_key = (c_item.get("sku") or "").strip().upper()
            inv_key = (c_item.get("inventory_id") or "").strip()
            item_key = (c_item.get("item_id") or "").strip()

            prep_units = prep_by_inv.get(inv_key, 0) or prep_by_sku.get(sku_key, 0) or prep_by_item.get(item_key, 0)
            raw_transit_units = transit_by_inv.get(inv_key, 0) or transit_by_sku.get(sku_key, 0) or transit_by_item.get(item_key, 0)
            in_process_units = c_item.get("not_available_stock_full", 0)

            # Si el usuario despachó unidades en tránsito y MeLi ya empezó a recibir en muelle:
            remaining_transit = max(0, raw_transit_units - in_process_units) if raw_transit_units > 0 else 0

            c_item["in_process_stock"] = in_process_units
            c_item["in_preparation_stock"] = prep_units
            c_item["in_transit_stock"] = remaining_transit

            total_incoming = in_process_units + prep_units + remaining_transit
            c_item["total_incoming"] = total_incoming
            total_covered_stock = stock + total_incoming

            vpd = round((0.50 * (s7 / 7.0)) + (0.35 * (s15 / 15.0)) + (0.15 * (s30 / 30.0)), 2)
            c_item["vpd_weighted"] = vpd

            if vpd > 0:
                days_left = round(stock / vpd, 1)
                c_item["days_left"] = days_left
                covered_days_left = round(total_covered_stock / vpd, 1)
                c_item["covered_days_left"] = covered_days_left

                stockout_date = today + timedelta(days=int(days_left))
                c_item["stockout_date"] = stockout_date.isoformat()
                days_until_prep = days_left - total_advance
                reorder_deadline = today + timedelta(days=max(0, int(days_until_prep)))
                c_item["reorder_deadline_date"] = reorder_deadline.isoformat()
                c_item["suggested_restock_units"] = max(0, int(round((target_cov * vpd) - total_covered_stock)))
            else:
                c_item["days_left"] = 999.0
                c_item["covered_days_left"] = 999.0
                c_item["stockout_date"] = None
                c_item["reorder_deadline_date"] = None
                c_item["suggested_restock_units"] = 0

            # Semáforo Inteligente considerando Recepción MeLi, En Tránsito y En Preparación
            if stock <= 0:
                if in_process_units > 0:
                    c_item["status"] = "in_reception"
                elif remaining_transit > 0:
                    c_item["status"] = "in_transit"
                elif prep_units > 0:
                    c_item["status"] = "in_preparation"
                else:
                    c_item["status"] = "out_of_stock"
            elif in_process_units > 0 and (stock + in_process_units) / max(vpd, 0.01) > (lt + transit):
                c_item["status"] = "in_reception"
            elif remaining_transit > 0 and (stock + in_process_units + remaining_transit) / max(vpd, 0.01) > (lt + transit):
                c_item["status"] = "in_transit"
            elif prep_units > 0:
                c_item["status"] = "in_preparation"
            elif c_item["days_left"] <= (lt + transit):
                c_item["status"] = "critical"
            elif c_item["days_left"] <= total_advance:
                c_item["status"] = "warning"
            else:
                c_item["status"] = "ok"

            output_items.append(c_item)

        # ── Aplicar Filtros de Estado y Búsqueda sobre el Catálogo Consolidado ──
        if status_filter:
            if status_filter == "action_required":
                output_items = [x for x in output_items if x["status"] in ("warning", "critical", "out_of_stock")]
            elif status_filter == "in_process":
                output_items = [x for x in output_items if x["status"] in ("in_reception", "in_transit", "in_preparation")]
            else:
                output_items = [x for x in output_items if x["status"] == status_filter]

        if search:
            s_low = search.lower()
            filtered_by_search = []
            for itm in output_items:
                match = (s_low in itm["title"].lower() or 
                         s_low in itm["sku"].lower() or 
                         s_low in itm["item_id"].lower() or
                         any(s_low in ch["item_id"].lower() for ch in itm.get("channels", [])))
                if match:
                    filtered_by_search.append(itm)
            output_items = filtered_by_search

        # Ordenamiento prioritario por urgencia y cobertura restante
        status_priority = {'out_of_stock': 1, 'critical': 2, 'warning': 3, 'in_transit': 4, 'in_reception': 5, 'ok': 6}
        output_items.sort(key=lambda x: (status_priority.get(x["status"], 7), x["days_left"]))

        # Resumen consolidado para las tarjetas de KPI
        summary = {
            "total_monitored": len(output_items),
            "count_ok": sum(1 for x in output_items if x["status"] == "ok"),
            "count_warning": sum(1 for x in output_items if x["status"] == "warning"),
            "count_critical": sum(1 for x in output_items if x["status"] in ("critical", "out_of_stock")),
            "count_in_process": sum(1 for x in output_items if x["status"] in ("in_reception", "in_transit"))
        }

    plan_info = get_user_plan_info(user_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "items": output_items,
        "summary": summary,
        "settings": settings,
        "plan_info": plan_info
    }), 200

@app.route("/api/full/items/<int:item_id>", methods=["PUT"])
@jwt_required()
@_equipo.requiere_rol('operator')
def update_item(item_id):
    """Actualiza Tiempo de Preparación (Lead Time), Buffer o Unidades por Caja de un producto."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    lt = data.get("lead_time_override")
    ss = data.get("safety_stock_override")
    upb = data.get("units_per_box")

    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        if upb is not None:
            val_box = int(upb) if int(upb) > 0 else None
            cur.execute("""
                UPDATE full_items 
                SET units_per_box=%s
                WHERE id=%s AND user_id=%s
            """, (val_box, item_id, account_id))

        if lt is not None or ss is not None:
            cur.execute("""
                UPDATE full_items 
                SET lead_time_override=%s, safety_stock_override=%s
                WHERE id=%s AND user_id=%s
            """, (lt, ss, item_id, account_id))

        # Recalcular semáforo inmediatamente
        cur.execute("SELECT item_id, variation_id, current_stock_full FROM full_items WHERE id=%s", (item_id,))
        it = cur.fetchone()
        if it:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (account_id,))
            s = cur.fetchone() or {"default_lead_time_days": 5, "default_safety_stock_days": 2}
            effective_lt = lt if lt is not None else s.get("default_lead_time_days", 5)
            effective_ss = ss if ss is not None else s.get("default_safety_stock_days", 2)
            transit = 2 # Villa Celina
            total_advance = effective_lt + effective_ss + transit

            var_val = it.get("variation_id") or ""
            cur.execute("SELECT vpd_weighted, days_left FROM forecasts WHERE user_id=%s AND item_id=%s AND COALESCE(variation_id, '')=%s", (account_id, it["item_id"], var_val))
            fc = cur.fetchone()
            if fc and fc["vpd_weighted"] > 0:
                dl = fc["days_left"]
                stock = it["current_stock_full"]
                today = datetime.utcnow().date()
                if stock <= 0:
                    new_status = 'out_of_stock'
                elif dl <= (effective_lt + transit):
                    new_status = 'critical'
                elif dl <= total_advance:
                    new_status = 'warning'
                else:
                    new_status = 'ok'
                reorder_deadline = today + timedelta(days=max(0, int(dl - total_advance)))
                cur.execute("""
                    UPDATE forecasts 
                    SET status=%s, reorder_deadline_date=%s, updated_at=NOW()
                    WHERE user_id=%s AND item_id=%s AND COALESCE(variation_id, '')=%s
                """, (new_status, reorder_deadline, account_id, it["item_id"], var_val))

    conn.close()
    return jsonify({"ok": True, "message": "Datos de reposición guardados."}), 200

@app.route("/api/full/sync", methods=["POST"])
@app.route("/api/full/sync-now", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('operator')
def trigger_sync():
    """Dispara sincronización inmediata de todas las cuentas del usuario."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    from worker import sync_all_accounts_for_user
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM ml_credentials WHERE user_id=%s", (account_id,))
        accounts = cur.fetchall()
    conn.close()

    if not accounts:
        return jsonify({"ok": False, "error": "Todavía no tenés cuentas de MercadoLibre vinculadas."}), 400

    threading.Thread(target=sync_all_accounts_for_user, args=(account_id,), daemon=True).start()
    return jsonify({"ok": True, "message": "Sincronización iniciada en segundo plano."}), 200

# -------------------------------------------------------------
# RUTAS DE EQUIPO / DESTINATARIOS (MULTIUSUARIO SEGÚN PLAN)
# -------------------------------------------------------------

@app.route("/api/full/recipients", methods=["GET"])
@jwt_required()
def get_recipients():
    user_id = int(get_jwt_identity())
    conn = get_db()
    plan_info = get_user_plan_info(user_id, conn)
    max_allowed = plan_info["limits"]["max_recipients"]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, phone, role, warehouse_filter, is_active, 
                   COALESCE(is_verified, 1) AS is_verified, created_at
            FROM alert_recipients
            WHERE user_id=%s AND is_active=1
            ORDER BY id ASC
        """, (user_id,))
        recipients = cur.fetchall()
    conn.close()

    return jsonify({
        "ok": True,
        "plan_tier": plan_info["plan_tier"],
        "plan_name": plan_info["plan_name"],
        "max_allowed": max_allowed,
        "current_count": len(recipients),
        "can_add_more": len(recipients) < max_allowed,
        "recipients": recipients
    }), 200

@app.route("/api/full/recipients", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
def add_recipient():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    role = data.get("role", "admin").strip()
    warehouse_filter = data.get("warehouse_filter", "all").strip()

    if not name or not phone:
        return jsonify({"ok": False, "error": "Completá nombre y teléfono."}), 400

    conn = get_db()
    plan_info = get_user_plan_info(user_id, conn)
    max_allowed = plan_info["limits"]["max_recipients"]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM alert_recipients WHERE user_id=%s AND is_active=1", (user_id,))
        current_count = cur.fetchone()["cnt"]

        if current_count >= max_allowed:
            conn.close()
            return jsonify({
                "ok": False,
                "error": f"Tu {plan_info['plan_name']} permite hasta {max_allowed} destinatario(s). Mejorá a un plan superior para sumar a todo tu equipo.",
                "limit_reached": True
            }), 403

        # Generar código de verificación de 6 dígitos
        code = str(secrets.randbelow(900000) + 100000)

        cur.execute("""
            INSERT INTO alert_recipients (user_id, name, phone, role, warehouse_filter, is_verified)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (user_id, name, phone, role, warehouse_filter))
        new_id = cur.lastrowid

        cur.execute("""
            INSERT INTO verification_codes (user_id, channel, destination, code, is_verified, verified_at)
            VALUES (%s, 'whatsapp', %s, %s, 1, NOW())
        """, (user_id, phone, code))
    conn.close()

    # Enviar mensaje automático de bienvenida y verificación de WhatsApp
    app_url = os.getenv("APP_URL", "https://enviobot.com.ar/full")
    wa_res = enviar_verificacion_whatsapp(phone, name, code, app_url)

    return jsonify({
        "ok": True,
        "message": f"Destinatario agregado. Se envió un mensaje de bienvenida y verificación a {phone}.",
        "id": new_id,
        "wa_result": wa_res
    }), 201

# -------------------------------------------------------------
# RUTAS DE VERIFICACIÓN DE EMAIL Y WHATSAPP
# -------------------------------------------------------------

@app.route("/api/full/verify/send-email", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
def send_email_verification():
    """Envía el email de bienvenida con código de 6 dígitos."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    email = data.get("email", "").strip()

    conn = get_db()
    with conn.cursor() as cur:
        if not email:
            cur.execute("SELECT alert_email FROM user_settings WHERE user_id=%s", (user_id,))
            s = cur.fetchone()
            email = s.get("alert_email") if s else ""
        if not email:
            cur.execute("SELECT email, full_name FROM users WHERE id=%s", (user_id,))
            u = cur.fetchone()
            email = u.get("email") if u else ""
            user_name = u.get("full_name") if u else "Usuario"
        else:
            cur.execute("SELECT full_name FROM users WHERE id=%s", (user_id,))
            u = cur.fetchone()
            user_name = u.get("full_name") if u else "Usuario"

        if not email:
            conn.close()
            return jsonify({"ok": False, "error": "No hay una casilla de correo para verificar."}), 400

        code = str(secrets.randbelow(900000) + 100000)
        cur.execute("""
            INSERT INTO verification_codes (user_id, channel, destination, code, is_verified)
            VALUES (%s, 'email', %s, %s, 0)
        """, (user_id, email, code))
    conn.close()

    app_url = os.getenv("APP_URL", "https://enviobot.com.ar/full")
    res = enviar_email_bienvenida_verificacion(email, user_name, code, app_url)
    return jsonify({
        "ok": True,
        "message": f"Email de bienvenida con código enviado a {email}.",
        "email": email,
        "detail": res
    }), 200

@app.route("/api/full/verify/check-email", methods=["POST"])
@jwt_required(optional=True)
def check_email_verification():
    """Valida el código de 6 dígitos para vincular y confirmar el email."""
    data = request.get_json() or {}
    code = str(data.get("code", "")).strip()
    email = data.get("email", "").strip().lower()

    user_id = None
    try:
        user_id = get_jwt_identity()
        if user_id:
            user_id = int(user_id)
    except Exception:
        pass

    if not code:
        return jsonify({"ok": False, "error": "Ingresá el código de 6 dígitos."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        query = "SELECT id, user_id, destination FROM verification_codes WHERE channel='email' AND code=%s AND is_verified=0"
        params = [code]
        if user_id:
            query += " AND user_id=%s"
            params.append(user_id)
        if email:
            query += " AND LOWER(destination)=%s"
            params.append(email)

        query += " ORDER BY id DESC LIMIT 1"
        cur.execute(query, tuple(params))
        row = cur.fetchone()

        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "Código incorrecto o vencido. Verificá tu correo o solicitá uno nuevo."}), 400

        target_uid = row["user_id"]
        cur.execute("UPDATE verification_codes SET is_verified=1, verified_at=NOW() WHERE id=%s", (row["id"],))
        cur.execute("UPDATE user_settings SET email_verified=1 WHERE user_id=%s", (target_uid,))
    conn.close()

    return jsonify({
        "ok": True,
        "verified": True,
        "message": "¡Casilla de correo vinculada y confirmada con éxito!"
    }), 200

@app.route("/api/full/verify/send-whatsapp", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
def send_whatsapp_verification():
    """Envía un mensaje de verificación por WhatsApp a un número específico."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    name = data.get("name", "").strip() or "Usuario"

    if not phone:
        return jsonify({"ok": False, "error": "Completá el número de celular."}), 400

    conn = get_db()
    with conn.cursor() as cur:
        code = str(secrets.randbelow(900000) + 100000)
        cur.execute("""
            INSERT INTO verification_codes (user_id, channel, destination, code, is_verified)
            VALUES (%s, 'whatsapp', %s, %s, 1)
        """, (user_id, phone, code))
    conn.close()

    app_url = os.getenv("APP_URL", "https://enviobot.com.ar/full")
    res = enviar_verificacion_whatsapp(phone, name, code, app_url)

    return jsonify({
        "ok": True,
        "message": f"Mensaje de verificación de WhatsApp enviado a {phone}.",
        "phone": phone,
        "detail": res
    }), 200

@app.route("/api/full/recipients/<int:recipient_id>", methods=["DELETE"])
@jwt_required()
@_equipo.requiere_rol('admin')
def delete_recipient(recipient_id):
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM alert_recipients WHERE id=%s AND user_id=%s", (recipient_id, user_id))
    conn.close()
    return jsonify({"ok": True, "message": "Destinatario eliminado."}), 200

@app.route("/api/full/recipients/test-whatsapp", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
def test_whatsapp():
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    name = data.get("name", "Usuario").strip()

    if not phone:
        return jsonify({"ok": False, "error": "Debe especificar un número de teléfono."}), 400

    sample_msg = (
        f"*Alarma de Prueba EnvioBot Full*\n"
        f"Hola {name}, esta es una notificación de prueba de tu sistema de reposición MeLi Full.\n"
        f"Tu número está correctamente configurado para recibir alertas matutinas de quiebre."
    )
    # Envío real a través del servicio de WhatsApp
    res = enviar_mensaje_whatsapp(phone, sample_msg)

    return jsonify({
        "ok": res.get("ok", False),
        "message": f"WhatsApp de prueba enviado a {phone}",
        "preview": sample_msg,
        "detail": res
    }), 200

@app.route("/api/full/alerts/trigger-now", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('operator')
def trigger_alerts_now():
    """Permite forzar la evaluación y disparo inmediato de alertas desde el panel."""
    user_id = int(get_jwt_identity())
    try:
        resultado = procesar_alertas_usuario(user_id)
        return jsonify({
            "ok": True,
            "message": "Evaluación de alertas ejecutada con éxito.",
            "data": resultado
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error procesando alertas: {str(e)}"}), 500

@app.route("/api/full/whatsapp/status", methods=["GET"])
@jwt_required()
def get_whatsapp_status():
    """Consulta el estado del proveedor de WhatsApp configurado."""
    provider = "evolution" if EVOLUTION_API_URL else ("gateway_http" if WHATSAPP_GATEWAY_URL else "simulacion")
    return jsonify({
        "ok": True,
        "provider": provider,
        "simulation_mode": WHATSAPP_SIMULATION_MODE,
        "evolution_url_configured": bool(EVOLUTION_API_URL),
        "gateway_url_configured": bool(WHATSAPP_GATEWAY_URL)
    }), 200

# -------------------------------------------------------------
# RUTAS DE DEPÓSITOS Y PARÁMETROS GLOBALES
# -------------------------------------------------------------

@app.route("/api/full/warehouses", methods=["GET"])
@jwt_required()
def get_warehouses():
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, code, name, city, province, type, transit_days, target_stock_days
            FROM warehouses
            WHERE user_id=%s AND is_active=1
            ORDER BY id ASC
        """, (account_id,))
        whs = cur.fetchall()

        # Si el usuario no tiene depósitos registrados aún, crearle automáticamente Villa Celina
        if not whs:
            cur.execute("SELECT target_coverage_days FROM user_settings WHERE user_id=%s", (account_id,))
            s = cur.fetchone()
            target_days = s["target_coverage_days"] if s and s.get("target_coverage_days") else 30
            cur.execute("""
                INSERT INTO warehouses (user_id, code, name, city, transit_days, target_stock_days, type, is_active)
                VALUES (%s, 'meli_full', 'Mercado Envíos Full (Villa Celina)', 'Villa Celina', 5, %s, 'meli_full', 1)
                ON DUPLICATE KEY UPDATE 
                    name=VALUES(name), city=VALUES(city), is_active=1
            """, (account_id, target_days))
            wh_id = cur.lastrowid
            whs = [{
                "id": wh_id,
                "code": "meli_full",
                "name": "Mercado Envíos Full (Villa Celina)",
                "city": "Villa Celina",
                "province": None,
                "type": "meli_full",
                "transit_days": 5,
                "target_stock_days": target_days
            }]
    conn.close()
    return jsonify({"ok": True, "warehouses": whs}), 200

@app.route("/api/full/warehouses", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
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
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouses (user_id, code, name, city, transit_days, target_stock_days)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                name=VALUES(name), city=VALUES(city), transit_days=VALUES(transit_days), target_stock_days=VALUES(target_stock_days)
        """, (account_id, code, name, city, transit_days, target_stock_days))
        new_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": new_id, "code": code, "message": "Depósito guardado."}), 201

@app.route("/api/full/settings", methods=["GET", "PUT"])
@jwt_required()
def user_settings_route():
    user_id = int(get_jwt_identity())
    if request.method == "PUT":
        _no = _equipo.chequear_rol("admin")
        if _no:
            return _no
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    if request.method == "GET":
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (account_id,))
            s = cur.fetchone() or {
                "default_lead_time_days": 7,
                "default_safety_stock_days": 3,
                "target_coverage_days": 30,
                "sync_frequency_hours": 4,
                "notify_email": True,
                "alert_email": "",
                "notify_whatsapp": False,
                "whatsapp_phone": "",
                "email_verified": False
            }
            if s:
                if "email_verified" not in s:
                    s["email_verified"] = False
                if "sync_frequency_hours" not in s or s["sync_frequency_hours"] is None:
                    s["sync_frequency_hours"] = 4

            # Incluir depósitos del usuario para carga unificada
            cur.execute("""
                SELECT id, code, name, city, province, type, transit_days, target_stock_days
                FROM warehouses
                WHERE user_id=%s AND is_active=1
                ORDER BY id ASC
            """, (account_id,))
            whs = cur.fetchall()
            s["warehouses"] = whs
        conn.close()
        return jsonify({"ok": True, "settings": s}), 200

    data = request.get_json() or {}
    new_email = data.get("alert_email", "").strip()
    new_phone = data.get("whatsapp_phone", "").strip()
    send_welcome = data.get("send_welcome", True)

    email_sent = False
    phone_sent = False
    email_code = None
    phone_code = None
    user_name = "Usuario"

    with conn.cursor() as cur:
        # Consultar estado anterior
        cur.execute("SELECT alert_email, email_verified FROM user_settings WHERE user_id=%s", (account_id,))
        prev_s = cur.fetchone()
        prev_email = prev_s.get("alert_email") if prev_s else None
        email_is_verified = prev_s.get("email_verified", False) if prev_s else False

        # Si el correo cambió, debe verificarse de nuevo
        if prev_email and new_email and prev_email.lower() != new_email.lower():
            email_is_verified = False

        target_cov = data.get("target_coverage_days", 30)
        sync_freq = int(data.get("sync_frequency_hours", 4))
        if sync_freq not in (1, 2, 4, 6, 12, 24):
            sync_freq = 4

        brand_enabled = bool(data.get("brand_enabled", False))
        brand_name = data.get("brand_name", "").strip() if data.get("brand_name") else ""
        brand_logo_url = data.get("brand_logo_url", "")
        brand_primary_color = data.get("brand_primary_color", "").strip() if data.get("brand_primary_color") else ""
        brand_show_powered_by = bool(data.get("brand_show_powered_by", True))

        cur.execute("""
            INSERT INTO user_settings 
            (user_id, default_lead_time_days, default_safety_stock_days, target_coverage_days, sync_frequency_hours, notify_email, alert_email, notify_whatsapp, whatsapp_phone, email_verified, brand_enabled, brand_name, brand_logo_url, brand_primary_color, brand_show_powered_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                default_lead_time_days = VALUES(default_lead_time_days),
                default_safety_stock_days = VALUES(default_safety_stock_days),
                target_coverage_days = VALUES(target_coverage_days),
                sync_frequency_hours = VALUES(sync_frequency_hours),
                notify_email = VALUES(notify_email),
                alert_email = VALUES(alert_email),
                notify_whatsapp = VALUES(notify_whatsapp),
                whatsapp_phone = VALUES(whatsapp_phone),
                email_verified = VALUES(email_verified),
                brand_enabled = VALUES(brand_enabled),
                brand_name = VALUES(brand_name),
                brand_logo_url = VALUES(brand_logo_url),
                brand_primary_color = VALUES(brand_primary_color),
                brand_show_powered_by = VALUES(brand_show_powered_by)
        """, (
            account_id,
            data.get("default_lead_time_days", 7),
            data.get("default_safety_stock_days", 3),
            target_cov,
            sync_freq,
            data.get("notify_email", True),
            new_email,
            data.get("notify_whatsapp", False),
            new_phone,
            email_is_verified,
            brand_enabled,
            brand_name,
            brand_logo_url,
            brand_primary_color,
            brand_show_powered_by
        ))

        # Actualizar depósitos individuales en la base de datos
        warehouses_payload = data.get("warehouses")
        if isinstance(warehouses_payload, list) and len(warehouses_payload) > 0:
            for wh in warehouses_payload:
                wh_code = wh.get("code") or wh.get("id") or "meli_full"
                wh_transit = int(wh.get("transit_days", 5))
                wh_target = int(wh.get("target_stock_days", target_cov))
                wh_name = wh.get("name") or "Mercado Envíos Full (Villa Celina)"
                wh_city = wh.get("city") or "Villa Celina"
                cur.execute("""
                    INSERT INTO warehouses (user_id, code, name, city, transit_days, target_stock_days, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        city = VALUES(city),
                        transit_days = VALUES(transit_days),
                        target_stock_days = VALUES(target_stock_days),
                        is_active = 1
                """, (account_id, wh_code, wh_name, wh_city, wh_transit, wh_target))
        else:
            # Si no se envió array de depósitos, actualizar el depósito activo de MeLi
            cur.execute("""
                UPDATE warehouses 
                SET target_stock_days = %s
                WHERE user_id = %s AND (code = 'meli_full' OR is_active = 1)
            """, (target_cov, account_id))

        cur.execute("SELECT full_name FROM users WHERE id=%s", (account_id,))
        u_row = cur.fetchone()
        if u_row and u_row.get("full_name"):
            user_name = u_row["full_name"]

        # Si se solicita o si hay nuevo email:
        if new_email and send_welcome:
            email_code = str(secrets.randbelow(900000) + 100000)
            cur.execute("""
                INSERT INTO verification_codes (user_id, channel, destination, code, is_verified)
                VALUES (%s, 'email', %s, %s, 0)
            """, (user_id, new_email, email_code))
            email_sent = True

        # Si hay teléfono nuevo y send_welcome:
        if new_phone and send_welcome:
            phone_code = str(secrets.randbelow(900000) + 100000)
            cur.execute("""
                INSERT INTO verification_codes (user_id, channel, destination, code, is_verified, verified_at)
                VALUES (%s, 'whatsapp', %s, %s, 1, NOW())
            """, (user_id, new_phone, phone_code))
            phone_sent = True

    conn.close()

    app_url = os.getenv("APP_URL", "https://enviobot.com.ar/full")
    if email_sent and email_code:
        try:
            enviar_email_bienvenida_verificacion(new_email, user_name, email_code, app_url)
        except Exception as e:
            print(f"[Error enviando email bienvenida]: {e}")

    if phone_sent and phone_code:
        try:
            enviar_verificacion_whatsapp(new_phone, user_name, phone_code, app_url)
        except Exception as e:
            print(f"[Error enviando WhatsApp verificación]: {e}")

    return jsonify({
        "ok": True,
        "message": "Configuración guardada exitosamente.",
        "email_verification_sent": email_sent,
        "whatsapp_verification_sent": phone_sent
    }), 200

@app.route("/api/full/settings/test-email", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('admin')
def test_email():
    """Envía un correo de prueba para verificar las credenciales SMTP de DonWeb."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    email = data.get("email", "").strip()

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT full_name, email FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
    conn.close()

    dest = email or (user.get("email") if user else "")
    name = user.get("full_name", "Usuario") if user else "Usuario"

    if not dest:
        return jsonify({"ok": False, "error": "Debe especificar una casilla de correo."}), 400

    tipo = data.get("account", data.get("tipo", "welcome"))
    res = enviar_email_prueba(dest, name, tipo=tipo)
    return jsonify({
        "ok": res.get("ok", False),
        "message": f"Correo de prueba enviado a {dest}",
        "detail": res
    }), 200

# -------------------------------------------------------------
# RUTAS DE EQUIPO Y COLABORADORES (INVITAR A FRAN / MIEMBROS)
# -------------------------------------------------------------

@app.route("/api/full/team/members", methods=["GET"])
@jwt_required()
def get_team_members():
    """Lista los colaboradores de la cuenta y los satélites detectados en EnvioBot Pedidos."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        # Colaboradores activos en EnvioBot Full
        cur.execute("""
            SELECT id, email, full_name, employee_label, active, created_at,
                   COALESCE(has_pedidos, 0) AS has_pedidos,
                   COALESCE(has_full, 0) AS has_full,
                   COALESCE(must_change_password, 0) AS must_change_password
            FROM users
            WHERE owner_id = %s
            ORDER BY created_at DESC
        """, (account_id,))
        members = cur.fetchall() or []
        for m in members:
            if m.get("created_at"):
                m["created_at"] = str(m["created_at"])

        # Usuarios satélite asociados en EnvioBot Pedidos (abono_de = account_id) que aún no tengan owner_id = account_id
        cur.execute("""
            SELECT id, email, full_name, employee_label,
                   COALESCE(has_pedidos, 1) AS has_pedidos,
                   COALESCE(has_full, 0) AS has_full
            FROM users
            WHERE abono_de = %s AND (owner_id IS NULL OR owner_id != %s)
            ORDER BY full_name ASC
        """, (account_id, account_id))
        satellites_pedidos = cur.fetchall() or []

    conn.close()
    return jsonify({
        "ok": True,
        "members": members,
        "satellites_pedidos": satellites_pedidos
    }), 200

@app.route("/api/full/team/invite", methods=["POST"])
@jwt_required()
def invite_team_member():
    """
    Invita o habilita a un colaborador para operar en EnvioBot Full.
    - Si ya es usuario de EnvioBot (por ejemplo Francisco Jaeger en Pedidos):
      Conserva su contraseña habitual, no entra en conflicto y se le habilita Full.
    - Si es un usuario nuevo (no registrado):
      Se le asigna la clave inicial (123456 por defecto) y se lo obliga a definir una nueva contraseña.
    """
    current_user_id = int(get_jwt_identity())
    if _equipo_prendido(current_user_id):
        return jsonify({"ok": False, "error": "Tu equipo ahora se maneja desde la pantalla Equipo (con invitación por link)."}), 409
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    full_name = data.get("full_name", "").strip()
    password = data.get("password", "").strip() or "123456"

    if not email:
        return jsonify({"ok": False, "error": "El email del colaborador es obligatorio."}), 400

    conn = get_db()
    account_id = get_account_user_id(current_user_id, conn)
    with conn.cursor() as cur:
        # Verificar si el usuario ya existe en EnvioBot
        cur.execute("""
            SELECT id, email, full_name, password_hash, owner_id, abono_de,
                   COALESCE(has_pedidos, 0) AS has_pedidos, COALESCE(has_full, 0) AS has_full
            FROM users
            WHERE email = %s LIMIT 1
        """, (email,))
        existing = cur.fetchone()

        if existing:
            # CASO 1: Ya existe en EnvioBot (ej: satélite en Pedidos abono_de=account_id o usuario previo)
            # NO sobreescribimos su contraseña habitual
            fn = full_name or existing.get("full_name") or "Colaborador"
            cur.execute("""
                UPDATE users
                SET owner_id = %s, has_full = 1, active = 1,
                    employee_label = COALESCE(employee_label, 'Colaborador')
                WHERE id = %s
            """, (account_id, existing["id"]))
            conn.close()
            return jsonify({
                "ok": True,
                "is_existing_user": True,
                "uses_existing_password": True,
                "message": f"{fn} ya es usuario de EnvioBot. Se habilitó su acceso a EnvioBot Full manteniendo su contraseña habitual de EnvioBot Pedidos.",
                "member": {
                    "id": existing["id"],
                    "email": email,
                    "full_name": fn,
                    "employee_label": "Colaborador",
                    "uses_existing_password": True
                }
            }), 200

        # CASO 2: Usuario completamente nuevo
        # Se asigna la clave inicial (123456) y se activa must_change_password
        fn = full_name or "Colaborador"
        p_hash = hash_pw(password)
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, owner_id, employee_label, has_full, has_pedidos, active, must_change_password)
            VALUES (%s, %s, %s, %s, 'Colaborador', 1, 0, 1, 1)
        """, (email, p_hash, fn, account_id))
        new_id = cur.lastrowid
    conn.close()

    return jsonify({
        "ok": True,
        "is_existing_user": False,
        "uses_existing_password": False,
        "initial_password": password,
        "must_change_password": True,
        "message": f"Colaborador {fn} creado con clave inicial {password}. Deberá definir su contraseña personal al ingresar.",
        "member": {
            "id": new_id,
            "email": email,
            "full_name": fn,
            "employee_label": "Colaborador",
            "uses_existing_password": False
        }
    }), 201

@app.route("/api/full/team/members/<int:member_id>", methods=["DELETE"])
@jwt_required()
def delete_team_member(member_id):
    """Elimina o desactiva un colaborador del equipo."""
    current_user_id = int(get_jwt_identity())
    if _equipo_prendido(current_user_id):
        return jsonify({"ok": False, "error": "Tu equipo ahora se maneja desde la pantalla Equipo."}), 409
    conn = get_db()
    account_id = get_account_user_id(current_user_id, conn)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id = %s AND owner_id = %s", (member_id, account_id))
        m = cur.fetchone()
        if not m:
            conn.close()
            return jsonify({"ok": False, "error": "Colaborador no encontrado en tu equipo."}), 404

        cur.execute("DELETE FROM users WHERE id = %s AND owner_id = %s", (member_id, account_id))
    conn.close()
    return jsonify({"ok": True, "message": "Colaborador removido exitosamente."}), 200

# -------------------------------------------------------------
# RUTAS DE ADMINISTRACIÓN Y CONTROL DE CLIENTES
# -------------------------------------------------------------

@app.route("/api/full/admin/clients", methods=["GET"])
@jwt_required()
def admin_get_clients():
    """Lista todos los clientes con su estado de Pedidos, Full, bloqueo y observaciones."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                u.id, u.email, u.full_name, u.business_name,
                COALESCE(u.has_pedidos, 1) AS has_pedidos,
                COALESCE(u.has_full, 0) AS has_full,
                COALESCE(u.has_inbound, 0) AS has_inbound,
                COALESCE(u.is_blocked, 0) AS is_blocked,
                COALESCE(u.admin_notes, '') AS admin_notes,
                (SELECT COUNT(*) FROM ml_credentials mc WHERE mc.user_id = u.id) AS ml_accounts_count
            FROM users u
            ORDER BY u.id ASC
        """)
        clients = cur.fetchall()
    conn.close()

    for c in clients:
        c["has_pedidos"] = bool(c.get("has_pedidos", 1))
        c["has_full"] = bool(c.get("has_full", 0))
        c["has_inbound"] = bool(c.get("has_inbound", 0))
        c["is_blocked"] = bool(c.get("is_blocked", 0))

    return jsonify({"ok": True, "clients": clients}), 200

@app.route("/api/full/admin/clients/<int:target_id>/toggle-full", methods=["POST"])
@jwt_required()
def admin_toggle_full(target_id):
    """Activa o desactiva EnvioBot Full para un cliente."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    data = request.get_json() or {}
    enable = bool(data.get("enable", False))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET has_full=%s WHERE id=%s", (1 if enable else 0, target_id))
    conn.close()

    msg = "EnvioBot Full habilitado para este cliente." if enable else "EnvioBot Full deshabilitado para este cliente."
    return jsonify({"ok": True, "message": msg, "has_full": enable}), 200

@app.route("/api/full/admin/clients/<int:target_id>/toggle-pedidos", methods=["POST"])
@jwt_required()
def admin_toggle_pedidos(target_id):
    """Activa o desactiva EnvioBot Pedidos para un cliente."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    data = request.get_json() or {}
    enable = bool(data.get("enable", False))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET has_pedidos=%s WHERE id=%s", (1 if enable else 0, target_id))
    conn.close()

    msg = "EnvioBot Pedidos habilitado para este cliente." if enable else "EnvioBot Pedidos deshabilitado."
    return jsonify({"ok": True, "message": msg, "has_pedidos": enable}), 200

@app.route("/api/full/admin/clients/<int:target_id>/toggle-block", methods=["POST"])
@jwt_required()
def admin_toggle_block(target_id):
    """Bloquea o desbloquea al usuario."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    data = request.get_json() or {}
    is_blocked = bool(data.get("is_blocked", False))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET is_blocked=%s WHERE id=%s", (1 if is_blocked else 0, target_id))
    conn.close()

    status_str = "bloqueado" if is_blocked else "desbloqueado"
    return jsonify({"ok": True, "message": f"Usuario {status_str} correctamente.", "is_blocked": is_blocked}), 200

@app.route("/api/full/admin/clients/<int:target_id>/notes", methods=["POST"])
@jwt_required()
def admin_save_notes(target_id):
    """Guarda las observaciones administrativas de un cliente."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    data = request.get_json() or {}
    notes = data.get("admin_notes", "").strip()

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET admin_notes=%s WHERE id=%s", (notes, target_id))
    conn.close()

    return jsonify({"ok": True, "message": "Observaciones guardadas con éxito.", "admin_notes": notes}), 200

@app.route("/api/full/admin/clients/<int:target_id>/toggle-inbound", methods=["POST"])
@jwt_required()
def admin_toggle_inbound(target_id):
    """Activa o desactiva el Módulo de Colectas / Envíos a Full para un cliente."""
    user_id = int(get_jwt_identity())
    if not is_admin_user(user_id):
        return jsonify({"ok": False, "error": "Acceso restringido a administradores."}), 403

    data = request.get_json() or {}
    enable = bool(data.get("enable", False))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET has_inbound=%s WHERE id=%s", (1 if enable else 0, target_id))
    conn.close()

    msg = "Módulo de Colectas Full habilitado." if enable else "Módulo de Colectas Full deshabilitado."
    return jsonify({"ok": True, "message": msg, "has_inbound": enable}), 200

# -------------------------------------------------------------
# RUTAS DE COLECTAS Y ENVÍOS INBOUND A FULL (MÓDULO PAGO)
# -------------------------------------------------------------

@app.route("/api/full/inbound/status", methods=["GET"])
@jwt_required()
def get_inbound_status():
    """Devuelve si el usuario tiene habilitado el módulo de Colectas / Envíos a Full."""
    user_id = int(get_jwt_identity())
    is_admin = is_admin_user(user_id)
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    sub = get_user_full_subscription(account_id, conn)
    has_inbound = bool(sub.get("has_inbound", False)) or is_admin

    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) AS total_shipments,
                SUM(CASE WHEN status IN ('scheduled', 'in_transit') THEN 1 ELSE 0 END) AS active_shipments
            FROM inbound_shipments
            WHERE user_id = %s
        """, (account_id,))
        stats = cur.fetchone() or {"total_shipments": 0, "active_shipments": 0}
    conn.close()

    return jsonify({
        "ok": True,
        "has_inbound": has_inbound,
        "is_admin": is_admin,
        "stats": stats,
        "default_warehouse": {
            "code": "meli_full",
            "name": "Mercado Envíos Full (Villa Celina)",
            "city": "La Matanza, Buenos Aires"
        }
    }), 200

@app.route("/api/full/inbound/shipments", methods=["GET"])
@jwt_required()
def list_inbound_shipments():
    """Lista todos los envíos / colectas generadas por el usuario."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                s.id, s.shipment_code, s.destination_warehouse, s.destination_name,
                s.status, s.target_coverage_days, s.lead_time_days, s.transit_days,
                s.total_items, s.total_units, s.total_boxes, s.packaging_type,
                s.carrier_notes, s.pickup_date, s.estimated_arrival_date,
                s.meli_inbound_id, s.meli_inbound_status, s.created_at, s.updated_at
            FROM inbound_shipments s
            WHERE s.user_id = %s
            ORDER BY s.id DESC
        """, (account_id,))
        shipments = cur.fetchall() or []

        for sh in shipments:
            if sh.get("pickup_date"):
                sh["pickup_date"] = str(sh["pickup_date"])
            if sh.get("estimated_arrival_date"):
                sh["estimated_arrival_date"] = str(sh["estimated_arrival_date"])
            if sh.get("created_at"):
                sh["created_at"] = sh["created_at"].strftime("%Y-%m-%d %H:%M:%S") if hasattr(sh["created_at"], "strftime") else str(sh["created_at"])

            cur.execute("""
                SELECT item_id, sku, title, units_to_send, box_count
                FROM inbound_shipment_items
                WHERE shipment_id = %s
                LIMIT 5
            """, (sh["id"],))
            sh["items_preview"] = cur.fetchall() or []
    conn.close()

    return jsonify({"ok": True, "shipments": shipments}), 200

@app.route("/api/full/inbound/shipments", methods=["POST"])
@jwt_required()
@_equipo.requiere_rol('operator')
def create_inbound_shipment():
    """Crea una nueva orden de colecta / envío inbound a Full."""
    user_id = int(get_jwt_identity())
    is_admin = is_admin_user(user_id)
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    sub = get_user_full_subscription(account_id, conn)
    has_inbound = bool(sub.get("has_inbound", False)) or is_admin

    if not has_inbound:
        conn.close()
        return jsonify({
            "ok": False,
            "requires_upgrade": True,
            "error": "El Módulo de Colectas y Envíos a Full es una función exclusiva para planes Pro Plus o Add-on activo.",
            "upgrade_msg": "Automatizá tus envíos a Villa Celina, generá hojas de despacho con código de barras y eliminá quiebres de stock."
        }), 403

    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        conn.close()
        return jsonify({"ok": False, "error": "Debe seleccionar al menos un producto para despachar."}), 400

    target_coverage_days = int(data.get("target_coverage_days", 30))
    lead_time_days = int(data.get("lead_time_days", 2))
    transit_days = int(data.get("transit_days", 3))
    packaging_type = data.get("packaging_type", "cajas_master")
    carrier_notes = data.get("carrier_notes", "").strip()
    pickup_date_str = data.get("pickup_date")

    total_units = 0
    total_boxes = 0
    clean_items = []

    for it in items:
        units = int(it.get("units_to_send", 0))
        if units <= 0:
            continue
        units_per_box = int(it.get("units_per_box", 0))
        if units_per_box > 0:
            box_count = (units + units_per_box - 1) // units_per_box
        else:
            box_count = int(it.get("box_count", 1))

        total_units += units
        total_boxes += box_count
        clean_items.append({
            "item_id": str(it.get("item_id", "")).strip(),
            "inventory_id": it.get("inventory_id"),
            "variation_id": str(it.get("variation_id", "")).strip() or None,
            "variation_name": it.get("variation_name"),
            "sku": it.get("sku"),
            "title": it.get("title", "Producto sin título"),
            "current_full_stock": int(it.get("current_full_stock", 0)),
            "vpd": float(it.get("vpd", 0.0)),
            "suggested_units": int(it.get("suggested_units", 0)),
            "units_to_send": units,
            "units_per_box": units_per_box,
            "box_count": box_count
        })

    if not clean_items:
        conn.close()
        return jsonify({"ok": False, "error": "No hay unidades válidas (> 0) para enviar."}), 400

    total_items = len(clean_items)
    today_str = datetime.now().strftime("%Y%m%d")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS cnt 
            FROM inbound_shipments 
            WHERE shipment_code LIKE %s
        """, (f"COL-FULL-{today_str}-%",))
        row = cur.fetchone()
        seq = (row.get("cnt", 0) if row else 0) + 1
        shipment_code = f"COL-FULL-{today_str}-{seq:03d}"

        today_date = datetime.now().date()
        if not pickup_date_str:
            pickup_date = today_date + timedelta(days=lead_time_days)
        else:
            try:
                pickup_date = datetime.strptime(pickup_date_str, "%Y-%m-%d").date()
            except Exception:
                pickup_date = today_date + timedelta(days=lead_time_days)

        estimated_arrival = pickup_date + timedelta(days=transit_days)

        cur.execute("""
            INSERT INTO inbound_shipments (
                user_id, shipment_code, destination_warehouse, destination_name,
                status, target_coverage_days, lead_time_days, transit_days,
                total_items, total_units, total_boxes, packaging_type,
                carrier_notes, pickup_date, estimated_arrival_date
            ) VALUES (
                %s, %s, 'meli_full', 'Mercado Envíos Full (Villa Celina)',
                'scheduled', %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
        """, (
            account_id, shipment_code, target_coverage_days, lead_time_days, transit_days,
            total_items, total_units, total_boxes, packaging_type,
            carrier_notes, pickup_date, estimated_arrival
        ))
        shipment_id = cur.lastrowid

        for cit in clean_items:
            cur.execute("""
                INSERT INTO inbound_shipment_items (
                    shipment_id, item_id, inventory_id, variation_id, variation_name,
                    sku, title, current_full_stock, vpd, suggested_units,
                    units_to_send, units_per_box, box_count
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
            """, (
                shipment_id, cit["item_id"], cit["inventory_id"], cit["variation_id"], cit["variation_name"],
                cit["sku"], cit["title"], cit["current_full_stock"], cit["vpd"], cit["suggested_units"],
                cit["units_to_send"], cit["units_per_box"], cit["box_count"]
            ))

            # Recordar units_per_box en full_items si está presente y mayor a cero
            if cit["units_per_box"] > 0:
                cur.execute("""
                    UPDATE full_items
                    SET units_per_box = %s
                    WHERE item_id = %s AND user_id = %s
                """, (cit["units_per_box"], cit["item_id"], account_id))

    conn.close()

    return jsonify({
        "ok": True,
        "message": f"Colecta {shipment_code} creada con éxito.",
        "shipment": {
            "id": shipment_id,
            "shipment_code": shipment_code,
            "status": "scheduled",
            "total_items": total_items,
            "total_units": total_units,
            "total_boxes": total_boxes,
            "pickup_date": str(pickup_date),
            "estimated_arrival_date": str(estimated_arrival)
        }
    }), 201

@app.route("/api/full/inbound/shipments/<int:shipment_id>", methods=["GET"])
@jwt_required()
def get_inbound_shipment_detail(shipment_id):
    """Obtiene el detalle completo de un envío inbound con sus ítems."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM inbound_shipments WHERE id = %s AND user_id = %s", (shipment_id, account_id))
        shipment = cur.fetchone()
        if not shipment:
            conn.close()
            return jsonify({"ok": False, "error": "Envío no encontrado."}), 404

        cur.execute("SELECT * FROM inbound_shipment_items WHERE shipment_id = %s ORDER BY id ASC", (shipment_id,))
        items = cur.fetchall() or []
    conn.close()

    if shipment.get("pickup_date"): shipment["pickup_date"] = str(shipment["pickup_date"])
    if shipment.get("estimated_arrival_date"): shipment["estimated_arrival_date"] = str(shipment["estimated_arrival_date"])
    if shipment.get("created_at"): shipment["created_at"] = str(shipment["created_at"])

    return jsonify({"ok": True, "shipment": shipment, "items": items}), 200

@app.route("/api/full/inbound/shipments/<int:shipment_id>", methods=["PUT"])
@jwt_required()
@_equipo.requiere_rol('operator')
def update_inbound_shipment(shipment_id):
    """Actualiza una orden de colecta / envío inbound existente (solo si no fue despachado)."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM inbound_shipments WHERE id = %s AND user_id = %s", (shipment_id, account_id))
        shipment = cur.fetchone()

    if not shipment:
        conn.close()
        return jsonify({"ok": False, "error": "Envío no encontrado."}), 404

    if shipment["status"] in ("in_transit", "delivered", "cancelled"):
        conn.close()
        return jsonify({
            "ok": False,
            "error": f"No se puede modificar un envío en estado '{shipment['status']}'. Solo se pueden editar envíos programados o en preparación."
        }), 400

    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        conn.close()
        return jsonify({"ok": False, "error": "El envío debe contener al menos un producto."}), 400

    pickup_date_str = data.get("pickup_date")
    carrier_notes = data.get("carrier_notes", "").strip() if "carrier_notes" in data else (shipment.get("carrier_notes") or "")
    packaging_type = data.get("packaging_type") or shipment.get("packaging_type") or "cajas_master"

    lead_time_days = shipment.get("lead_time_days", 2)
    transit_days = shipment.get("transit_days", 3)
    pickup_date = None
    if pickup_date_str:
        try:
            pickup_date = datetime.strptime(str(pickup_date_str).split("T")[0], "%Y-%m-%d").date()
        except Exception:
            pickup_date = None
    if not pickup_date:
        pickup_date = shipment.get("pickup_date") or (datetime.now().date() + timedelta(days=lead_time_days))

    estimated_arrival = pickup_date + timedelta(days=transit_days)

    total_units = 0
    total_boxes = 0
    clean_items = []

    for it in items:
        units = int(it.get("units_to_send", 0))
        if units <= 0:
            continue
        units_per_box = int(it.get("units_per_box", 0))
        if units_per_box > 0:
            box_count = (units + units_per_box - 1) // units_per_box
        else:
            box_count = int(it.get("box_count", 1))

        total_units += units
        total_boxes += box_count
        clean_items.append({
            "item_id": str(it.get("item_id", "")).strip(),
            "inventory_id": it.get("inventory_id"),
            "variation_id": str(it.get("variation_id", "")).strip() or None,
            "variation_name": it.get("variation_name"),
            "sku": it.get("sku"),
            "title": it.get("title", "Producto sin título"),
            "current_full_stock": int(it.get("current_full_stock", 0)),
            "vpd": float(it.get("vpd", 0.0)),
            "suggested_units": int(it.get("suggested_units", 0)),
            "units_to_send": units,
            "units_per_box": units_per_box,
            "box_count": box_count
        })

    if not clean_items:
        conn.close()
        return jsonify({"ok": False, "error": "Debe haber al menos un producto con unidades mayor a cero."}), 400

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE inbound_shipments SET
                total_items = %s,
                total_units = %s,
                total_boxes = %s,
                packaging_type = %s,
                carrier_notes = %s,
                pickup_date = %s,
                estimated_arrival_date = %s,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """, (
            len(clean_items),
            total_units,
            total_boxes,
            packaging_type,
            carrier_notes,
            pickup_date,
            estimated_arrival,
            shipment_id,
            account_id
        ))

        cur.execute("DELETE FROM inbound_shipment_items WHERE shipment_id = %s", (shipment_id,))
        for it in clean_items:
            cur.execute("""
                INSERT INTO inbound_shipment_items (
                    shipment_id, item_id, inventory_id, variation_id, variation_name,
                    sku, title, current_full_stock, vpd, suggested_units,
                    units_to_send, units_per_box, box_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                shipment_id,
                it["item_id"],
                it["inventory_id"],
                it["variation_id"],
                it["variation_name"],
                it["sku"],
                it["title"],
                it["current_full_stock"],
                it["vpd"],
                it["suggested_units"],
                it["units_to_send"],
                it["units_per_box"],
                it["box_count"]
            ))

    conn.close()

    return jsonify({
        "ok": True,
        "message": "Envío actualizado con éxito.",
        "shipment": {
            "id": shipment_id,
            "shipment_code": shipment["shipment_code"],
            "total_items": len(clean_items),
            "total_units": total_units,
            "total_boxes": total_boxes,
            "pickup_date": str(pickup_date),
            "carrier_notes": carrier_notes
        }
    }), 200

@app.route("/api/full/inbound/shipments/<int:shipment_id>/status", methods=["PUT"])
@jwt_required()
@_equipo.requiere_rol('operator')
def update_inbound_shipment_status(shipment_id):
    """Actualiza el estado operativo de un envío (scheduled, in_transit, delivered, cancelled)."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    new_status = data.get("status")
    valid_statuses = {"draft", "scheduled", "in_transit", "delivered", "cancelled"}
    if new_status not in valid_statuses:
        return jsonify({"ok": False, "error": f"Estado inválido. Opciones: {list(valid_statuses)}"}), 400

    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE inbound_shipments SET status = %s WHERE id = %s AND user_id = %s", (new_status, shipment_id, account_id))
        affected = cur.rowcount
    conn.close()

    if affected == 0:
        return jsonify({"ok": False, "error": "Envío no encontrado o sin cambios."}), 404

    return jsonify({"ok": True, "message": f"Estado actualizado a '{new_status}'."}), 200

@app.route("/api/full/inbound/shipments/<int:shipment_id>", methods=["DELETE"])
@jwt_required()
@_equipo.requiere_rol('operator')
def delete_inbound_shipment(shipment_id):
    """Elimina una colecta o envío programado."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM inbound_shipments WHERE id = %s AND user_id = %s", (shipment_id, account_id))
        affected = cur.rowcount
    conn.close()

    if affected == 0:
        return jsonify({"ok": False, "error": "Envío no encontrado."}), 404

    return jsonify({"ok": True, "message": "Envío eliminado correctamente."}), 200

@app.route("/api/full/inbound/shipments/<int:shipment_id>/remito-html", methods=["GET"])
def get_inbound_shipment_remito_html(shipment_id):
    """Genera la vista imprimible A4 de la Hoja de Despacho / Colecta con códigos de barras."""
    user_id = None
    token = request.args.get("token")
    if token:
        try:
            from flask_jwt_extended import decode_token
            decoded = decode_token(token)
            user_id = int(decoded.get("sub"))
        except Exception:
            user_id = None

    if not user_id:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        try:
            verify_jwt_in_request(optional=True)
            ident = get_jwt_identity()
            if ident:
                user_id = int(ident)
        except Exception:
            pass

    if not user_id:
        return "<h3>Acceso no autorizado. Por favor iniciá sesión en EnvioBot Full.</h3>", 401
    conn = get_db()
    account_id = get_account_user_id(user_id, conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.*, u.full_name, u.business_name, u.email, u.phone, u.cuit
            FROM inbound_shipments s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = %s AND s.user_id = %s
        """, (shipment_id, account_id))
        shipment = cur.fetchone()
        if not shipment:
            conn.close()
            return "<h3>Envío no encontrado</h3>", 404

        cur.execute("SELECT * FROM inbound_shipment_items WHERE shipment_id = %s ORDER BY id ASC", (shipment_id,))
        items = cur.fetchall() or []

        cur.execute("SELECT brand_enabled, brand_name, brand_logo_url, brand_primary_color, brand_show_powered_by FROM user_settings WHERE user_id = %s", (account_id,))
        branding = cur.fetchone() or {}
    conn.close()

    html_content = render_remito_html(shipment, items, branding)
    return html_content, 200, {"Content-Type": "text/html; charset=utf-8"}

# -------------------------------------------------------------
# RUTAS DE MONITOR LOGÍSTICO Y EVENTOS E-COMMERCE (CYBER, BLACK FRIDAY)
# -------------------------------------------------------------

@app.route("/api/full/logistic-events", methods=["GET"])
@jwt_required()
def get_logistic_events():
    """Devuelve los mega-eventos comerciales, fechas de corte de Full y cuenta regresiva de turnos."""
    conn = get_db()
    today = datetime.utcnow().date()
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM logistic_events 
            WHERE is_active = 1 
            ORDER BY event_start ASC
        """)
        raw_events = cur.fetchall() or []
        
    conn.close()
    
    processed = []
    next_event = None
    
    for ev in raw_events:
        cutoff = ev["inbound_cutoff_date"]
        freeze = ev["dock_freeze_start"]
        start = ev["event_start"]
        end = ev["event_end"]
        
        days_to_cutoff = (cutoff - today).days
        days_to_freeze = (freeze - today).days
        days_to_start = (start - today).days
        
        # Estado dinámico según calendario
        if today > end:
            dyn_status = "finished"
        elif today >= start:
            dyn_status = "event_active"
        elif today >= freeze:
            dyn_status = "inbound_locked"
        elif days_to_cutoff <= 14:
            dyn_status = "inbound_warning"
        else:
            dyn_status = "upcoming"
            
        turnos_delay = ev.get("typical_turnos_delay_days", 7)
        safe_booking_days = max(0, days_to_cutoff - turnos_delay)
        
        ev_dict = {
            "id": ev["id"],
            "name": ev["name"],
            "slug": ev["slug"],
            "event_start": str(start),
            "event_end": str(end),
            "inbound_cutoff_date": str(cutoff),
            "dock_freeze_start": str(freeze),
            "typical_turnos_delay_days": turnos_delay,
            "demand_multiplier": float(ev.get("demand_multiplier", 1.50)),
            "status": dyn_status,
            "description": ev.get("description", ""),
            "days_to_cutoff": days_to_cutoff,
            "days_to_freeze": days_to_freeze,
            "days_to_start": days_to_start,
            "safe_booking_days_left": safe_booking_days,
            "is_booking_urgent": (days_to_cutoff > 0 and safe_booking_days <= 5)
        }
        processed.append(ev_dict)
        
        if dyn_status in ("inbound_warning", "upcoming") and next_event is None:
            next_event = ev_dict
            
    # Si no hay próximo en warning, tomar el primero activo
    if next_event is None and processed:
        next_event = processed[0]
        
    return jsonify({
        "ok": True,
        "events": processed,
        "next_event": next_event,
        "today": str(today)
    }), 200

@app.route("/api/full/logistic-events/<int:event_id>/turnos-delay", methods=["PUT"])
@jwt_required()
@_equipo.requiere_rol('operator')
def update_event_turnos_delay(event_id):
    """Permite actualizar la demora de turnos actual reportada en Villa Celina."""
    data = request.get_json() or {}
    delay = int(data.get("delay_days", 7))
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE logistic_events SET typical_turnos_delay_days=%s WHERE id=%s", (delay, event_id))
    conn.close()
    return jsonify({"ok": True, "message": f"Demora de turnos actualizada a {delay} días."}), 200

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
