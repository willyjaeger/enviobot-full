#!/usr/bin/env python3
"""
email_service.py - Servicio Profesional de Correo Saliente (SMTP DonWeb)
Envía alertas transaccionales por email con plantillas HTML responsivas
y diseño corporativo de EnvioBot Full.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("email_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

# Configuración SMTP DonWeb
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.donweb.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "alertas@enviobot.com.ar")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_SENDER_EMAIL = os.getenv("ALERT_SENDER_EMAIL", "alertas@enviobot.com.ar")
SENDER_DISPLAY_NAME = os.getenv("SENDER_DISPLAY_NAME", "EnvioBot Full")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "soporte@enviobot.com.ar")
APP_URL = os.getenv("APP_URL", "https://enviobot.com.ar/full")

# Modo simulación si falta contraseña de SMTP
EMAIL_SIMULATION_MODE = os.getenv("EMAIL_SIMULATION_MODE", "").lower() in ("true", "1", "yes") or not SMTP_PASSWORD


def _generar_plantilla_html(titulo_banner: str, subtitulo: str, nombre_usuario: str, deposito_nombre: str, items: list, nivel: str) -> str:
    """Genera una plantilla HTML moderna, responsiva y profesional con la paleta de EnvioBot Full."""
    color_banner = "#f5a623" if nivel == "warning" else ("#ff5252" if nivel == "critical" else "#4caf50")
    etiqueta_nivel = "PEDIR COLECTA HOY" if nivel == "warning" else ("RIESGO CRÍTICO" if nivel == "critical" else "AVISO PREVENTIVO")

    filas_html = ""
    for it in items[:12]:
        sku_str = f"<span style='color: #8a8d9a; font-size: 11px;'>SKU: {it.get('sku')}</span><br>" if it.get("sku") else ""
        dias = it.get('days_left', 0)
        sug = it.get('suggested_restock_units', 0)
        quiebre = it.get('stockout_date') or "Pronto"
        stock_act = it.get('current_stock_full', 0)

        filas_html += f"""
        <tr style="border-bottom: 1px solid #2b303c;">
            <td style="padding: 10px 12px; font-size: 13px; color: #ffffff;">
                {sku_str}<strong>{it.get('title', '')[:50]}</strong>
            </td>
            <td style="padding: 10px 12px; font-size: 13px; text-align: center; color: #cfd3dc;">
                {stock_act} un.
            </td>
            <td style="padding: 10px 12px; font-size: 13px; text-align: center; color: #cfd3dc;">
                {dias} d
            </td>
            <td style="padding: 10px 12px; font-size: 13px; text-align: center; font-weight: bold; color: {color_banner};">
                {quiebre}
            </td>
            <td style="padding: 10px 12px; font-size: 14px; text-align: center; font-weight: bold; color: #f5a623;">
                {sug} un.
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{titulo_banner}</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #0c0e12; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e1e4ea;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #0c0e12; padding: 25px 10px;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%; background-color: #171b22; border: 1px solid #2b303c; border-radius: 8px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                        <!-- Encabezado con Identidad de Marca -->
                        <tr>
                            <td style="background-color: #11141a; padding: 20px 28px; border-bottom: 2px solid {color_banner};">
                                <table width="100%">
                                    <tr>
                                        <td>
                                            <span style="font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">
                                                EnvioBot <span style="color: #f5a623;">Full</span>
                                            </span>
                                        </td>
                                        <td align="right">
                                            <span style="background-color: rgba(245, 166, 35, 0.15); color: {color_banner}; border: 1px solid {color_banner}; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; text-transform: uppercase;">
                                                {etiqueta_nivel}
                                            </span>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>

                        <!-- Cuerpo Principal -->
                        <tr>
                            <td style="padding: 26px 28px;">
                                <h2 style="margin: 0 0 8px 0; font-size: 18px; color: #ffffff; font-weight: 700;">
                                    {titulo_banner}
                                </h2>
                                <p style="margin: 0 0 18px 0; font-size: 13.5px; color: #8a8d9a; line-height: 1.5;">
                                    Hola <strong>{nombre_usuario}</strong>, este es tu reporte matutino de stock para el depósito <strong>{deposito_nombre}</strong>.<br>
                                    {subtitulo}
                                </p>

                                <!-- Tabla de Artículos -->
                                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; background-color: #12151c; border-radius: 6px; overflow: hidden; border: 1px solid #2b303c; margin-bottom: 24px;">
                                    <thead>
                                        <tr style="background-color: #1c212b; border-bottom: 1px solid #2b303c;">
                                            <th style="padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: #8a8d9a; text-align: left;">Publicación / SKU</th>
                                            <th style="padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: #8a8d9a; text-align: center;">Stock</th>
                                            <th style="padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: #8a8d9a; text-align: center;">Días</th>
                                            <th style="padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: #8a8d9a; text-align: center;">Quiebra</th>
                                            <th style="padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: #8a8d9a; text-align: center;">A Mandar</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filas_html}
                                    </tbody>
                                </table>

                                <!-- Botón de Acción Principal -->
                                <table width="100%" cellpadding="0" cellspacing="0">
                                    <tr>
                                        <td align="center" style="padding: 10px 0 16px 0;">
                                            <a href="{APP_URL}" target="_blank" style="display: inline-block; background-color: #f5a623; color: #111111; font-size: 14px; font-weight: bold; text-decoration: none; padding: 12px 28px; border-radius: 6px; box-shadow: 0 4px 14px rgba(245, 166, 35, 0.3);">
                                                Abrir Remito y Armar Colecta en MeLi
                                            </a>
                                        </td>
                                    </tr>
                                </table>

                                <p style="font-size: 12px; color: #6b7280; text-align: center; margin: 12px 0 0 0;">
                                    Si solicitás el turno hoy en MercadoLibre, el camión llega a destino antes de agotar el inventario.
                                </p>
                            </td>
                        </tr>

                        <!-- Pie de Correo -->
                        <tr>
                            <td style="background-color: #11141a; padding: 18px 28px; border-top: 1px solid #2b303c; font-size: 11.5px; color: #6b7280; text-align: center; line-height: 1.5;">
                                EnvioBot Full · Monitoreo y Pronóstico de Stock en Mercado Envíos Full<br>
                                Servidor de Notificaciones DonWeb · <a href="{APP_URL}" style="color: #f5a623; text-decoration: none;">enviobot.com.ar/full</a>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    return html


