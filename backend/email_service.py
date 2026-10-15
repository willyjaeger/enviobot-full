#!/usr/bin/env python3
"""
email_service.py - Servicio Profesional de Correo Saliente (SMTP Ferozo / DonWeb)
Envía alertas transaccionales por email con plantillas HTML responsivas
y diseño corporativo oficial según especificaciones de marca de EnvioBot.

Especificaciones respetadas (ver docs/LOGO_SPECS_PARA_ANTIGRAVITY.md):
- EnvioBot Pedidos / General: Icono impresora SVG (24x24 trazo 1.7) + wordmark "EnvioBot" (peso 800, #e8e9ed).
- EnvioBot Full: Icono cajita isométrica SVG (24x24 trazo 1.8, R=2.5) + wordmark "EnvioBot Full" (Full en #f5a623).
- Tipografía: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif
- Tokens: --bg #111318, --surface #1c1e26, --surf2 #252830, --text #e8e9ed, --text2 #8a8d9a, --accent #f5a623.
"""

import os
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid, formataddr
from datetime import datetime
from dotenv import load_dotenv
import pymysql
import pymysql.cursors

load_dotenv()

logger = logging.getLogger("email_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

# Variables de entorno por defecto
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "enviobot" if os.path.exists("/var/www") else "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

DEFAULT_SMTP_HOST = os.getenv("SMTP_HOST", "po000380.ferozo.com")
DEFAULT_SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "soporte@enviobot.com.ar")
APP_URL = os.getenv("APP_URL", "https://enviobot.com.ar/full")

# Assets oficiales servidos vía HTTPS
URL_ICON_CAJITA = "https://enviobot.com.ar/assets/icon-cajita-full.png"
URL_ICON_PRINTER = "https://enviobot.com.ar/assets/icon-printer-enviobot.png"


def get_db():
    """Conexión a la base de datos MySQL unificada para leer configuraciones de admin."""
    try:
        return pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
    except Exception as e:
        logger.warning(f"[email_service] No se pudo conectar a la base de datos: {e}")
        return None


