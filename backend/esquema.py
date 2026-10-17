"""Averigua si la base ya tiene las columnas/tablas de la migración 001.

El código nuevo puede llegar al servidor ANTES de que se aplique la migración (que se hace con el
servicio apagado y con OK de Guillermo). Mientras tanto no debe romper nada: si falta la columna,
la función nueva se apaga sola y el panel sigue como antes.
"""
import time

_TTL = 300  # segundos; así, aplicada la migración, se enciende sola sin reiniciar
_cache = {}


def _consultar(cur, sql, params):
    cur.execute(sql, params)
    fila = cur.fetchone()
    if not fila:
        return False
    valor = list(fila.values())[0] if isinstance(fila, dict) else fila[0]
    return bool(valor)


def tiene_columna(cur, tabla, columna, ahora=None):
    return _cacheado(('col', tabla, columna), cur, """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
    """, (tabla, columna), ahora)


def tiene_tabla(cur, tabla, ahora=None):
    return _cacheado(('tab', tabla), cur, """
        SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
    """, (tabla,), ahora)


def _cacheado(clave, cur, sql, params, ahora):
    ahora = time.time() if ahora is None else ahora
    guardado = _cache.get(clave)
    if guardado and ahora - guardado[1] < _TTL:
        return guardado[0]
    try:
        existe = _consultar(cur, sql, params)
    except Exception:
        return False  # ante la duda, la función nueva queda apagada
    _cache[clave] = (existe, ahora)
    return existe


def olvidar():
    """Para los tests."""
    _cache.clear()
