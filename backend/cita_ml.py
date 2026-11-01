"""Cuánto permite la cita de una colecta de Mercado Libre.

Mercado Libre muestra en la pantalla de editar el envío "Tu cita permite entre X y Y u.". No está en la API ni en el
PDF. Con dos colectas reales (2026-11-01) el rango es el 30 % arriba y abajo de lo que se DECLARÓ al agendar, no del
total actual: 645 u. → 451 a 839, y 755 u. → 528 a 982 (el envío siguió mostrando 528 a 982 después de subirlo a 793 u.).
Es una deducción con dos datos, no una regla documentada: por eso el usuario puede corregirlo a mano (cita_min y
cita_max) y la pantalla lo marca como calculado.

Se guarda en inbound_shipments (migración 009): total_declarado (una sola vez, no se renueva con cada PDF), y cita_min /
cita_max cuando el usuario los carga a mano. Sin las columnas la función se apaga sola y la pantalla estima con lo cargado.
"""
import esquema

PORCENTAJE = 30


def rango(declarado):
    """(mínimo, máximo) de unidades que permite la cita, o None si no hay total declarado. Mínimo hacia abajo, máximo hacia arriba."""
    try:
        d = int(declarado)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    return (d * (100 - PORCENTAJE)) // 100, -((-d * (100 + PORCENTAJE)) // 100)


def estado(total, minimo, maximo):
    """'ok', 'bajo' o 'alto', con las unidades que faltan o sobran."""
    total = int(total or 0)
    if total < minimo:
        return {"estado": "bajo", "faltan": minimo - total, "sobran": 0}
    if total > maximo:
        return {"estado": "alto", "faltan": 0, "sobran": total - maximo}
    return {"estado": "ok", "faltan": 0, "sobran": 0}


def resumen(envio):
    """Lo que ve el panel de una colecta (fila de inbound_shipments), o None si no hay con qué calcular."""
    declarado = envio.get("total_declarado")
    cmin, cmax = envio.get("cita_min"), envio.get("cita_max")
    if cmin is not None and cmax is not None:
        return {"min": int(cmin), "max": int(cmax), "declarado": declarado, "manual": True}
    r = rango(declarado)
    if r:
        return {"min": r[0], "max": r[1], "declarado": int(declarado), "manual": False}
    return None


def fijar_declarado(cur, shipment_id, account_id, total):
    """Guarda el total declarado una sola vez (si ya hay uno, no lo toca). Sin la columna no hace nada."""
    if not total or not esquema.tiene_columna(cur, "inbound_shipments", "total_declarado"):
        return
    cur.execute("UPDATE inbound_shipments SET total_declarado=%s WHERE id=%s AND user_id=%s AND total_declarado IS NULL",
                (int(total), shipment_id, account_id))


def leer_manual(datos):
    """Rango cargado a mano en el PUT. Devuelve ('sin_cambio',), ('borrar',) o ('fijar', min, max); lanza ValueError si no sirve."""
    if "cita_min" not in datos and "cita_max" not in datos:
        return ("sin_cambio",)
    cmin, cmax = datos.get("cita_min"), datos.get("cita_max")
    if cmin is None and cmax is None:
        return ("borrar",)
    try:
        cmin, cmax = int(cmin), int(cmax)
    except (TypeError, ValueError):
        raise ValueError("El rango de la cita tiene que ser dos números enteros.")
    if cmin < 0 or cmax < cmin or cmax > 1000000:
        raise ValueError("El rango de la cita no es válido: el mínimo no puede ser mayor que el máximo.")
    return ("fijar", cmin, cmax)


def guardar_manual(cur, shipment_id, account_id, orden):
    if orden[0] == "sin_cambio" or not esquema.tiene_columna(cur, "inbound_shipments", "cita_min"):
        return
    cmin, cmax = (orden[1], orden[2]) if orden[0] == "fijar" else (None, None)
    cur.execute("UPDATE inbound_shipments SET cita_min=%s, cita_max=%s WHERE id=%s AND user_id=%s",
                (cmin, cmax, shipment_id, account_id))
