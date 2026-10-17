#!/usr/bin/env python3
"""Aviso de que se cierra la posibilidad de modificar la colecta.

Una hora antes del límite (día hábil anterior al retiro, 9:40 de Buenos Aires) manda un mensaje
por WhatsApp y mail a quienes ya reciben las alertas de Full. Cada colecta se avisa UNA vez.

Está pensado para correr cada 10 minutos desde cron (el worker corre cada 4 horas y no alcanza):
    */10 * * * * <venv>/bin/python <app>/backend/aviso_limite_colecta.py >> /var/log/enviobot_full.log 2>&1
Cargar esa línea en el servidor es un cambio aparte, con OK de Guillermo.

No toca la base: usa las tablas que ya existen (alert_logs para no repetir el aviso).
"""
import logging
from datetime import datetime

import alerts_engine
import esquema
import proyeccion
from email_service import enviar_email
from horario_whatsapp import whatsapp_permitido
from whatsapp_service import enviar_lote_con_demora, obtener_configuracion_whatsapp

logger = logging.getLogger("aviso_limite_colecta")

TIPO_ALERTA = "colecta_limite"
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _fecha_larga(d):
    return f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def texto_aviso(fecha_retiro, limite, segundos_restantes, codigo=None, app_url=""):
    """Mensaje para WhatsApp (el mail usa el mismo texto)."""
    minutos = max(1, int(round(segundos_restantes / 60.0)))
    if minutos >= 50:
        resto = "Te queda cerca de una hora"
    else:
        resto = f"Te quedan {minutos} minutos"
    cod = f" ({codigo})" if codigo else ""
    return (
        f"{resto} antes de que cierre la posibilidad de modificar la colecta del {_fecha_larga(fecha_retiro)}{cod}. "
        f"El límite es el {_fecha_larga(limite)} a las {limite.hour:02d}:{limite.minute:02d}. "
        f"Si querés cambiar unidades o productos, hacelo ahora{': ' + app_url if app_url else '.'}"
    )


def _destinatarios(conn, user_id, settings):
    with conn.cursor() as cur:
        cur.execute("SELECT phone FROM alert_recipients WHERE user_id=%s AND is_active=1", (user_id,))
        telefonos = [r["phone"] for r in cur.fetchall() if r.get("phone")]
    if not telefonos and settings.get("whatsapp_phone"):
        telefonos = [settings["whatsapp_phone"]]
    return telefonos


def procesar_usuario(conn, user_id, ahora=None):
    """Avisa de las colectas de este usuario que están a una hora o menos del límite."""
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    res = {"user_id": user_id, "avisos": 0}
    with conn.cursor() as cur:
        cur.execute("SELECT id, email FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user:
            return res
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone() or {"notify_email": True, "notify_whatsapp": True, "alert_email": user.get("email")}
        hora = None
        if esquema.tiene_columna(cur, "warehouses", "edit_cutoff_time"):
            cur.execute("SELECT edit_cutoff_time FROM warehouses WHERE user_id=%s AND is_active=1 ORDER BY id ASC LIMIT 1", (user_id,))
            fila = cur.fetchone()
            hora = fila.get("edit_cutoff_time") if fila else None
        cur.execute("""
            SELECT shipment_code, pickup_date FROM inbound_shipments
            WHERE user_id=%s AND status='scheduled' AND pickup_date >= %s
        """, (user_id, ahora.date()))
        colectas = cur.fetchall()

    for c in colectas:
        retiro = c["pickup_date"]
        cuenta = proyeccion.cuenta_regresiva(retiro, ahora, hora)
        if not (cuenta["abierta"] and cuenta["segundos_restantes"] <= proyeccion.MINUTOS_AVISO_LIMITE * 60):
            continue
        clave = f"{c.get('shipment_code') or 'colecta'}:{retiro.isoformat()}"
        # Un registro por canal: si el WhatsApp tiene que esperar al horario, el mail no lo bloquea.
        ya_wa = alerts_engine.ya_se_envio_alerta_hoy(conn, user_id, TIPO_ALERTA, clave + ":wa", horas_cooldown=72)
        ya_mail = alerts_engine.ya_se_envio_alerta_hoy(conn, user_id, TIPO_ALERTA, clave + ":mail", horas_cooldown=72)
        if ya_wa and ya_mail:
            continue  # ya se avisó de esta colecta
        limite = proyeccion.limite_edicion(retiro, hora)
        texto = texto_aviso(retiro, limite, cuenta["segundos_restantes"], c.get("shipment_code"), alerts_engine.APP_URL)

        enviado = False
        telefonos = _destinatarios(conn, user_id, settings)
        if (not ya_wa and telefonos and settings.get("notify_whatsapp", True)
                and whatsapp_permitido(ahora) and obtener_configuracion_whatsapp().get("enabled", True)):
            enviar_lote_con_demora(telefonos, texto)
            alerts_engine.registrar_alerta_en_log(conn, user_id, clave + ":wa", TIPO_ALERTA, texto, channel="whatsapp")
            enviado = True
        email_dest = settings.get("alert_email") or user.get("email")
        if not ya_mail and email_dest and settings.get("notify_email", True):
            r = enviar_email(email_dest, "Se cierra el cambio de tu colecta de Full", texto)
            if r.get("ok"):
                alerts_engine.registrar_alerta_en_log(conn, user_id, clave + ":mail", TIPO_ALERTA, texto, channel="email")
                enviado = True
        if enviado:
            res["avisos"] += 1
            logger.info(f"[Aviso límite] user_id={user_id} colecta {clave}: aviso enviado")
    return res


def ejecutar_global(ahora=None):
    conn = alerts_engine.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT s.user_id FROM inbound_shipments s
                JOIN users u ON u.id = s.user_id
                WHERE s.status='scheduled' AND s.pickup_date >= %s AND u.active=1 AND u.is_blocked=0
            """, (ahora.date() if ahora else datetime.now(proyeccion.HORA_BA).date(),))
            usuarios = [f["user_id"] for f in cur.fetchall()]
        total = 0
        for uid in usuarios:
            try:
                total += procesar_usuario(conn, uid, ahora)["avisos"]
            except Exception as e:  # un usuario con problemas no frena a los demás
                logger.error(f"[Aviso límite] user_id={uid}: {e}")
        return total
    finally:
        conn.close()


if __name__ == "__main__":
    ejecutar_global()
