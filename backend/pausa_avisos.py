"""Pausa general de avisos (decisión de Guillermo, 2026-10-17).

Hasta definir cuáles avisos mandar, no sale ninguno: ni el WhatsApp ni el mail de stock (alerts_engine),
ni el aviso de una hora antes del límite de la colecta. Solo pasan los tipos de TIPOS_PERMITIDOS.

Quedan fuera de la pausa porque los pide una persona en ese momento y no son avisos automáticos:
verificar un número de WhatsApp, invitar a alguien, el mensaje de prueba y los mails de alta de cuenta.

Para reanudar todos los avisos: poner ENVIOBOT_AVISOS=activos en el .env del servidor y reiniciar.
Sin esa variable (o con cualquier otro valor) los avisos están pausados.
"""
import os

# Avisos que pasan aunque la pausa esté puesta. El de cambio de tasa de venta se está armando aparte:
# quien lo envíe tiene que preguntar con puede_enviar("cambio_tasa_venta").
TIPOS_PERMITIDOS = frozenset({"cambio_tasa_venta", "colecta_mail"})

ALERTA_STOCK = "alerta_stock"        # WhatsApp y mail de stock crítico, preventivo, de colecta y resumen diario
AVISO_LIMITE_COLECTA = "colecta_limite"
MAIL_COLECTA = "colecta_mail"          # reenvío por WhatsApp de los mails de ML sobre la colecta (pedido por Guillermo, 2026-10-19)


def avisos_pausados():
    return os.getenv("ENVIOBOT_AVISOS", "pausados").strip().lower() != "activos"


def puede_enviar(tipo):
    return (not avisos_pausados()) or tipo in TIPOS_PERMITIDOS


def codigo_email_activo():
    """Los mails con el código de vinculación de correo están apagados por ahora (decisión de Guillermo, 2026-10-19):
    llegaban de a decenas y no se entendían. Para volver a mandarlos: ENVIOBOT_CODIGO_EMAIL=activo en el .env del servidor."""
    return os.getenv("ENVIOBOT_CODIGO_EMAIL", "apagado").strip().lower() == "activo"