def _get_settings_from_db(keys: list) -> dict:
    """Obtiene los settings desde la tabla site_settings de admin.enviobot."""
    conn = get_db()
    res = {}
    if not conn:
        return res
    try:
        with conn.cursor() as cur:
            format_strings = ','.join(['%s'] * len(keys))
            cur.execute(f"SELECT setting_key, setting_value FROM site_settings WHERE setting_key IN ({format_strings})", tuple(keys))
            for row in cur.fetchall():
                res[row["setting_key"]] = row["setting_value"]
    except Exception as e:
        logger.warning(f"[email_service] Error consultando site_settings: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return res


def get_welcome_smtp_config() -> dict:
    """
    Configuración de la cuenta de Bienvenida y Envío de Códigos (hola@enviobot.com.ar).
    Prioriza los valores guardados en admin.enviobot.com.ar (site_settings).
    """
    db_cfg = _get_settings_from_db([
        "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_sender_name"
    ])
    port = db_cfg.get("smtp_port") or os.getenv("WELCOME_SMTP_PORT", str(DEFAULT_SMTP_PORT))
    try:
        port = int(port)
    except (ValueError, TypeError):
        port = 465

    user = (db_cfg.get("smtp_user") or os.getenv("WELCOME_SENDER_EMAIL", "hola@enviobot.com.ar")).strip()
    return {
        "host": (db_cfg.get("smtp_host") or os.getenv("WELCOME_SMTP_HOST", DEFAULT_SMTP_HOST)).strip(),
        "port": port,
        "user": user,
        "password": db_cfg.get("smtp_password") or os.getenv("WELCOME_SMTP_PASSWORD", ""),
        "sender_name": (db_cfg.get("smtp_sender_name") or os.getenv("WELCOME_SENDER_NAME", "EnvioBot")).strip(),
        "sender_email": user,
        "reply_to": REPLY_TO_EMAIL
    }


def get_alert_smtp_config() -> dict:
    """
    Configuración de la cuenta de Alertas de Stock de Full (alertafull@enviobot.com.ar).
    Prioriza los valores guardados en admin.enviobot.com.ar (site_settings).
    """
    db_cfg = _get_settings_from_db([
        "smtp_alertafull_host", "smtp_alertafull_port", "smtp_alertafull_user",
        "smtp_alertafull_password", "smtp_alertafull_sender_name"
    ])
    port = db_cfg.get("smtp_alertafull_port") or os.getenv("ALERT_SMTP_PORT", str(DEFAULT_SMTP_PORT))
    try:
        port = int(port)
    except (ValueError, TypeError):
        port = 465

    user = (db_cfg.get("smtp_alertafull_user") or os.getenv("ALERT_SENDER_EMAIL", "alertafull@enviobot.com.ar")).strip()
    return {
        "host": (db_cfg.get("smtp_alertafull_host") or os.getenv("ALERT_SMTP_HOST", DEFAULT_SMTP_HOST)).strip(),
        "port": port,
        "user": user,
        "password": db_cfg.get("smtp_alertafull_password") or os.getenv("ALERT_SMTP_PASSWORD", ""),
        "sender_name": (db_cfg.get("smtp_alertafull_sender_name") or os.getenv("ALERT_SENDER_NAME", "EnvioBot Full")).strip(),
        "sender_email": user,
        "reply_to": REPLY_TO_EMAIL
    }


def _generar_plantilla_html(titulo_banner: str, subtitulo: str, nombre_usuario: str, deposito_nombre: str, items: list, nivel: str, es_full: bool = True) -> str:
    """
    Genera una plantilla HTML moderna, responsiva y oficial respetando estrictamente
    las especificaciones de icono, wordmark, tipografía y tokens de marca.
    """
    color_banner = "#f5a623" if nivel == "warning" else ("#ff5252" if nivel == "critical" else "#4caf50")
    etiqueta_nivel = "PEDIR COLECTA HOY" if nivel == "warning" else ("RIESGO CRÍTICO" if nivel == "critical" else "AVISO PREVENTIVO")

    icon_url = URL_ICON_CAJITA if es_full else URL_ICON_PRINTER
    wordmark_html = (
        'EnvioBot <span style="color: #f5a623;">Full</span>'
        if es_full else
        'EnvioBot'
    )
    product_label = "EnvioBot Full · Monitoreo y Pronóstico de Stock en Mercado Envíos Full" if es_full else "EnvioBot · Automatización de Etiquetas y Pedidos"

    filas_html = ""
    for it in items[:12]:
        sku_str = f"<span style='color: #8a8d9a; font-size: 11px; font-weight: 500;'>SKU: {it.get('sku')}</span><br>" if it.get("sku") else ""
        dias = it.get('days_left', 0)
        sug = it.get('suggested_restock_units', 0)
        quiebre = it.get('stockout_date') or "Pronto"
        stock_act = it.get('current_stock_full', 0)

        filas_html += f"""
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.07);">
            <td style="padding: 12px 14px; font-size: 13.5px; color: #e8e9ed; line-height: 1.4;">
                {sku_str}<strong style="color: #e8e9ed;">{it.get('title', '')[:55]}</strong>
            </td>
            <td style="padding: 12px 14px; font-size: 13.5px; text-align: center; color: #cfd3dc;">
                {stock_act} un.
            </td>
            <td style="padding: 12px 14px; font-size: 13.5px; text-align: center; color: #cfd3dc;">
                {dias} d
            </td>
            <td style="padding: 12px 14px; font-size: 13.5px; text-align: center; font-weight: 700; color: {color_banner};">
                {quiebre}
            </td>
            <td style="padding: 12px 14px; font-size: 14px; text-align: center; font-weight: 700; color: #f5a623;">
                {sug} un.
            </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{titulo_banner}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #111318; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; color: #e8e9ed;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #111318; padding: 25px 10px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width: 600px; width: 100%; background-color: #1c1e26; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; overflow: hidden; box-shadow: 0 12px 36px rgba(0,0,0,0.5);">
                    <!-- Encabezado con Identidad Oficial de Marca -->
                    <tr>
                        <td style="background-color: #11141a; padding: 20px 28px; border-bottom: 2px solid {color_banner};">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td valign="middle" align="left">
                                        <table cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td valign="middle" style="vertical-align: middle; padding-right: 10px; line-height: 0;">
                                                    <img src="{icon_url}" width="24" height="24" alt="EnvioBot" style="display: block; width: 24px; height: 24px; border: 0;" />
                                                </td>
                                                <td valign="middle" style="vertical-align: middle; line-height: 1;">
                                                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 20px; font-weight: 800; letter-spacing: -0.2px; color: #e8e9ed;">
                                                        {wordmark_html}
                                                    </span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td valign="middle" align="right">
                                        <span style="background-color: rgba(245, 166, 35, 0.15); color: {color_banner}; border: 1px solid {color_banner}; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                                            {etiqueta_nivel}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Cuerpo Principal -->
                    <tr>
                        <td style="padding: 28px;">
                            <h2 style="margin: 0 0 10px 0; font-size: 19px; color: #e8e9ed; font-weight: 700; letter-spacing: -0.02em;">
                                {titulo_banner}
                            </h2>
                            <p style="margin: 0 0 20px 0; font-size: 14px; color: #8a8d9a; line-height: 1.6;">
                                Hola <strong style="color: #e8e9ed;">{nombre_usuario}</strong>, este es tu reporte matutino de stock para el depósito <strong style="color: #e8e9ed;">{deposito_nombre}</strong>.<br>
                                {subtitulo}
                            </p>

                            <!-- Tabla de Artículos -->
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse; background-color: #151820; border-radius: 6px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 24px;">
                                <thead>
                                    <tr style="background-color: #1c212b; border-bottom: 1px solid rgba(255,255,255,0.08);">
                                        <th style="padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #8a8d9a; text-align: left;">Publicación / SKU</th>
                                        <th style="padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #8a8d9a; text-align: center;">Stock</th>
                                        <th style="padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #8a8d9a; text-align: center;">Días</th>
                                        <th style="padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #8a8d9a; text-align: center;">Quiebra</th>
                                        <th style="padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #8a8d9a; text-align: center;">A Mandar</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filas_html}
                                </tbody>
                            </table>

                            <!-- Botón de Acción Principal -->
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td align="center" style="padding: 10px 0 16px 0;">
                                        <a href="{APP_URL}" target="_blank" style="display: inline-block; background-color: #f5a623; color: #14100a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 14.5px; font-weight: 700; text-decoration: none; padding: 13px 30px; border-radius: 8px; box-shadow: 0 4px 14px rgba(245, 166, 35, 0.3);">
                                            Abrir Remito y Armar Colecta en MeLi
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <p style="font-size: 12.5px; color: #8a8d9a; text-align: center; margin: 12px 0 0 0; line-height: 1.5;">
                                Si solicitás el turno hoy en MercadoLibre, el camión llega a destino antes de agotar el inventario.
                            </p>
                        </td>
                    </tr>

                    <!-- Pie de Correo con Identidad -->
                    <tr>
                        <td style="background-color: #11141a; padding: 20px 28px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 12px; color: #8a8d9a; text-align: center; line-height: 1.6;">
                            <table cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto 6px auto;">
                                <tr>
                                    <td valign="middle" style="vertical-align: middle; padding-right: 8px; line-height: 0;">
                                        <img src="{icon_url}" width="16" height="16" alt="" style="display: block; width: 16px; height: 16px; opacity: 0.8;" />
                                    </td>
                                    <td valign="middle" style="vertical-align: middle; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 12.5px; font-weight: 800; letter-spacing: -0.2px; color: #e8e9ed;">
                                        {wordmark_html}
                                    </td>
                                </tr>
                            </table>
                            {product_label}<br>
                            Notificaciones Oficiales · <a href="{APP_URL}" style="color: #f5a623; text-decoration: none; font-weight: 600;">enviobot.com.ar/full</a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    return html


def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str, cuerpo_html: str = None, smtp_cfg: dict = None) -> dict:
    """
    Función de despacho a través de SMTP SSL/TLS usando la configuración indicada.
    Si no se especifica smtp_cfg, utiliza por defecto la cuenta de alertas de Full.
    """
    if not destinatario:
        return {"ok": False, "error": "Destinatario vacío"}

    cfg = smtp_cfg or get_alert_smtp_config()
    sender_email = cfg.get("sender_email") or cfg.get("user")
    sender_name = cfg.get("sender_name", "EnvioBot")
    host = cfg.get("host")
    port = cfg.get("port", 465)
    password = cfg.get("password", "")

    # Modo simulación si falta la contraseña
    if not password:
        logger.info(f"[SIMULACIÓN EMAIL]\nDe: {sender_name} <{sender_email}>\nPara: {destinatario}\nAsunto: {asunto}\n{cuerpo_texto[:180]}...")
        return {
            "ok": True,
            "simulated": True,
            "to": destinatario,
            "subject": asunto,
            "message": f"Email en modo simulación (configurar contraseña para {sender_email} en admin.enviobot.com.ar)."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = formataddr((sender_name, sender_email))
        msg["To"] = destinatario
        if cfg.get("reply_to"):
            msg["Reply-To"] = cfg.get("reply_to")
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="enviobot.com.ar")
        msg["X-Mailer"] = "EnvioBot Notification Service"

        msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        if cuerpo_html:
            msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        contexto = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=14, context=contexto)
        else:
            server = smtplib.SMTP(host, port, timeout=14)
            server.ehlo()
            server.starttls(context=contexto)
            server.ehlo()

        server.login(cfg["user"], password)
        server.sendmail(sender_email, [destinatario], msg.as_string())
        server.quit()

        logger.info(f"[SMTP {sender_email}] Correo enviado exitosamente a {destinatario}")
        return {"ok": True, "to": destinatario, "subject": asunto, "from": sender_email}
    except Exception as e:
        logger.error(f"[SMTP Error ({sender_email})] No se pudo enviar a {destinatario}: {e}")
        return {"ok": False, "error": str(e), "to": destinatario, "from": sender_email}


def enviar_alerta_stock_email(destinatario: str, nombre_usuario: str, deposito_nombre: str, items: list, nivel: str) -> dict:
    """
    Envía la alerta de stock estructurada usando la cuenta oficial de alertas:
    alertafull@enviobot.com.ar
    Con el icono oficial de cajita y wordmark EnvioBot Full.
    """
    if nivel == "critical":
        asunto = f"EnvioBot Full: Alerta Crítica de Quiebre de Stock ({deposito_nombre})"
        titulo = "Riesgo Inminente de Quiebre de Stock"
        subtitulo = "Las siguientes publicaciones se quedarán sin inventario antes de que arribe un flete habitual. Se requiere despacho urgente."
    elif nivel == "warning":
        asunto = f"EnvioBot Full: Pedir Colecta Hoy en MercadoLibre ({deposito_nombre})"
        titulo = "Fecha Límite de Colecta Alcanzada"
        subtitulo = "Hoy es la fecha óptima para pedir turno en MercadoLibre. Si solicitás el turno hoy, el flete llegará antes del agotamiento."
    else:
        asunto = f"EnvioBot Full: Planificación Preventiva de Colecta ({deposito_nombre})"
        titulo = "Aviso Preventivo de Producción"
        subtitulo = "Tus ventas registran buen ritmo. En los próximos días alcanzarás la fecha límite de reposición para estos artículos."

    # Texto plano fallback
    texto_plano = f"EnvioBot Full - {titulo}\nHola {nombre_usuario}, depósito: {deposito_nombre}\n\n"
    for it in items[:10]:
        texto_plano += f"• [{it.get('sku') or 'Sin SKU'}] {it.get('title')}: Stock {it.get('current_stock_full', 0)} un. - Mandar: {it.get('suggested_restock_units', 0)} un. (Quiebra: {it.get('stockout_date')})\n"
    texto_plano += f"\nAccedé a tu panel para descargar la lista o imprimir el remito: {APP_URL}\n"

    # HTML enriquecido oficial con cajita y wordmark
    html = _generar_plantilla_html(titulo, subtitulo, nombre_usuario, deposito_nombre, items, nivel, es_full=True)

    # Usa cuenta de alertas Full: alertafull@enviobot.com.ar
    return enviar_email(destinatario, asunto, texto_plano, html, smtp_cfg=get_alert_smtp_config())


def enviar_email_bienvenida_verificacion(destinatario: str, nombre_usuario: str, codigo_verificacion: str, app_url: str = APP_URL) -> dict:
    """
    Envía el email de bienvenida y vinculación con código de 6 dígitos usando la cuenta:
    hola@enviobot.com.ar
    Con el logo oficial y tipografía institucional de EnvioBot Full.
    """
    asunto = f"EnvioBot Full: Codigo de Vinculacion de Correo [{codigo_verificacion}]"
    enlace_confirmacion = f"{app_url}/?verify_code={codigo_verificacion}&channel=email&email={destinatario}"
    
    texto_plano = (
        f"EnvioBot Full - Bienvenida y Vinculacion de Correo\n\n"
        f"Hola {nombre_usuario}:\n"
        f"Te damos la bienvenida a EnvioBot Full.\n\n"
        f"Para asegurar que recibas los reportes matutinos y avisos de quiebre de stock a tiempo, "
        f"tu codigo de vinculacion es: {codigo_verificacion}\n\n"
        f"Tambien podes confirmar tu cuenta con 1 clic en este enlace:\n"
        f"{enlace_confirmacion}\n\n"
        f"EnvioBot Full - enviobot.com.ar/full\n"
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bienvenida a EnvioBot Full</title>
</head>
<body style="margin: 0; padding: 0; background-color: #111318; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; color: #e8e9ed;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #111318; padding: 25px 10px;">
        <tr>
            <td align="center">
                <table width="580" cellpadding="0" cellspacing="0" border="0" style="max-width: 580px; width: 100%; background-color: #1c1e26; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; overflow: hidden; box-shadow: 0 12px 36px rgba(0,0,0,0.5);">
                    <!-- Encabezado con Identidad Oficial de Marca -->
                    <tr>
                        <td style="background-color: #11141a; padding: 20px 28px; border-bottom: 2px solid #f5a623;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td valign="middle" align="left">
                                        <table cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td valign="middle" style="vertical-align: middle; padding-right: 10px; line-height: 0;">
                                                    <img src="{URL_ICON_CAJITA}" width="24" height="24" alt="EnvioBot Full" style="display: block; width: 24px; height: 24px; border: 0;" />
                                                </td>
                                                <td valign="middle" style="vertical-align: middle; line-height: 1;">
                                                    <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 20px; font-weight: 800; letter-spacing: -0.2px; color: #e8e9ed;">
                                                        EnvioBot <span style="color: #f5a623;">Full</span>
                                                    </span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td valign="middle" align="right">
                                        <span style="background-color: rgba(245, 166, 35, 0.15); color: #f5a623; border: 1px solid #f5a623; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                                            VINCULACIÓN DE CASILLA
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Cuerpo Principal -->
                    <tr>
                        <td style="padding: 28px;">
                            <h2 style="margin: 0 0 10px 0; font-size: 19px; color: #e8e9ed; font-weight: 700; letter-spacing: -0.02em;">
                                ¡Te damos la bienvenida a EnvioBot Full!
                            </h2>
                            <p style="margin: 0 0 20px 0; font-size: 14px; color: #8a8d9a; line-height: 1.6;">
                                Hola <strong style="color: #e8e9ed;">{nombre_usuario}</strong>, vinculamos tu cuenta de Mercado Libre para monitorear tu stock en el centro de distribución de Mercado Envíos Full.<br><br>
                                Para asegurarnos de que esta casilla reciba sin inconvenientes los <strong style="color: #e8e9ed;">reportes matutinos y avisos de quiebre de stock</strong>, ingresá el siguiente código de confirmación:
                            </p>

                            <!-- Código en caja destacada -->
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 22px 0;">
                                <tr>
                                    <td align="center" style="background-color: #151820; border: 2px dashed #f5a623; border-radius: 8px; padding: 18px 20px;">
                                        <div style="font-size: 11px; text-transform: uppercase; color: #8a8d9a; letter-spacing: 1.2px; font-weight: 700; margin-bottom: 6px;">
                                            Código de Vinculación
                                        </div>
                                        <div style="font-size: 34px; font-weight: 900; letter-spacing: 8px; color: #f5a623; font-family: 'Courier New', Courier, monospace;">
                                            {codigo_verificacion}
                                        </div>
                                    </td>
                                </tr>
                            </table>

                            <!-- Botón de 1 Clic Directo -->
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 16px 0 24px 0;">
                                <tr>
                                    <td align="center">
                                        <a href="{enlace_confirmacion}" target="_blank" style="display: inline-block; background-color: #f5a623; color: #14100a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 14.5px; font-weight: 700; text-decoration: none; padding: 13px 30px; border-radius: 8px; box-shadow: 0 4px 14px rgba(245, 166, 35, 0.3);">
                                            Confirmar Casilla con 1 Clic
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <p style="font-size: 12.5px; color: #8a8d9a; text-align: center; margin: 0; line-height: 1.5;">
                                Una vez confirmada, tu cuenta quedará vinculada para recibir las alertas automáticas matutinas antes de cada quiebre.
                            </p>
                        </td>
                    </tr>

                    <!-- Pie de Correo -->
                    <tr>
                        <td style="background-color: #11141a; padding: 20px 28px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 12px; color: #8a8d9a; text-align: center; line-height: 1.6;">
                            <table cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto 6px auto;">
                                <tr>
                                    <td valign="middle" style="vertical-align: middle; padding-right: 8px; line-height: 0;">
                                        <img src="{URL_ICON_CAJITA}" width="16" height="16" alt="" style="display: block; width: 16px; height: 16px; opacity: 0.8;" />
                                    </td>
                                    <td valign="middle" style="vertical-align: middle; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; font-size: 12.5px; font-weight: 800; letter-spacing: -0.2px; color: #e8e9ed;">
                                        EnvioBot <span style="color: #f5a623;">Full</span>
                                    </td>
                                </tr>
                            </table>
                            Control de Stock y Reposición en Mercado Envíos Full<br>
                            <a href="{app_url}" style="color: #f5a623; text-decoration: none; font-weight: 600;">enviobot.com.ar/full</a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    # Usa cuenta de bienvenida: hola@enviobot.com.ar
    return enviar_email(destinatario, asunto, texto_plano, html, smtp_cfg=get_welcome_smtp_config())


def enviar_email_prueba(destinatario: str, nombre_usuario: str = "Usuario", tipo: str = "welcome") -> dict:
    """
    Envía un correo de verificación para testear credenciales SMTP (welcome o alertafull)
    con el icono y tipografía oficial correspondiente.
    """
    es_full = (tipo == "alertafull")
    cfg = get_alert_smtp_config() if es_full else get_welcome_smtp_config()
    asunto = f"EnvioBot: Verificación de Correo Saliente ({cfg['user']})"
    items_demo = [
        {"sku": "DEMO-001", "title": "Producto de Prueba para Verificación de Alertas", "current_stock_full": 15, "days_left": 4.5, "stockout_date": datetime.now().strftime("%d/%m"), "suggested_restock_units": 40}
    ]
    titulo = f"Casilla de correo verificada ({cfg['user']})"
    subtitulo = f"Confirmación de que la casilla {cfg['user']} puede despachar correos a través de {cfg['host']} con la identidad oficial."

    texto_plano = f"EnvioBot - Prueba de Correo Saliente\nHola {nombre_usuario}, tu casilla {destinatario} está correctamente vinculada.\n"
    html = _generar_plantilla_html(titulo, subtitulo, nombre_usuario, "Mercado Envíos Full", items_demo, "ok", es_full=es_full)

    return enviar_email(destinatario, asunto, texto_plano, html, smtp_cfg=cfg)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        try:
            target = sys.argv[sys.argv.index("--test") + 1]
            tipo = "welcome"
            if "--tipo" in sys.argv:
                tipo = sys.argv[sys.argv.index("--tipo") + 1]
            print(f"Probando envío SMTP ({tipo}) a {target}...")
            res = enviar_email_prueba(target, "Administrador", tipo=tipo)
            print("Resultado:", res)
        except IndexError:
            print("Uso: python email_service.py --test <tu_email> [--tipo welcome|alertafull]")
    else:
        print("Módulo email_service.py cargado. Ejecutar con --test <email> para verificar.")
