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

from whatsapp_service import enviar_mensaje_whatsapp, WHATSAPP_SIMULATION_MODE, EVOLUTION_API_URL, WHATSAPP_GATEWAY_URL
from alerts_engine import procesar_alertas_usuario
from email_service import enviar_email_prueba

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
    Verifica suscripción o trial a EnvioBot Full independientemente de EnvioBot Pedidos.
    Consulta la tabla user_features (utilizada por admin.enviobot.com.ar) y features.
    Retorna si el usuario tiene acceso efectivo a Full y cuántos días le quedan.
    """
    with conn.cursor() as cur:
        # 1. Buscar en user_features vinculada con features (estándar de admin.enviobot.com.ar)
        uf = None
        try:
            cur.execute("""
                SELECT uf.*, f.feature_code, f.feature_name
                FROM user_features uf
                JOIN features f ON uf.feature_id = f.id
                WHERE uf.user_id = %s AND f.feature_code = 'enviobot_full'
                LIMIT 1
            """, (user_id,))
            uf = cur.fetchone()
        except Exception:
            pass

        # 1b. Si no se encontró por join, buscar por feature_code directo si la tabla lo tiene
        if not uf:
            try:
                cur.execute("""
                    SELECT * FROM user_features
                    WHERE user_id = %s AND (feature_id = 'enviobot_full' OR feature_code = 'enviobot_full')
                    LIMIT 1
                """, (user_id,))
                uf = cur.fetchone()
            except Exception:
                pass

        # 1c. Si no existe en user_features, buscar en user_config
        if not uf:
            try:
                cur.execute("""
                    SELECT plan_tier, subscription_status, trial_ends_at
                    FROM user_config
                    WHERE user_id = %s
                """, (user_id,))
                cfg = cur.fetchone()
                # Solo si tiene explícitamente configurado full o trial activo
                if cfg and cfg.get("subscription_status"):
                    uf = cfg
            except Exception:
                pass

        # Si el usuario NO tiene ningún registro asignado a EnvioBot Full:
        if not uf:
            return {
                "has_full_access": False,
                "is_active": False,
                "is_expired": False,
                "subscription_status": "not_subscribed",
                "plan_tier": "none",
                "plan_name": "Sin suscripción a Full",
                "can_start_trial": True,
                "trial_days_left": 0,
                "trial_ends_at": None,
                "limits": PLAN_LIMITS["trial"]
            }

        # El usuario tiene registro de EnvioBot Full
        is_active = bool(uf.get("is_active", 1))
        status = (uf.get("status") or uf.get("subscription_status") or "trial").lower()
        plan_tier = (uf.get("plan_tier") or "trial").lower()
        limits = PLAN_LIMITS.get(plan_tier, PLAN_LIMITS["trial"])

        expires_at = uf.get("expires_at") or uf.get("trial_ends_at")
        trial_days_left = 0
        is_expired = False

        if expires_at:
            delta = expires_at - datetime.utcnow()
            trial_days_left = max(0, delta.days)
            if delta.total_seconds() <= 0:
                is_expired = True
                is_active = False

        # Si está explícitamente suspendido o cancelado
        if status in ("cancelled", "suspended", "expired"):
            is_active = False

        has_access = bool(is_active and not is_expired)

        return {
            "has_full_access": has_access,
            "is_active": is_active,
            "is_expired": is_expired,
            "subscription_status": "expired" if is_expired else status,
            "plan_tier": plan_tier,
            "plan_name": limits["name"],
            "trial_days_left": trial_days_left,
            "trial_ends_at": expires_at.isoformat() if expires_at else None,
            "can_start_trial": False,  # ya utilizó o tiene asignado registro
            "limits": limits
        }

def get_user_plan_info(user_id, conn):
    """Alias compatible con llamadas previas."""
    return get_user_full_subscription(user_id, conn)

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
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "El email ya está registrado. Podés iniciar sesión directamente."}), 400

        # Crear usuario
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, business_name, platform)
            VALUES (%s, %s, %s, %s, 'ml')
        """, (email, hash_pw(password), full_name, business_name))
        user_id = cur.lastrowid

        # 30 DÍAS DE PRUEBA GRATIS DE ENVIOBOT FULL
        trial_ends_at = datetime.utcnow() + timedelta(days=30)
        try:
            cur.execute("SELECT id FROM features WHERE feature_code='enviobot_full' LIMIT 1")
            feat = cur.fetchone()
            if not feat:
                cur.execute("INSERT INTO features (feature_code, feature_name, description, is_active) VALUES ('enviobot_full', 'EnvioBot Full', 'Monitoreo de stock Full y reposición', 1)")
                feat_id = cur.lastrowid
            else:
                feat_id = feat["id"]

            cur.execute("""
                INSERT INTO user_features (user_id, feature_id, is_active, plan_tier, status, expires_at, created_at, updated_at)
                VALUES (%s, %s, 1, 'trial', 'trial', %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE is_active=1, plan_tier='trial', status='trial', expires_at=%s, updated_at=NOW()
            """, (user_id, feat_id, trial_ends_at, trial_ends_at))
        except Exception as e:
            pass

        # Configuración por defecto de stock
        cur.execute("""
            INSERT IGNORE INTO user_settings (user_id, alert_email)
            VALUES (%s, %s)
        """, (user_id, email))

    conn.close()
    token = create_access_token(identity=str(user_id))
    return jsonify({
        "ok": True,
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "has_full_access": True,
            "subscription_status": "trial",
            "can_start_trial": False,
            "plan_tier": "trial",
            "plan_name": "Prueba Gratis (30 días)",
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
            SELECT id, email, password_hash, full_name, business_name
            FROM users
            WHERE email = %s LIMIT 1
        """, (email,))
        user = cur.fetchone()

        if not user or not verify_pw(password, user["password_hash"]):
            conn.close()
            return jsonify({"ok": False, "error": "Email o contraseña incorrectos."}), 401

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
        cur.execute("SELECT id, email, full_name, business_name FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user:
            conn.close()
            return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404

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

    trial_ends_at = datetime.utcnow() + timedelta(days=30)
    with conn.cursor() as cur:
        # Asegurar feature 'enviobot_full'
        cur.execute("SELECT id FROM features WHERE feature_code='enviobot_full' LIMIT 1")
        feat = cur.fetchone()
        if not feat:
            cur.execute("INSERT INTO features (feature_code, feature_name, description, is_active) VALUES ('enviobot_full', 'EnvioBot Full', 'Monitoreo de stock Full y reposición', 1)")
            feat_id = cur.lastrowid
        else:
            feat_id = feat["id"]

        # Insertar o actualizar user_features
        cur.execute("""
            INSERT INTO user_features (user_id, feature_id, is_active, plan_tier, status, expires_at, created_at, updated_at)
            VALUES (%s, %s, 1, 'trial', 'trial', %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE is_active=1, plan_tier='trial', status='trial', expires_at=%s, updated_at=NOW()
        """, (user_id, feat_id, trial_ends_at, trial_ends_at))

        cur.execute("INSERT IGNORE INTO user_settings (user_id) VALUES (%s)", (user_id,))

    conn.close()

    conn2 = get_db()
    new_sub = get_user_full_subscription(user_id, conn2)
    conn2.close()

    return jsonify({
        "ok": True,
        "message": "¡Tus 30 días de prueba gratis en EnvioBot Full están activos!",
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

                # ACTIVAR 30 DÍAS DE PRUEBA GRATIS
                trial_ends_at = datetime.utcnow() + timedelta(days=30)
                cur.execute("SELECT id FROM features WHERE feature_code='enviobot_full' LIMIT 1")
                feat = cur.fetchone()
                if not feat:
                    cur.execute("INSERT INTO features (feature_code, feature_name, description, is_active) VALUES ('enviobot_full', 'EnvioBot Full', 'Monitoreo de stock Full y reposición', 1)")
                    feat_id = cur.lastrowid
                else:
                    feat_id = feat["id"]

                cur.execute("""
                    INSERT INTO user_features (user_id, feature_id, is_active, plan_tier, status, expires_at, created_at, updated_at)
                    VALUES (%s, %s, 1, 'trial', 'trial', %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE is_active=1, plan_tier='trial', status='trial', expires_at=%s, updated_at=NOW()
                """, (user_id, feat_id, trial_ends_at, trial_ends_at))

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
            SELECT id, name, phone, role, warehouse_filter, is_active, created_at
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

    if not phone:
        return jsonify({"ok": False, "error": "Debe especificar un número de teléfono."}), 400

    sample_msg = (
        f"🚨 *¡Alarma de Prueba EnvioBot Full!*\n"
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
                "whatsapp_phone": ""
            }
        conn.close()
        return jsonify({"ok": True, "settings": s}), 200

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

    res = enviar_email_prueba(dest, name)
    return jsonify({
        "ok": res.get("ok", False),
        "message": f"Correo de prueba enviado a {dest}",
        "detail": res
    }), 200

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
