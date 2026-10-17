#!/usr/bin/env python3
"""
alerts_engine.py - Motor Inteligente de Disparo y Consolidación de Alertas
Evalúa periódicamente los pronósticos de quiebre de stock,
agrupa los productos en un único Digest matutino y dispara notificaciones
por WhatsApp y Email según los roles y depósitos configurados.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date

import pymysql
from dotenv import load_dotenv

from whatsapp_service import (
    enviar_lote_con_demora,
    formatear_alerta_preventiva,
    formatear_alerta_colecta_hoy,
    formatear_alerta_critica,
    formatear_alerta_resumen_diario,
    obtener_configuracion_whatsapp
)
from email_service import enviar_alerta_stock_email, enviar_email
import esquema
import proyeccion
from horario_whatsapp import horario_de, en_horario
from whatsapp_service import normalizar_telefono

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv()

logger = logging.getLogger("alerts_engine")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "enviobot")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.donweb.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_SENDER_EMAIL = os.getenv("ALERT_SENDER_EMAIL", "alertas@enviobot.com.ar")
APP_URL = os.getenv("APP_URL", "https://enviobot.com.ar/full")


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


def ya_se_envio_alerta_hoy(conn, user_id: int, alert_type: str, item_id: str = None, horas_cooldown: int = 20, channel: str = None) -> bool:
    """
    Verifica si ya se envió una alerta del mismo tipo a este usuario dentro de la ventana de cooldown (por defecto 20 horas).
    Evita saturar o duplicar notificaciones en ejecuciones sucesivas del cron.
    """
    limite = datetime.utcnow() - timedelta(hours=horas_cooldown)
    con_canal = " AND channel=%s" if channel else ""
    extra = (channel,) if channel else ()
    with conn.cursor() as cur:
        if item_id:
            cur.execute("""
                SELECT id FROM alert_logs
                WHERE user_id=%s AND alert_type=%s AND item_id=%s AND sent_at >= %s""" + con_canal + """
                LIMIT 1
            """, (user_id, alert_type, item_id, limite) + extra)
        else:
            cur.execute("""
                SELECT id FROM alert_logs
                WHERE user_id=%s AND alert_type=%s AND sent_at >= %s""" + con_canal + """
                LIMIT 1
            """, (user_id, alert_type, limite) + extra)
        row = cur.fetchone()
        return bool(row)


def wa_ya_enviado(conn, user_id: int, nivel: str, phone: str, horas_cooldown: int = 20) -> bool:
    """Cada destinatario tiene su propio control, porque cada uno puede tener su horario.
    También cuenta el registro viejo CONSOLIDADO (de antes de los horarios por destinatario)."""
    clave = "wa:" + normalizar_telefono(phone)
    return (ya_se_envio_alerta_hoy(conn, user_id, nivel, item_id=clave, horas_cooldown=horas_cooldown, channel="whatsapp")
            or ya_se_envio_alerta_hoy(conn, user_id, nivel, item_id="CONSOLIDADO", horas_cooldown=horas_cooldown, channel="whatsapp"))


def registrar_alerta_en_log(conn, user_id: int, item_id: str, alert_type: str, mensaje: str, channel: str = "whatsapp"):
    """Registra en la tabla alert_logs para auditoría y control de frecuencia."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_logs (user_id, item_id, alert_type, message, channel, sent_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (user_id, item_id, alert_type, mensaje[:250], channel))
    except Exception as e:
        logger.warning(f"[Alert Logs] Error registrando en tabla alert_logs: {e}")


def enviar_email_alerta(destinatario: str, asunto: str, cuerpo_texto: str, cuerpo_html: str = None):
    """Envía un email transaccional vía SMTP usando la cuenta de alertas configurada."""
    res = enviar_email(destinatario, asunto, cuerpo_texto, cuerpo_html)
    return bool(res.get("ok", False))



