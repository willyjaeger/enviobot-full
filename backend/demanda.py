"""Ritmo de venta limpio y con rango, a partir de las ventas por día.

El VPD de siempre promedia 7, 15 y 30 días y se deja engañar: un producto que estuvo sin stock
y vuelve vende de golpe lo acumulado (el "rebote") y ese pico entra como si fuera el ritmo normal.
Acá se sacan los días sin stock, los de rebote y los picos sueltos, y se devuelve un escenario
bajo, uno base y uno alto, para decidir cuánto pedir según lo caro que sea el producto.

Funciones puras, sin base ni ML, para poder probarlas solas (ver test_demanda.py).
"""
from datetime import timedelta

DIAS_REBOTE = 7          # días posteriores a un quiebre en los que la venta puede venir inflada
FACTOR_REBOTE = 1.25     # un día de rebote se descarta si vende más de 1,25 veces el ritmo normal
MIN_CORRIDA_CERO = 2     # días seguidos en cero que se toman como quiebre si no hay dato de stock
MIN_VENTA_QUIEBRE = 3    # ...y el producto normalmente vende al menos esto por día (mediana)
DIAS_RECIENTES = 14
DIAS_LARGOS = 28
VENTANA = 7              # para los escenarios: ritmo de cada semana móvil
MIN_VALIDOS_VENTANA = 4
UMBRAL_BAJA = 0.70       # la última semana vende menos que esto del ritmo anterior: tendencia a la baja
UMBRAL_SUBA = 1.40


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


def _winsorizar(valores):
    """Recorta los picos sueltos: nada pasa de mediana + 3 desvíos robustos (MAD)."""
    if len(valores) < 5:
        return list(valores)
    med = _mediana(valores)
    mad = _mediana([abs(x - med) for x in valores])
    # si el ritmo es casi constante el MAD da 0: se deja un margen mínimo para no recortar de más
    escala = max(1.4826 * mad, 0.25 * med, 1.0)
    tope = med + 3 * escala
    return [min(x, tope) for x in valores]


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def limpiar(serie, hoy, dias=60, sin_stock=()):
    """Marca cada día como válido o descartado. Devuelve una lista de dicts de más viejo a más nuevo:
    {dia, unidades, valido, motivo} con motivo None, 'sin_stock', 'sin_stock_inferido' o 'rebote'.

    serie: {fecha: unidades}; los días que faltan valen 0. Termina ayer: hoy está incompleto.
    sin_stock: fechas en las que se sabe que el producto estuvo en cero (stock_daily).
    """
    # Antes de la primera venta registrada el producto no existía o no había historia: no cuenta.
    con_venta = [f for f, u in serie.items() if u and f < hoy]
    primero = min(con_venta) if con_venta else hoy
    dias_lista = [hoy - timedelta(days=n) for n in range(dias, 0, -1) if hoy - timedelta(days=n) >= primero]
    unidades = [int(serie.get(d, 0) or 0) for d in dias_lista]
    sin_stock = set(sin_stock or ())
    motivo = [("sin_stock" if d in sin_stock else None) for d in dias_lista]

    # Sin dato de stock: varios días seguidos en cero en un producto que suele vender = quiebre.
    positivos = [u for u in unidades if u > 0]
    if positivos and _mediana(positivos) >= MIN_VENTA_QUIEBRE:
        i = 0
        while i < len(unidades):
            if unidades[i] == 0 and motivo[i] is None:
                j = i
                while j < len(unidades) and unidades[j] == 0:
                    j += 1
                # un cero que llega hasta hoy también es quiebre, salvo que sea solo ayer
                if j - i >= MIN_CORRIDA_CERO:
                    for k in range(i, j):
                        if motivo[k] is None:
                            motivo[k] = "sin_stock_inferido"
                i = j
            else:
                i += 1

    # Rebote: los días que siguen a un quiebre y venden bastante más que el ritmo normal.
    normales = [u for u, m in zip(unidades, motivo) if m is None]
    ref = _mediana(normales) if normales else 0
    for i in range(len(unidades)):
        if motivo[i] and motivo[i].startswith("sin_stock"):
            fin = i
            while fin + 1 < len(unidades) and motivo[fin + 1] and motivo[fin + 1].startswith("sin_stock"):
                fin += 1
            for k in range(fin + 1, min(fin + 1 + DIAS_REBOTE, len(unidades))):
                if motivo[k] is None and ref > 0 and unidades[k] > ref * FACTOR_REBOTE:
                    motivo[k] = "rebote"

    return [{"dia": d, "unidades": u, "valido": m is None, "motivo": m}
            for d, u, m in zip(dias_lista, unidades, motivo)]


