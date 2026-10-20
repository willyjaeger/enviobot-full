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


def etapa_colecta(codigo, estado, en_proceso=0, recibida_ml=False):
    """En cuál de los cuatro pasos está la colecta: 'propuesta', 'armada', 'retirada' o 'recibida'.

    Se deduce de lo que ya sabemos, sin adivinar: una colecta cargada desde Mercado Libre (ML-...) está al menos
    armada; si ya salió (en tránsito) está retirada; y es recibida si Mercado Libre ya tiene en proceso unidades de
    esa colecta (`en_proceso`) o el sincronizador ya la marcó recibida (`recibida_ml`). Una colecta que todavía no
    salió nunca pasa a recibida: ese stock en proceso puede ser de otra colecta anterior con los mismos productos."""
    estado = estado or "scheduled"
    if estado == "delivered":
        return "recibida"
    if estado == "in_transit":
        return "recibida" if (recibida_ml or int(en_proceso or 0) > 0) else "retirada"
    return "armada" if str(codigo or "").startswith("ML-") else "propuesta"


def demora_aprendida(muestras):
    """Días que de verdad tarda una colecta del retiro a la recepción, según las últimas recibidas (la mediana,
    para que una demora rara no la mueva). `muestras`: días reales, de la más reciente a la más vieja. None si
    todavía no hay ninguna."""
    dias = sorted([max(0, min(int(m), 14)) for m in (muestras or []) if m is not None][:5])
    if not dias:
        return None
    n = len(dias)
    medio = dias[n // 2] if n % 2 else (dias[n // 2 - 1] + dias[n // 2]) / 2
    return int(medio + 0.5)


def ingreso_estimado(fila, demora_real=None):
    """Fecha de ingreso a Full de una colecta. Si ya fue recibida, es la real. Si no, la que se cargó a mano; y si
    la fecha es la automática (retiro + demora supuesta), se corrige con la demora que de verdad tardaron las
    colectas anteriores (`demora_real`). Nunca es un dato cierto hasta que Mercado Libre la recibe."""
    retiro = fila["pickup_date"]
    cargada = fila.get("estimated_arrival_date")
    recibida = (fila.get("meli_inbound_status") or "") == "received" or fila.get("status") == "delivered"
    supuesta = retiro + timedelta(days=int(fila.get("transit_days") or 3))
    if recibida and cargada:
        return cargada
    if cargada and cargada != supuesta:
        return cargada  # la movieron a mano: se respeta
    if demora_real is not None:
        return retiro + timedelta(days=int(demora_real))
    return cargada or supuesta


def armar_colecta(fila, productos, hora=None, ahora=None, en_proceso=0, demora_real=None):
    """Una colecta lista para mostrar: estado, fechas (retiro, límite de edición, ingreso a Full) y sus productos.
    `fila` es el registro de inbound_shipments; `productos`, sus renglones (title, sku, units_to_send).
    `en_proceso`: unidades de esta colecta que Mercado Libre ya recibió y todavía está procesando."""
    retiro = fila["pickup_date"]
    estado = fila.get("status") or "scheduled"
    base = cuenta_regresiva(retiro, ahora=ahora, hora=hora)
    ingreso = ingreso_estimado(fila, demora_real)
    recibida_ml = (fila.get("meli_inbound_status") or "") == "received"
    unidades = sum(int(p.get("units_to_send") or 0) for p in productos)
    en_proceso = max(0, min(int(en_proceso or 0), unidades)) if estado == "in_transit" else 0
    return {
        "etapa": etapa_colecta(fila.get("shipment_code"), estado, en_proceso, recibida_ml),
        "ingreso_estimado": not (recibida_ml or estado == "delivered"),
        "unidades_en_proceso": en_proceso,
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


def calcular_cambio_fechas(retiro_actual, ingreso_actual, transito_dias, nuevo_retiro=None, nuevo_ingreso=None, hoy=None):
    """Fechas finales de una colecta si se mueve su retiro y/o su ingreso a Full.

    El retiro y el ingreso se pueden mover aunque Mercado Libre haya cerrado la colecta: la agenda cambia por ellos o
    por nosotros, y el ingreso es una estimación (retiro + demora supuesta), no un dato. Si solo se mueve el retiro,
    el ingreso lo acompaña con la misma demora. Devuelve {'retiro','ingreso','transito_dias'} o {'error': texto}."""
    hoy = hoy or datetime.now(HORA_BA).date()
    if nuevo_retiro is not None and nuevo_retiro < hoy:
        return {"error": "La fecha de retiro no puede ser anterior a hoy."}
    retiro = nuevo_retiro or retiro_actual
    if nuevo_ingreso is not None:
        if nuevo_ingreso < hoy:
            return {"error": "La fecha de ingreso no puede ser anterior a hoy."}
        ingreso = nuevo_ingreso
    elif nuevo_retiro is not None:
        hueco = (ingreso_actual - retiro_actual).days if ingreso_actual else int(transito_dias or 3)
        ingreso = nuevo_retiro + timedelta(days=hueco)
    else:
        ingreso = ingreso_actual or (retiro + timedelta(days=int(transito_dias or 3)))
    if ingreso < retiro:
        return {"error": "El ingreso a Full no puede ser antes del retiro."}
    return {"retiro": retiro, "ingreso": ingreso, "transito_dias": (ingreso - retiro).days}


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


def pausa_por_quiebre(canales, stock):
    """True si el producto está pausado en ML (todas sus publicaciones) porque se quedó sin stock en Full.

    Una pausa por otro motivo (el vendedor lo pausó, suspensión, revisión) no es un quiebre y no se avisa.
    Sin el motivo guardado (migración 002 sin aplicar) no se puede saber, y se asume que no es por stock.
    """
    if not canales or stock > 0:
        return False
    if any((ch.get("status") or "active") == "active" for ch in canales):
        return False
    return any("out_of_stock" in (ch.get("sub_status") or "") for ch in canales)
