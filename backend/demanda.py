"""Ritmo de venta con margen de seguridad, a partir de las ventas por día.

Se probó con ventas reales (herramientas/backtest_demanda.py, 14 días hacia adelante): ningún método acierta con
menos de 35 % de error, y el mejor es el más simple, el promedio de los últimos 28 días. Un número único se queda
corto la mitad de las veces (cobertura 49 %). Para no quebrar hace falta un margen que dependa de cuánto varía la
venta de cada producto: promedio + 0,5 desvío diario cubre 80 % de los casos y promedio + 1 desvío, 96 %.
Por eso se devuelven tres ritmos:
  - base: promedio de 28 días (lo esperable);
  - protegido: base + K_SERVICIO desvíos (con el que se planifica la colecta para no quebrar);
  - alto: base + 1 desvío (hasta dónde puede llegar sin sorpresa).
Solo se descartan los días en que se sabe que el producto no tenía stock (stock_daily). Recortar "rebotes" o inferir
quiebres por ceros seguidos no mejoró el pronóstico y se sacó.

Funciones puras, sin base ni ML, para poder probarlas solas (ver test_demanda.py).
"""
from datetime import timedelta

DIAS_RECIENTES = 14
DIAS_LARGOS = 28
VENTANA = 7              # para el ritmo de referencia: cada semana móvil
MIN_VALIDOS_VENTANA = 4
UMBRAL_BAJA = 0.70       # la última semana vende menos que esto del ritmo anterior: tendencia a la baja
UMBRAL_SUBA = 1.40
K_SERVICIO = 0.5         # desvíos de margen para planificar (0,5 = cubre ~80 % de las veces; 1 = ~96 %)


def _percentil(valores, p):
    """Percentil p (0 a 100) por interpolación lineal. Lista vacía devuelve 0."""
    v = sorted(valores)
    if not v:
        return 0.0
    if len(v) == 1:
        return float(v[0])
    pos = (len(v) - 1) * p / 100.0
    i = int(pos)
    frac = pos - i
    if i + 1 >= len(v):
        return float(v[-1])
    return v[i] + (v[i + 1] - v[i]) * frac


def _mediana(valores):
    return _percentil(valores, 50)


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def _desvio(valores):
    if len(valores) < 2:
        return 0.0
    m = sum(valores) / len(valores)
    return (sum((x - m) ** 2 for x in valores) / len(valores)) ** 0.5


def limpiar(serie, hoy, dias=60, sin_stock=()):
    """Lista de dicts de más viejo a más nuevo: {dia, unidades, valido, motivo}, con motivo None o 'sin_stock'.

    serie: {fecha: unidades}; los días que faltan valen 0. Termina ayer: hoy está incompleto.
    sin_stock: fechas en las que se sabe que el producto estuvo en cero (stock_daily).
    """
    # Antes de la primera venta registrada el producto no existía o no había historia: no cuenta.
    con_venta = [f for f, u in serie.items() if u and f < hoy]
    primero = min(con_venta) if con_venta else hoy
    dias_lista = [hoy - timedelta(days=n) for n in range(dias, 0, -1) if hoy - timedelta(days=n) >= primero]
    sin_stock = set(sin_stock or ())
    return [{"dia": d, "unidades": int(serie.get(d, 0) or 0), "valido": d not in sin_stock,
             "motivo": "sin_stock" if d in sin_stock else None} for d in dias_lista]


def _valores(dias, hasta):
    """Ventas de los días válidos de los últimos `hasta` días."""
    return [d["unidades"] for d in dias[max(0, len(dias) - hasta):] if d["valido"]]