def _tasa(dias, desde, hasta):
    """Media (con picos recortados) de los días válidos en [desde, hasta) contando desde el final."""
    tramo = dias[len(dias) - hasta:len(dias) - desde] if hasta > desde else []
    vals = [d["unidades"] for d in tramo if d["valido"]]
    if not vals:
        return None, 0
    return _media(_winsorizar(vals)), len(vals)


def estimar(serie, hoy, sin_stock=(), dias=60):
    """Ritmo de venta por día con tres escenarios y datos para explicarlo.

    Devuelve un dict: bajo, base, alto (unidades por día), ultimos7, tendencia ('baja', 'suba',
    'estable' o 'sin_datos'), confianza ('alta', 'media', 'baja'), validos, descartados
    ({'sin_stock': n, 'rebote': n}), ventas_30 (suma cruda), vpd_crudo_30 (para comparar),
    media_con_stock (promedio de todos los días con stock, rebote incluido), quiebres (cuántas veces se quedó sin stock)
    y dias_analizados.
    """
    lista = limpiar(serie, hoy, dias, sin_stock)
    validos = [d for d in lista if d["valido"]]
    descartados = {"sin_stock": 0, "rebote": 0}
    for d in lista:
        if d["motivo"] == "rebote":
            descartados["rebote"] += 1
        elif d["motivo"]:
            descartados["sin_stock"] += 1
    ventas_30 = sum(d["unidades"] for d in lista[-30:])
    con_stock = [d["unidades"] for d in lista if not (d["motivo"] or "").startswith("sin_stock")]
    quiebres, previo_q = 0, False
    for d in lista:
        q = (d["motivo"] or "").startswith("sin_stock")
        quiebres += q and not previo_q
        previo_q = q

    r7, n7 = _tasa(lista, 0, 7)
    r14, n14 = _tasa(lista, 0, DIAS_RECIENTES)
    r28, n28 = _tasa(lista, 0, DIAS_LARGOS)
    previo, nprev = _tasa(lista, 7, 35)

    if r14 is None and r28 is None:
        base = 0.0
    elif r14 is None:
        base = r28
    elif r28 is None:
        base = r14
    else:
        base = 0.6 * r14 + 0.4 * r28

    # Escenarios: cómo anduvo cada semana móvil de las últimas cuatro (solo con días válidos).
    tasas = []
    for fin in range(0, 22):
        tramo = lista[len(lista) - fin - VENTANA:len(lista) - fin]
        vals = [d["unidades"] for d in tramo if d["valido"]]
        if len(vals) >= MIN_VALIDOS_VENTANA:
            tasas.append(sum(vals) / len(vals))
    if len(tasas) >= 3:
        bajo = min(base, _percentil(tasas, 25))
        alto = max(base, _percentil(tasas, 75))
    else:
        bajo, alto = base, base

    if n7 >= MIN_VALIDOS_VENTANA and previo and nprev >= 7:
        ratio = r7 / previo
        tendencia = "baja" if ratio < UMBRAL_BAJA else "suba" if ratio > UMBRAL_SUBA else "estable"
    else:
        tendencia = "sin_datos"

    n = len(validos)
    confianza = "alta" if n >= 28 else "media" if n >= 14 else "baja"
    return {
        "bajo": round(bajo, 2), "base": round(base, 2), "alto": round(alto, 2),
        "ultimos7": round(r7, 2) if r7 is not None else None,
        "tendencia": tendencia, "confianza": confianza, "validos": n,
        "descartados": descartados, "ventas_30": ventas_30,
        "vpd_crudo_30": round(ventas_30 / 30.0, 2),
        "media_con_stock": round(_media(con_stock), 2) if con_stock else 0.0,
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


MIN_VALIDOS_PANEL = 7   # con menos días válidos que estos no se confía en el cálculo limpio


def ritmo_para_panel(serie, hoy, sin_stock, vpd_anterior):
    """Ritmo que usa el panel. Si hay historia suficiente, el limpio (base); si no, el de siempre.

    Devuelve el dict de estimar() más 'vpd' (el que se usa), 'fuente' ('limpio' o 'anterior') y 'vpd_anterior'.
    """
    e = estimar(serie, hoy, sin_stock)
    e["vpd_anterior"] = round(float(vpd_anterior or 0), 2)
    usable = bool(serie) and e["validos"] >= MIN_VALIDOS_PANEL and (e["base"] > 0 or not vpd_anterior)
    e["fuente"] = "limpio" if usable else "anterior"
    e["vpd"] = e["base"] if usable else e["vpd_anterior"]
    return e
