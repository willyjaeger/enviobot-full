"""Proyección de stock a la fecha de ingreso de una colecta.

Lo que pase en Full entre hoy y el ingreso no se puede cambiar; lo que sí se puede es cuánto
mandar. Por eso miramos desde el día del ingreso hacia adelante: lo que se vende durante la
espera se descuenta del stock de hoy (sin bajar de 0) y recién ahí se suma lo que entra.

Funciones puras, sin base ni ML, para poder probarlas solas (ver test_proyeccion.py).
"""
from datetime import datetime, timedelta, timezone

# Buenos Aires no tiene horario de verano: UTC-3 todo el año.
HORA_BA = timezone(timedelta(hours=-3))
# Hasta el día anterior a esta hora se puede modificar la colecta (dato de Guillermo, 2026-10-16).
# Por ahora fijo; cuando se pase a un valor por depósito hace falta un cambio de base con OK.
LIMITE_EDICION_HORA = 9
LIMITE_EDICION_MINUTO = 44
# El aviso de "subió la venta" solo salta si lo comprometido queda bastante corto.
TOLERANCIA_AVISO = 0.8


def dias_hasta_ingreso(estado, hoy, fecha_llegada=None, preparacion=0, flete=0):
    """Días que faltan para que la mercadería esté vendible en Full.

    estado: 'scheduled' (en preparación), 'in_transit', 'in_reception' o None (sin colecta).
    Con fecha de llegada cargada se usa esa; si no, preparación + flete.
    """
    if estado == 'in_reception':
        return 1  # ya está en el muelle, pero ML tarda en dejarla vendible
    if estado == 'in_transit':
        return max(0, flete)
    if estado == 'scheduled' and fecha_llegada is not None:
        return max(0, (fecha_llegada - hoy).days)
    return max(0, preparacion + flete)


def stock_al_ingreso(stock_hoy, vpd, dias):
    """Lo que queda en Full el día que entra la colecta. Nunca negativo."""
    return max(0.0, stock_hoy - vpd * dias)


def cobertura_post_colecta(stock_hoy, vpd, dias, unidades_entrantes):
    """Días de venta que cubre el stock desde el ingreso. None si no hay ventas."""
    if vpd <= 0:
        return None
    return round((stock_al_ingreso(stock_hoy, vpd, dias) + unidades_entrantes) / vpd, 1)


def sugerido_al_ingreso(stock_hoy, vpd, dias, unidades_entrantes, objetivo_dias):
    """Unidades a mandar para llegar al objetivo contando desde el ingreso."""
    if vpd <= 0:
        return 0
    falta = objetivo_dias * vpd - stock_al_ingreso(stock_hoy, vpd, dias) - unidades_entrantes
    return max(0, int(round(falta)))


def aviso_ajuste(stock_hoy, vpd, dias, unidades_colecta, objetivo_dias):
    """Si lo comprometido en la colecta quedó corto, devuelve cuántas unidades convendría
    preparar; si está bien (o no hay colecta), None."""
    if unidades_colecta <= 0 or vpd <= 0:
        return None
    cobertura = cobertura_post_colecta(stock_hoy, vpd, dias, unidades_colecta)
    if cobertura >= objetivo_dias * TOLERANCIA_AVISO:
        return None
    ideal = sugerido_al_ingreso(stock_hoy, vpd, dias, 0, objetivo_dias)
    return ideal if ideal > unidades_colecta else None


# Sobrestock: cobertura (con lo que viene en camino) por encima de este múltiplo del objetivo.
# Es una regla nuestra, no de MercadoLibre: con objetivo de 30 días avisa a partir de los 45.
FACTOR_SOBRESTOCK = 1.5


def umbral_sobrestock(objetivo_dias, factor=None):
    """Días de cobertura a partir de los cuales hay exceso. El factor lo puede cambiar el
    cliente; si falta o no sirve, se usa FACTOR_SOBRESTOCK."""
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        factor = FACTOR_SOBRESTOCK
    if factor <= 1:
        factor = FACTOR_SOBRESTOCK
    return objetivo_dias * factor


def es_sobrestock(stock_hoy, unidades_entrantes, vpd, objetivo_dias, factor=None):
    """True si lo que hay (más lo que viene) alcanza para bastante más que el objetivo.
    Sin ventas no se marca: un producto nuevo o parado no es lo mismo que un exceso."""
    if vpd <= 0:
        return False
    return (stock_hoy + unidades_entrantes) / vpd > umbral_sobrestock(objetivo_dias, factor)


