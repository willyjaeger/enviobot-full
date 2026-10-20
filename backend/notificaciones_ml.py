"""Receptor de las notificaciones de Mercado Libre sobre el stock de Full (tema fbm_stock_operations).

Formato según la documentación de ML (https://developers.mercadolibre.com.ar/es_ar/productos-recibe-notificaciones):
    {"resource": "/stock/fulfillment/operations/9876", "user_id": 1234, "topic": "fbm_stock_operations",
     "application_id": 12341234, "attempts": 1, "sent": "...", "received": "..."}
ML pide responder HTTP 200 en menos de 500 ms (si no, desactiva el tema), así que la ruta contesta enseguida y
la consulta del detalle (GET al recurso, con el token del vendedor) se hace aparte.

Por ahora solo REGISTRA en el log qué operación llegó (tipo, inventario, fecha): el primer aviso real sirve para
confirmar el formato de verdad antes de actuar sobre él. Un ingreso de colecta es el tipo inbound_reception.
Nada de esto se activa hasta que se cargue la URL y se tilde el tema en el devcenter de ML.
"""
import logging
import re

logger = logging.getLogger("notificaciones_ml")

TEMA = "fbm_stock_operations"
_RE_RECURSO = re.compile(r"^/stock/fulfillment/operations/\d+$")


def validar(payload, application_id, ml_user_ids):
    """(ok, motivo). Solo se acepta nuestro tema, de nuestra aplicación y de un vendedor conocido.

    El recurso tiene que tener la forma exacta de una operación de stock: nunca se consulta una ruta arbitraria."""
    if not isinstance(payload, dict):
        return False, "formato"
    if payload.get("topic") != TEMA:
        return False, "tema"
    if str(payload.get("application_id")) != str(application_id):
        return False, "aplicacion"
    if str(payload.get("user_id")) not in {str(u) for u in ml_user_ids}:
        return False, "vendedor"
    if not _RE_RECURSO.match(str(payload.get("resource") or "")):
        return False, "recurso"
    return True, ""


def procesar(payload, obtener_token, consultar):
    """Consulta el detalle de la operación y lo registra. `obtener_token(user_id)` y `consultar(ruta, token)`
    (devuelve (estado_http, json)) se pueden reemplazar en los tests. No tira excepciones: es un hilo suelto."""
    try:
        token = obtener_token(payload["user_id"])
        if not token:
            logger.warning("[ML stock] Sin token para el vendedor %s; no se pudo consultar %s", payload.get("user_id"), payload.get("resource"))
            return None
        estado, op = consultar(payload["resource"], token)
        if estado != 200 or not isinstance(op, dict):
            logger.warning("[ML stock] %s respondió HTTP %s", payload["resource"], estado)
            return None
        logger.info("[ML stock] Operación %s: tipo=%s inventario=%s fecha=%s",
                    op.get("id"), op.get("type"), op.get("inventory_id"), op.get("date_created"))
        return op
    except Exception:
        logger.exception("[ML stock] Error procesando la notificación")
        return None
