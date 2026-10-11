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
    enviar_mensaje_whatsapp, enviar_verificacion_whatsapp,
    WHATSAPP_SIMULATION_MODE, EVOLUTION_API_URL, WHATSAPP_GATEWAY_URL
)
from alerts_engine import procesar_alertas_usuario
from email_service import enviar_email_prueba, enviar_email_bienvenida_verificacion

load_dotenv()

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# Configuración JWT
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "enviobot_full_jwt_secret_unified_2026")
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
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q")
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
                   COALESCE(is_blocked, 0) AS is_blocked,
                   COALESCE(admin_notes, '') AS admin_notes
            FROM users WHERE id=%s
        """, (user_id,))
        u = cur.fetchone()

    if not u:
        return {
            "has_full_access": False,
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

    is_blocked = bool(u.get("is_blocked", 0))
    if is_blocked:
        return {
            "has_full_access": False,
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

    has_full = bool(u.get("has_full", 0))
    return {
        "has_full_access": has_full,
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
        cur.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        u = cur.fetchone()
    conn.close()
    if not u:
        return False
    email = (u.get("email") or "").lower()
    return email in ("guillermo.jaeger@gmail.com", "admin@enviobot.com.ar") or "admin" in email

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
            SELECT id, email, password_hash, full_name, business_name,
                   COALESCE(is_blocked, 0) AS is_blocked, admin_notes
            FROM users
            WHERE email = %s LIMIT 1
        """, (email,))
        user = cur.fetchone()

        if not user or not verify_pw(password, user["password_hash"]):
            conn.close()
            return jsonify({"ok": False, "error": "Email o contraseña incorrectos."}), 401

        if user.get("is_blocked"):
            conn.close()
            return jsonify({"ok": False, "blocked": True, "error": "Tu cuenta se encuentra bloqueada por la administración. Comunicate con soporte."}), 403

        user_id = user["id"]
        # Cuentas de MeLi vinculadas
        cur.execute("""
            SELECT id, ml_user_id, ml_nickname,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_valid
            FROM ml_credentials
            WHERE user_id = %s
            ORDER BY id ASC
        """, (user_id,))
        ml_accounts = cur.fetchall()

    plan_info = get_user_plan_info(user_id, conn)
    conn.close()

    token = create_access_token(identity=str(user_id))
    return jsonify({
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "business_name": user["business_name"],
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
            "ml_accounts": ml_accounts or []
        }
    }), 200

@app.route("/api/auth/me", methods=["GET"])
@app.route("/api/full/auth/me", methods=["GET"])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, email, full_name, business_name,
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

        cur.execute("""
            SELECT id, ml_user_id, ml_nickname,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_valid
            FROM ml_credentials
            WHERE user_id = %s
            ORDER BY id ASC
        """, (user_id,))
        ml_accounts = cur.fetchall()

    plan_info = get_user_plan_info(user_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "business_name": user["business_name"],
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
_pkce_store = {}

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def generate_pkce_pair():
    code_verifier = _b64url(secrets.token_bytes(64))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode('ascii')).digest())
    return code_verifier, code_challenge

@app.route("/api/ml/auth/login", methods=["GET"])
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
        plan_info = get_user_plan_info(user_id, conn)
        max_accs = plan_info["limits"]["max_ml_accounts"]
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM ml_credentials WHERE user_id=%s", (user_id,))
            current_accs = cur.fetchone()["count"]
        conn.close()

        if current_accs >= max_accs:
            return jsonify({
                "ok": False,
                "error": f"Tu plan actual ({plan_info['plan_name']}) permite hasta {max_accs} cuenta(s) de MercadoLibre. Contactate para mejorar tu plan si necesitás más."
            }), 403

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    _pkce_store[state] = {
        'user_id': user_id,
        'code_verifier': code_verifier,
        'created_at': time.time()
    }

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

    pkce = _pkce_store.pop(state, None) if state else None
    if not code or not pkce:
        return redirect('/full/?ml=error&msg=sesion_expirada')

    user_id = pkce.get('user_id')
    try:
        r = requests.post(
            f"{MELI_API}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": ML_CLIENT_ID,
                "client_secret": ML_CLIENT_SECRET,
                "code": code,
                "redirect_uri": ML_REDIRECT_URI,
                "code_verifier": pkce["code_verifier"]
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

            # Guardar o actualizar credenciales MeLi
            cur.execute("SELECT id FROM ml_credentials WHERE user_id=%s AND ml_user_id=%s", (user_id, meli_user_id))
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
                """, (user_id, meli_user_id, access_token, refresh_token, expires_at, nickname))
                cred_id = cur.lastrowid
        conn.close()

        # Lanzar sincronización en background
        try:
            from worker import sync_account_full_catalog
            threading.Thread(target=sync_account_full_catalog, args=(user_id, cred_id, access_token, meli_user_id), daemon=True).start()
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
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, ml_user_id, ml_nickname, created_at,
                   (ml_token_expires_at > UNIX_TIMESTAMP()) AS is_active
            FROM ml_credentials
            WHERE user_id=%s
            ORDER BY id ASC
        """, (user_id,))
        accs = cur.fetchall()
    plan_info = get_user_plan_info(user_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "accounts": accs,
        "max_allowed": plan_info["limits"]["max_ml_accounts"],
        "can_add_more": len(accs) < plan_info["limits"]["max_ml_accounts"]
    }), 200