def parsear_hora(valor):
    """'09:40', '9:40:00' o un timedelta/time de la base -> (hora, minuto). None si no sirve."""
    if valor is None:
        return None
    if isinstance(valor, timedelta):  # PyMySQL devuelve TIME como timedelta
        minutos = int(valor.total_seconds() // 60)
        return (minutos // 60) % 24, minutos % 60
    if hasattr(valor, 'hour') and hasattr(valor, 'minute'):
        return valor.hour, valor.minute
    try:
        h, m = str(valor).strip().split(':')[:2]
        h, m = int(h), int(m)
    except ValueError:
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def dia_habil_anterior(fecha):
    """El día hábil (lunes a viernes) anterior a la fecha. Una colecta del lunes se cierra el
    viernes. No contempla feriados: si hay uno en el medio, el límite real es antes."""
    dia = fecha - timedelta(days=1)
    while dia.weekday() >= 5:  # 5 = sábado, 6 = domingo
        dia -= timedelta(days=1)
    return dia


def limite_edicion(fecha_retiro, hora=None):
    """Momento hasta el que se puede modificar la colecta: el día hábil anterior al retiro, a la
    hora del depósito (por defecto 9:44) de Buenos Aires. Devuelve un datetime con zona horaria."""
    h, m = parsear_hora(hora) or (LIMITE_EDICION_HORA, LIMITE_EDICION_MINUTO)
    dia = dia_habil_anterior(fecha_retiro)
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=HORA_BA)


def cuenta_regresiva(fecha_retiro, ahora=None, hora=None):
    """Datos para el cartel de la colecta. 'abierta' es False si ya pasó el límite."""
    ahora = ahora or datetime.now(HORA_BA)
    limite = limite_edicion(fecha_retiro, hora)
    segundos = int((limite - ahora).total_seconds())
    return {
        "fecha_retiro": fecha_retiro.isoformat(),
        "limite_edicion": limite.isoformat(),
        "segundos_restantes": max(0, segundos),
        "abierta": segundos > 0,
    }


def bloqueada_por_ml(codigo, fecha_retiro, ahora=None, hora=None):
    """Una colecta cargada desde Mercado Libre (código ML-<número>) ya está bloqueada allá pasado el límite:
    EnvioBot tampoco deja cambiarla, para no mostrar cantidades distintas de las que ML va a recibir."""
    if not str(codigo or '').startswith('ML-') or not fecha_retiro:
        return False
    return not cuenta_regresiva(fecha_retiro, ahora=ahora, hora=hora)["abierta"]


def armar_colecta(fila, productos, hora=None, ahora=None):
    """Una colecta lista para mostrar: estado, fechas (retiro, límite de edición, ingreso a Full) y sus productos.
    `fila` es el registro de inbound_shipments; `productos`, sus renglones (title, sku, units_to_send)."""
    retiro = fila["pickup_date"]
    estado = fila.get("status") or "scheduled"
    base = cuenta_regresiva(retiro, ahora=ahora, hora=hora)
    ingreso = fila.get("estimated_arrival_date")
    if not ingreso:
        ingreso = retiro + timedelta(days=int(fila.get("transit_days") or 3))
    unidades = sum(int(p.get("units_to_send") or 0) for p in productos)
    return {
        "id": fila.get("id"),
        "codigo": fila.get("shipment_code"),
        "estado": estado,
        "fecha_retiro": retiro.isoformat(),
        "limite_edicion": base["limite_edicion"],
        "abierta": bool(base["abierta"]) and estado == "scheduled",
        "fecha_ingreso": ingreso.isoformat(),
        "de_ml": str(fila.get("shipment_code") or "").startswith("ML-"),
        "total_unidades": unidades,
        "productos": [{"titulo": p.get("title") or "", "sku": p.get("sku") or "",
                       "unidades": int(p.get("units_to_send") or 0)} for p in productos],
    }


def validar_nuevo_retiro(codigo, retiro_actual, nuevo, ahora=None, hora=None):
    """Texto del problema si no se puede mover el retiro de esta colecta a `nuevo`; None si se puede."""
    ahora = ahora or datetime.now(HORA_BA)
    if bloqueada_por_ml(codigo, retiro_actual, ahora=ahora, hora=hora):
        return "Mercado Libre ya cerró esta colecta (el límite para cambiarla pasó), así que no se puede mover."
    if nuevo < ahora.date():
        return "La fecha de retiro no puede ser anterior a hoy."
    if str(codigo or '').startswith('ML-') and not cuenta_regresiva(nuevo, ahora=ahora, hora=hora)["abierta"]:
        return "Para ese día ya pasó el límite de Mercado Libre: no llegás a cambiar el turno a tiempo."
    return None


# ── Velocidad de venta corregida por días sin stock ─────────────────────────────────────
MIN_DIAS_ACTIVOS = 3  # con menos días con stock que esto, el promedio sería puro ruido: no se corrige


def _por_dia(ventas, dias_ventana, dias_sin_stock):
    activos = dias_ventana - max(0, dias_sin_stock or 0)
    if activos < MIN_DIAS_ACTIVOS:
        activos = dias_ventana
    return ventas / float(activos)


def vpd_ponderado(v7, v15, v30, sin7=0, sin15=0, sin30=0):
    """Ventas por día: 50% de 7 días, 35% de 15 y 15% de 30. Cada ventana se divide por los días
    en que HABÍA stock, no por todos: si un producto estuvo 10 días quebrado, dividir por 30 lo
    subestima y se manda de menos. Sin días sin stock da exactamente la fórmula de siempre."""
    return round((0.50 * _por_dia(v7, 7, sin7)) + (0.35 * _por_dia(v15, 15, sin15)) + (0.15 * _por_dia(v30, 30, sin30)), 2)


MINUTOS_AVISO_LIMITE = 60  # se avisa cuando falta una hora o menos para el límite


def en_ventana_de_aviso(fecha_retiro, ahora=None, hora=None, minutos_antes=MINUTOS_AVISO_LIMITE):
    """True si falta `minutos_antes` o menos para el límite y todavía no pasó."""
    r = cuenta_regresiva(fecha_retiro, ahora, hora)
    return r["abierta"] and r["segundos_restantes"] <= minutos_antes * 60