def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str, cuerpo_html: str = None) -> dict:
    """
    Función de bajo nivel para despachar correo a través de DonWeb SMTP.
    """
    if not destinatario:
        return {"ok": False, "error": "Destinatario vacío"}

    # Modo simulación si no hay credenciales SMTP cargadas
    if EMAIL_SIMULATION_MODE:
        logger.info(f"[SIMULACIÓN EMAIL DONWEB]\nDe: {ALERT_SENDER_EMAIL}\nPara: {destinatario}\nAsunto: {asunto}\n{cuerpo_texto[:200]}...")
        return {
            "ok": True,
            "simulated": True,
            "to": destinatario,
            "subject": asunto,
            "message": "Email procesado en modo simulación (configurar SMTP_PASSWORD en .env para salida real)."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = f"{SENDER_DISPLAY_NAME} <{ALERT_SENDER_EMAIL}>"
        msg["To"] = destinatario
        msg["Reply-To"] = REPLY_TO_EMAIL
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="enviobot.com.ar")
        msg["X-Mailer"] = "EnvioBot Full Alerts Engine"

        msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        if cuerpo_html:
            msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=14)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=14)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(ALERT_SENDER_EMAIL, [destinatario], msg.as_string())
        server.quit()

        logger.info(f"[SMTP DonWeb] Correo enviado exitosamente a {destinatario}")
        return {"ok": True, "to": destinatario, "subject": asunto}
    except Exception as e:
        logger.error(f"[SMTP DonWeb Error] No se pudo enviar a {destinatario}: {e}")
        return {"ok": False, "error": str(e), "to": destinatario}