@app.route("/api/full/ml/accounts/<int:acc_id>", methods=["DELETE"])
@jwt_required()
def delete_ml_account(acc_id):
    """Desvincula una cuenta de MercadoLibre."""
    user_id = int(get_jwt_identity())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM ml_credentials WHERE id=%s AND user_id=%s", (acc_id, user_id))
    conn.close()
    return jsonify({"ok": True, "message": "Cuenta desvinculada."}), 200

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
    full_sub = get_user_full_subscription(user_id, conn)
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
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone() or {"default_lead_time_days": 7, "default_safety_stock_days": 3, "target_coverage_days": 30}

        query = """
            SELECT 
                i.id, i.item_id, i.sku, i.title, i.thumbnail, i.permalink, i.current_stock_full,
                i.ml_credential_id,
                c.ml_nickname AS account_nickname,
                COALESCE(i.lead_time_override, %s) AS effective_lead_time,
                COALESCE(i.safety_stock_override, %s) AS effective_buffer,
                f.sales_last_7d, f.sales_last_15d, f.sales_last_30d,
                f.vpd_weighted, f.days_left, f.stockout_date, f.reorder_deadline_date,
                f.suggested_restock_units, f.status, f.updated_at
            FROM full_items i
            LEFT JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
            LEFT JOIN ml_credentials c ON c.id = i.ml_credential_id
            WHERE i.user_id = %s AND i.is_monitored = 1
        """
        params = [settings["default_lead_time_days"], settings["default_safety_stock_days"], user_id]

        if account_filter and account_filter != "all":
            query += " AND i.ml_credential_id = %s"
            params.append(int(account_filter))

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

        # Resumen de contadores
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

    plan_info = get_user_plan_info(user_id, conn)
    conn.close()

    return jsonify({
        "ok": True,
        "items": items,
        "summary": summary or {"total_monitored": 0, "count_ok": 0, "count_warning": 0, "count_critical": 0},
        "settings": settings,
        "plan_info": plan_info
    }), 200

@app.route("/api/full/items/<int:item_id>", methods=["PUT"])
@jwt_required()
def update_item(item_id):
    """Actualiza Lead Time o Buffer particular de un producto."""
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

@app.route("/api/full/sync", methods=["POST"])
@app.route("/api/full/sync-now", methods=["POST"])
@jwt_required()
def trigger_sync():
    """Dispara sincronización inmediata de todas las cuentas del usuario."""
    user_id = int(get_jwt_identity())
    from worker import sync_all_accounts_for_user
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM ml_credentials WHERE user_id=%s", (user_id,))
        accounts = cur.fetchall()
    conn.close()

    if not accounts:
        return jsonify({"ok": False, "error": "Todavía no tenés cuentas de MercadoLibre vinculadas."}), 400

    threading.Thread(target=sync_all_accounts_for_user, args=(user_id,), daemon=True).start()
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

@app.route("/api/full/settings", methods=["GET", "PUT"])
@jwt_required()
def user_settings_route():
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
                "whatsapp_phone": "",
                "email_verified": False
            }
            if s and "email_verified" not in s:
                s["email_verified"] = False
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
        cur.execute("SELECT alert_email, email_verified FROM user_settings WHERE user_id=%s", (user_id,))
        prev_s = cur.fetchone()
        prev_email = prev_s.get("alert_email") if prev_s else None
        email_is_verified = prev_s.get("email_verified", False) if prev_s else False

        # Si el correo cambió, debe verificarse de nuevo
        if prev_email and new_email and prev_email.lower() != new_email.lower():
            email_is_verified = False

        cur.execute("""
            INSERT INTO user_settings 
            (user_id, default_lead_time_days, default_safety_stock_days, target_coverage_days, notify_email, alert_email, notify_whatsapp, whatsapp_phone, email_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                default_lead_time_days = VALUES(default_lead_time_days),
                default_safety_stock_days = VALUES(default_safety_stock_days),
                target_coverage_days = VALUES(target_coverage_days),
                notify_email = VALUES(notify_email),
                alert_email = VALUES(alert_email),
                notify_whatsapp = VALUES(notify_whatsapp),
                whatsapp_phone = VALUES(whatsapp_phone),
                email_verified = VALUES(email_verified)
        """, (
            user_id,
            data.get("default_lead_time_days", 7),
            data.get("default_safety_stock_days", 3),
            data.get("target_coverage_days", 30),
            data.get("notify_email", True),
            new_email,
            data.get("notify_whatsapp", False),
            new_phone,
            email_is_verified
        ))

        cur.execute("SELECT full_name FROM users WHERE id=%s", (user_id,))
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
