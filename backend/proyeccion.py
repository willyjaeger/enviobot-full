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
LIMITE_EDICION_MINUTO = 40
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


def limite_edicion(fecha_retiro):
    """Momento hasta el que se puede modificar la colecta: el día anterior al retiro, 9:40 de
    Buenos Aires. Devuelve un datetime con zona horaria."""
    dia = fecha_retiro - timedelta(days=1)
    return datetime(dia.year, dia.month, dia.day, LIMITE_EDICION_HORA, LIMITE_EDICION_MINUTO, tzinfo=HORA_BA)


def cuenta_regresiva(fecha_retiro, ahora=None):
    """Datos para el cartel de la colecta. 'abierta' es False si ya pasó el límite."""
    ahora = ahora or datetime.now(HORA_BA)
    limite = limite_edicion(fecha_retiro)
    segundos = int((limite - ahora).total_seconds())
    return {
        "fecha_retiro": fecha_retiro.isoformat(),
        "limite_edicion": limite.isoformat(),
        "segundos_restantes": max(0, segundos),
        "abierta": segundos > 0,
    }