def procesar_alertas_usuario(user_id: int) -> dict:
    """
    Evalúa todos los pronósticos de un usuario y dispara las alertas correspondientes
    si hay productos en fecha límite o en riesgo crítico de quiebre.
    """
    conn = get_db()
    resultado = {
        "user_id": user_id,
        "items_criticos": 0,
        "items_colecta_hoy": 0,
        "items_preventivos": 0,
        "mensajes_whatsapp_enviados": 0,
        "email_enviado": False
    }

    try:
        with conn.cursor() as cur:
            # Obtener datos de usuario
            cur.execute("SELECT id, full_name, email FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone()
            if not user:
                return resultado

            # Obtener configuración del usuario
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            settings = cur.fetchone() or {
                "default_lead_time_days": 7,
                "default_safety_stock_days": 3,
                "notify_email": True,
                "alert_email": user["email"],
                "notify_whatsapp": True
            }

            # Obtener depósitos activos del usuario
            cur.execute("SELECT * FROM warehouses WHERE user_id=%s AND is_active=1", (user_id,))
            wh_list = cur.fetchall()
            if not wh_list:
                wh_list = [{
                    "id": 0,
                    "code": "meli_full",
                    "name": "Mercado Envíos Full (Bs As)",
                    "transit_days": settings.get("default_lead_time_days", 5)
                }]

            # Obtener publicaciones monitoreadas con sus pronósticos
            cur.execute("""
                SELECT 
                    i.item_id, i.sku, i.inventory_id, i.variation_id, i.title, i.current_stock_full,
                    f.days_left, f.stockout_date, f.reorder_deadline_date,
                    f.suggested_restock_units, f.status, f.vpd_weighted
                FROM full_items i
                JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
                     AND ( (i.variation_id IS NULL AND f.variation_id IS NULL) OR (f.variation_id = i.variation_id) )
                WHERE i.user_id = %s AND i.is_monitored = 1
                ORDER BY f.days_left ASC
            """, (user_id,))
            items = cur.fetchall()

        if not items:
            return resultado

        # Consolidar por producto físico para evitar notificaciones duplicadas (Clásica vs Premium vs Catálogo)
        dedup_items = {}
        for it in items:
            key = (it.get("inventory_id") or "").strip() or (it.get("sku") or "").strip().upper() or f"{it['item_id']}_{it.get('variation_id') or ''}"
            if key not in dedup_items:
                dedup_items[key] = it
            else:
                prev = dedup_items[key]
                if (it.get("days_left") or 999) < (prev.get("days_left") or 999):
                    dedup_items[key] = it
        items = list(dedup_items.values())

        today = date.today()
        criticos = []
        colecta_hoy = []
        preventivos = []

        for it in items:
            st = it.get("status")
            reorder_dt = it.get("reorder_deadline_date")
            stock = it.get("current_stock_full", 0)

            # Clasificación progresiva
            if st in ("critical", "out_of_stock") or stock <= 0:
                criticos.append(it)
            elif st == "warning" or (reorder_dt and reorder_dt <= today):
                colecta_hoy.append(it)
            elif reorder_dt and (reorder_dt <= (today + timedelta(days=4))):
                preventivos.append(it)

        resultado["items_criticos"] = len(criticos)
        resultado["items_colecta_hoy"] = len(colecta_hoy)
        resultado["items_preventivos"] = len(preventivos)

        # Si no hay ningún producto en alerta, terminamos
        if not criticos and not colecta_hoy and not preventivos:
            return resultado

        # Seleccionar el nivel prioritario para el mensaje consolidado de hoy
        if criticos:
            nivel_alerta = "critical"
            asunto_tipo = "ALARMA CRITICA: Quiebre de Stock Inminente"
            texto_wa = formatear_alerta_critica(
                user["full_name"],
                wh_list[0]["name"],
                criticos,
                APP_URL
            )
        elif colecta_hoy:
            nivel_alerta = "warning"
            asunto_tipo = "Pedir Colecta Hoy en MercadoLibre"
            total_bultos = sum(x.get("suggested_restock_units", 0) for x in colecta_hoy)
            texto_wa = formatear_alerta_colecta_hoy(
                user["full_name"],
                wh_list[0]["name"],
                colecta_hoy,
                total_bultos,
                APP_URL
            )
        else:
            nivel_alerta = "preventive"
            asunto_tipo = "Aviso Preventivo de Producción"
            texto_wa = formatear_alerta_preventiva(
                user["full_name"],
                wh_list[0]["name"],
                preventivos,
                APP_URL
            )

        # Obtener configuración de WhatsApp y cadencia desde site_settings (admin)
        wa_cfg = obtener_configuracion_whatsapp()
        cadence = wa_cfg.get("cadence", {})
        cooldown_hours = int(cadence.get("cooldown_hours", 20))
        pacing_delay = int(cadence.get("pacing_delay_seconds", 3))

        # El cooldown es por canal, y el de WhatsApp es por destinatario: cada uno tiene su horario.
        # Si a alguien le toca fuera de su horario, espera a la próxima corrida dentro de él;
        # el mail que ya salió no lo frena.
        ya_mail = ya_se_envio_alerta_hoy(conn, user_id, nivel_alerta, horas_cooldown=cooldown_hours, channel="email")
        enviar_mail = not ya_mail

        # Destinatarios de WhatsApp con su horario (el suyo, o el del dueño si no cambió nada)
        horario_dueno = horario_de(settings)
        destinos = {}  # teléfono -> horario

        with conn.cursor() as cur:
            con_horario = esquema.tiene_columna(cur, "alert_recipients", "wa_days")
            cur.execute("""
                SELECT phone, name, role, warehouse_filter""" + (", wa_days, wa_from, wa_to" if con_horario else "") + """
                FROM alert_recipients 
                WHERE user_id=%s AND is_active=1
            """, (user_id,))
            destinatarios = cur.fetchall()

        for r in destinatarios:
            if r.get("phone"):
                destinos.setdefault(r["phone"], horario_de(r, horario_dueno))

        # Si no tiene destinatarios en la tabla pero tiene teléfono en user_settings
        if not destinos and settings.get("whatsapp_phone"):
            destinos[settings["whatsapp_phone"]] = horario_dueno

        # Sumar destinatarios administradores/globales configurados en admin.enviobot.com.ar
        admin_recs = wa_cfg.get("recipients", [])
        for ar in admin_recs:
            if ar.get("active", True) and ar.get("phone"):
                key_map = {
                    "preventive": "notify_preventive",
                    "warning": "notify_colecta",
                    "critical": "notify_critical"
                }
                notif_flag = key_map.get(nivel_alerta, "notify_daily_digest")
                if ar.get(notif_flag, True) or ar.get("notify_daily_digest", True):
                    destinos.setdefault(ar["phone"], horario_dueno)

        ahora_ba = datetime.now(proyeccion.HORA_BA)
        pendientes = [t for t in destinos if not wa_ya_enviado(conn, user_id, nivel_alerta, t, cooldown_hours)]
        telefonos = [t for t in pendientes if en_horario(destinos[t], ahora_ba)]
        if pendientes and not telefonos:
            logger.info(f"[Alerts Engine] Usuario {user_id}: los {len(pendientes)} destinatarios pendientes están fuera de su horario de WhatsApp. Se manda en la próxima corrida dentro del horario.")
        enviar_wa = bool(telefonos) and wa_cfg.get("enabled", True)
        if not enviar_wa and not enviar_mail:
            logger.info(f"[Alerts Engine] Usuario {user_id}: nada para enviar de nivel '{nivel_alerta}' (ya enviado en las últimas {cooldown_hours}hs o fuera de horario). Omitiendo.")
            return resultado

        # 1. DISPARAR WHATSAPP (Si está habilitado globalmente)
        if enviar_wa:
            logger.info(f"[Alerts Engine] Enviando WhatsApp a {len(telefonos)} destinatarios para usuario {user_id}")
            res_wa = enviar_lote_con_demora(telefonos, texto_wa, delay_segundos=pacing_delay)
            resultado["mensajes_whatsapp_enviados"] = len(res_wa)
            for t in telefonos:
                registrar_alerta_en_log(conn, user_id, "wa:" + normalizar_telefono(t), nivel_alerta, texto_wa, channel="whatsapp")

        # 2. DISPARAR EMAIL (Si está habilitado)
        email_dest = settings.get("alert_email") or user.get("email")
        if enviar_mail and settings.get("notify_email") and email_dest:
            items_para_email = criticos if criticos else (colecta_hoy if colecta_hoy else preventivos)
            res_mail = enviar_alerta_stock_email(
                destinatario=email_dest,
                nombre_usuario=user["full_name"],
                deposito_nombre=wh_list[0]["name"],
                items=items_para_email,
                nivel=nivel_alerta
            )
            enviado_mail = res_mail.get("ok", False)
            resultado["email_enviado"] = enviado_mail
            if enviado_mail:
                registrar_alerta_en_log(conn, user_id, "CONSOLIDADO", nivel_alerta, f"Email enviado a {email_dest}", channel="email")

    finally:
        conn.close()

    return resultado


def ejecutar_motor_alertas_global():
    """
    Recorre todos los usuarios activos y evalúa si corresponde enviar alertas hoy.
    Invocado automáticamente por worker.py o por el cron de Linux.
    """
    logger.info("=== INICIANDO MOTOR DE ALERTAS GLOBAL ENVIOBOT FULL ===")
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM users LIKE 'is_blocked'")
        has_blocked = bool(cur.fetchone())
        cur.execute("SHOW COLUMNS FROM users LIKE 'active'")
        has_active = bool(cur.fetchone())
        conds = []
        if has_active:
            conds.append("active=1")
        if has_blocked:
            conds.append("is_blocked=0")
        where_clause = " AND ".join(conds) if conds else "1=1"
        cur.execute(f"SELECT id FROM users WHERE {where_clause}")
        usuarios = cur.fetchall()
    conn.close()

    total_usuarios = len(usuarios)
    alertas_enviadas = 0

    for u in usuarios:
        try:
            res = procesar_alertas_usuario(u["id"])
            if res.get("mensajes_whatsapp_enviados", 0) > 0 or res.get("email_enviado"):
                alertas_enviadas += 1
        except Exception as e:
            logger.error(f"Error procesando alertas para usuario {u['id']}: {e}")

    logger.info(f"=== MOTOR DE ALERTAS FINALIZADO: {alertas_enviadas}/{total_usuarios} usuarios notificados ===")
    return {"total_usuarios": total_usuarios, "alertas_enviadas": alertas_enviadas}


if __name__ == "__main__":
    ejecutar_motor_alertas_global()