def estimar(serie, hoy, sin_stock=(), dias=60, k=K_SERVICIO):
    """Ritmo de venta por día con margen y datos para explicarlo.

    Devuelve un dict: base, protegido, alto, bajo (unidades por día), sigma (desvío diario), ultimos7 y ultimos3
    (venta reciente), referencia (buenas semanas recientes), tendencia ('baja', 'suba', 'estable' o 'sin_datos'),
    confianza ('alta', 'media', 'baja'), validos, descartados ({'sin_stock': n}), quiebres (cuántas veces se quedó
    sin stock), ventas_30 y vpd_crudo_30 (para comparar) y dias_analizados.
    """
    lista = limpiar(serie, hoy, dias, sin_stock)
    validos = [d for d in lista if d["valido"]]
    ventas_30 = sum(d["unidades"] for d in lista[-30:])
    quiebres, previo_q = 0, False
    for d in lista:
        q = not d["valido"]
        quiebres += q and not previo_q
        previo_q = q

    v7, v3 = _valores(lista, 7), _valores(lista, 3)
    v14, v28 = _valores(lista, DIAS_RECIENTES), _valores(lista, DIAS_LARGOS)
    r7, r3 = _media(v7), _media(v3)
    base = _media(v28) if v28 else (_media(v14) or 0.0)
    sigma = _desvio(v28)
    protegido = base + k * sigma
    alto = base + 1.0 * sigma
    bajo = min(base, r7) if r7 is not None else base

    # Ritmo de referencia: lo que se vendía en las buenas semanas recientes (percentil 75 de las semanas móviles
    # de los últimos ~2 meses). Sirve para saber si hoy se vende mucho menos que cuando se planificó una compra.
    largas = []
    for fin in range(0, 54):
        tramo = lista[max(0, len(lista) - fin - VENTANA):len(lista) - fin]
        vals = [d["unidades"] for d in tramo if d["valido"]]
        if len(vals) >= MIN_VALIDOS_VENTANA:
            largas.append(sum(vals) / len(vals))
    referencia = _percentil(largas, 75) if len(largas) >= 8 else None

    previo_vals = [d["unidades"] for d in lista[max(0, len(lista) - 35):max(0, len(lista) - 7)] if d["valido"]]
    if len(v7) >= MIN_VALIDOS_VENTANA and len(previo_vals) >= 7 and _media(previo_vals):
        ratio = r7 / _media(previo_vals)
        tendencia = "baja" if ratio < UMBRAL_BAJA else "suba" if ratio > UMBRAL_SUBA else "estable"
    else:
        tendencia = "sin_datos"

    n = len(validos)
    confianza = "alta" if n >= 28 else "media" if n >= 14 else "baja"
    return {
        "bajo": round(bajo, 2), "base": round(base, 2), "protegido": round(protegido, 2), "alto": round(alto, 2),
        "sigma": round(sigma, 2),
        "ultimos7": round(r7, 2) if r7 is not None else None,
        "ultimos3": round(r3, 2) if r3 is not None else None,
        "tendencia": tendencia, "confianza": confianza, "validos": n,
        "referencia": round(referencia, 2) if referencia is not None else None,
        "descartados": {"sin_stock": len(lista) - n}, "ventas_30": ventas_30,
        "vpd_crudo_30": round(ventas_30 / 30.0, 2),
        "quiebres": quiebres, "dias_analizados": len(lista),
    }


def dias_de_stock(stock, tasa):
    """Días que dura el stock a ese ritmo. None si no hay ventas."""
    if tasa is None or tasa <= 0:
        return None
    return round(stock / tasa, 1)


def unidades_a_pedir(tasa, stock, entrante, dias_objetivo, dias_hasta_ingreso=0):
    """Unidades para llegar a dias_objetivo de cobertura contando desde el ingreso de la colecta.
    Lo que se vende durante la espera se descuenta del stock de hoy (como en proyeccion.py)."""
    if tasa is None or tasa <= 0:
        return 0
    stock_al_ingreso = max(0.0, stock - tasa * dias_hasta_ingreso)
    return max(0, int(round(dias_objetivo * tasa - stock_al_ingreso - entrante)))


MIN_VALIDOS_PANEL = 7   # con menos días válidos que estos no se confía en el cálculo nuevo


def ritmo_para_panel(serie, hoy, sin_stock, vpd_anterior):
    """Ritmo que usa el panel para planificar. Si hay historia suficiente, el protegido (base + margen);
    si no, el de siempre. Devuelve el dict de estimar() más 'vpd' (el que se usa), 'fuente' ('limpio' o
    'anterior') y 'vpd_anterior'."""
    e = estimar(serie, hoy, sin_stock)
    e["vpd_anterior"] = round(float(vpd_anterior or 0), 2)
    usable = bool(serie) and e["validos"] >= MIN_VALIDOS_PANEL and (e["base"] > 0 or not vpd_anterior)
    e["fuente"] = "limpio" if usable else "anterior"
    e["vpd"] = e["protegido"] if usable else e["vpd_anterior"]
    return e