def enviar_alerta_stock_email(destinatario: str, nombre_usuario: str, deposito_nombre: str, items: list, nivel: str) -> dict:
    """Envía la alerta estructurada con la plantilla HTML correspondiente."""
    if nivel == "critical":
        asunto = f"🚨 EnvioBot Full: Alerta Crítica de Quiebre de Stock ({deposito_nombre})"
        titulo = "Riesgo Inminente de Quiebre de Stock"
        subtitulo = "Las siguientes publicaciones se quedarán sin inventario antes de que arribe un flete habitual. Se requiere despacho urgente."
    elif nivel == "warning":
        asunto = f"🚛 EnvioBot Full: Pedir Colecta Hoy en MercadoLibre ({deposito_nombre})"
        titulo = "Fecha Límite de Colecta Alcanzada"
        subtitulo = "Hoy es la fecha óptima para pedir turno en MercadoLibre. Si solicitás el turno hoy, el flete llegará antes del agotamiento."
    else:
        asunto = f"📦 EnvioBot Full: Planificación Preventiva de Colecta ({deposito_nombre})"
        titulo = "Aviso Preventivo de Producción"
        subtitulo = "Tus ventas registran buen ritmo. En los próximos días alcanzarás la fecha límite de reposición para estos artículos."

    # Texto plano fallback
    texto_plano = f"EnvioBot Full - {titulo}\nHola {nombre_usuario}, depósito: {deposito_nombre}\n\n"
    for it in items[:10]:
        texto_plano += f"• [{it.get('sku') or 'Sin SKU'}] {it.get('title')}: Stock {it.get('current_stock_full', 0)} un. - Mandar: {it.get('suggested_restock_units', 0)} un. (Quiebra: {it.get('stockout_date')})\n"
    texto_plano += f"\nAccedé a tu panel para descargar la lista o imprimir el remito: {APP_URL}\n"

    # HTML enriquecido
    html = _generar_plantilla_html(titulo, subtitulo, nombre_usuario, deposito_nombre, items, nivel)

    return enviar_email(destinatario, asunto, texto_plano, html)


def enviar_email_prueba(destinatario: str, nombre_usuario: str = "Usuario") -> dict:
    """Envía un correo de verificación para testear credenciales SMTP de DonWeb."""
    asunto = "✓ EnvioBot Full: Verificación de Correo Saliente Exitosa"
    items_demo = [
        {"sku": "DEMO-001", "title": "Producto de Prueba para Verificación de Alertas", "current_stock_full": 15, "days_left": 4.5, "stockout_date": datetime.now().strftime("%d/%m"), "suggested_restock_units": 40}
    ]
    titulo = "Tu correo de alertas está correctamente configurado"
    subtitulo = "Esta es una confirmación de que el servidor SMTP de DonWeb puede enviar reportes matutinos a esta casilla."

    texto_plano = f"EnvioBot Full - Prueba de Correo Saliente\nHola {nombre_usuario}, tu casilla {destinatario} está correctamente vinculada.\n"
    html = _generar_plantilla_html(titulo, subtitulo, nombre_usuario, "Mercado Envíos Full (Bs As)", items_demo, "ok")

    return enviar_email(destinatario, asunto, texto_plano, html)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        try:
            target = sys.argv[sys.argv.index("--test") + 1]
            print(f"Probando envío SMTP a {target}...")
            res = enviar_email_prueba(target, "Administrador")
            print("Resultado:", res)
        except IndexError:
            print("Uso: python email_service.py --test <tu_email>")
    else:
        print("Módulo email_service.py cargado. Ejecutar con --test <email> para verificar.")
