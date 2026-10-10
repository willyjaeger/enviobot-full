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
    formatear_alerta_critica
)
from email_service import enviar_alerta_stock_email

load_dotenv()

logger = logging.getLogger("alerts_engine")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
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


def ya_se_envio_alerta_hoy(conn, user_id: int, alert_type: str, item_id: str = None) -> bool:
    """
    Verifica si ya se envió una alerta del mismo tipo a este usuario en las últimas 20 horas.
    Evita saturar o duplicar notificaciones en ejecuciones sucesivas del cron.
    """
    limite = datetime.utcnow() - timedelta(hours=20)
    with conn.cursor() as cur:
        if item_id:
            cur.execute("""
                SELECT id FROM alert_logs 
                WHERE user_id=%s AND alert_type=%s AND item_id=%s AND sent_at >= %s
                LIMIT 1
            """, (user_id, alert_type, item_id, limite))
        else:
            cur.execute("""
                SELECT id FROM alert_logs 
                WHERE user_id=%s AND alert_type=%s AND sent_at >= %s
                LIMIT 1
            """, (user_id, alert_type, limite))
        row = cur.fetchone()
        return bool(row)


def registrar_alerta_en_log(conn, user_id: int, item_id: str, alert_type: str, mensaje: str, channel: str = "whatsapp"):
    """Registra en la tabla alert_logs para auditoría y control de frecuencia."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO alert_logs (user_id, item_id, alert_type, message, channel, sent_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (user_id, item_id, alert_type, mensaje[:250], channel))


def enviar_email_alerta(destinatario: str, asunto: str, cuerpo_texto: str, cuerpo_html: str = None):
    """Envía un email transaccional vía SMTP (DonWeb u otro)."""
    if not destinatario or not SMTP_USER or not SMTP_PASSWORD:
        logger.info(f"[Email Simulado] Para {destinatario}: {asunto}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = f"EnvioBot Full <{ALERT_SENDER_EMAIL}>"
        msg["To"] = destinatario

        msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        if cuerpo_html:
            msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=12)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(ALERT_SENDER_EMAIL, [destinatario], msg.as_string())
        server.quit()
        logger.info(f"[Email Enviado] Exitoso a {destinatario}")
        return True
    except Exception as e:
        logger.error(f"[Email Error] No se pudo enviar a {destinatario}: {e}")
        return False


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
                    i.item_id, i.sku, i.title, i.current_stock_full,
                    f.days_left, f.stockout_date, f.reorder_deadline_date,
                    f.suggested_restock_units, f.status, f.vpd_weighted
                FROM full_items i
                JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
                WHERE i.user_id = %s AND i.is_monitored = 1
                ORDER BY f.days_left ASC
            """, (user_id,))
            items = cur.fetchall()

        if not items:
            return resultado

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
            asunto_tipo = "🚨 ALARMA CRÍTICA: Quiebre de Stock Inminente"
            texto_wa = formatear_alerta_critica(
                user["full_name"],
                wh_list[0]["name"],
                criticos,
                APP_URL
            )
        elif colecta_hoy:
            nivel_alerta = "warning"
            asunto_tipo = "🚛 Pedir Colecta Hoy en MercadoLibre"
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
            asunto_tipo = "📦 Aviso Preventivo de Producción"
            texto_wa = formatear_alerta_preventiva(
                user["full_name"],
                wh_list[0]["name"],
                preventivos,
                APP_URL
            )

        # Verificar si ya se envió este tipo de alerta hoy
        if ya_se_envio_alerta_hoy(conn, user_id, nivel_alerta):
            logger.info(f"[Alerts Engine] Usuario {user_id} ya recibió alerta de nivel '{nivel_alerta}' hoy. Omitiendo.")
            return resultado

        # Obtener destinatarios de WhatsApp configurados
        with conn.cursor() as cur:
            cur.execute("""
                SELECT phone, name, role, warehouse_filter 
                FROM alert_recipients 
                WHERE user_id=%s AND is_active=1
            """, (user_id,))
            destinatarios = cur.fetchall()

        telefonos = [r["phone"] for r in destinatarios if r.get("phone")]

        # Si no tiene destinatarios en la tabla pero tiene teléfono en user_settings
        if not telefonos and settings.get("whatsapp_phone"):
            telefonos = [settings["whatsapp_phone"]]

        # 1. DISPARAR WHATSAPP
        if telefonos:
            logger.info(f"[Alerts Engine] Enviando WhatsApp a {len(telefonos)} destinatarios de usuario {user_id}")
            res_wa = enviar_lote_con_demora(telefonos, texto_wa, delay_segundos=3)
            resultado["mensajes_whatsapp_enviados"] = len(res_wa)
            # Registrar en log
            registrar_alerta_en_log(conn, user_id, "CONSOLIDADO", nivel_alerta, texto_wa, channel="whatsapp")

        # 2. DISPARAR EMAIL (Si está habilitado)
        email_dest = settings.get("alert_email") or user.get("email")
        if settings.get("notify_email") and email_dest:
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
        cur.execute("SELECT id FROM users WHERE is_active=1")
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
