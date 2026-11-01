"""Historial de ventas por día de cada publicación, para calcular el ritmo de venta limpio (demanda.py).

Solo guarda unidades por publicación y día (sin compradores ni órdenes sueltas). La primera vez que se ve
una publicación se bajan los últimos 120 días; después, en cada sincronización, solo los últimos días
(se vuelven a bajar unos pocos para corregir cancelaciones). El detalle diario de más de 120 días se junta en
semanas (ventas_semanales, hasta 2 años) y se borra. Sin las tablas de la migración 006 no hace nada.
"""
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import esquema

MELI_API = "https://api.mercadolibre.com"
BA = timezone(timedelta(hours=-3))  # Buenos Aires no tiene horario de verano
DIAS_DETALLE = 120
DIAS_REPASO = 3        # días ya guardados que se vuelven a bajar por si hubo cancelaciones
TRAMO = 10             # días por pedido: orders/search no devuelve más de ~1000 resultados por consulta
SEMANAS_GUARDADAS = 104


def hoy_ba(ahora=None):
    return (ahora or datetime.now(BA)).astimezone(BA).date()


def acumular_ordenes(ordenes, item_id):
    """{variation_id: {fecha: unidades}} de una lista de órdenes de ML. Ignora canceladas e inválidas."""
    out = defaultdict(lambda: defaultdict(int))
    for o in ordenes:
        if o.get("status") in ("cancelled", "invalid"):
            continue
        try:
            dia = datetime.fromisoformat(o["date_created"]).astimezone(BA).date()
        except (KeyError, ValueError):
            continue
        for oi in o.get("order_items", []):
            it = oi.get("item", {})
            if it.get("id") == item_id:
                out[str(it.get("variation_id") or "")][dia] += oi.get("quantity", 1)
    return out


def dias_a_bajar(ultimo_dia, hoy):
    """Cuántos días hacia atrás hay que pedir a ML: todo si es la primera vez; si no, desde unos días
    antes del último guardado."""
    if ultimo_dia is None:
        return DIAS_DETALLE
    return max(DIAS_REPASO, min(DIAS_DETALLE, (hoy - ultimo_dia).days + DIAS_REPASO))


def ventas_por_dia(access_token, meli_user_id, item_id, dias, hoy=None, pausa=0.3):
    """Baja las ventas de las últimas `dias` jornadas completas (hoy no, está incompleto).
    Devuelve {variation_id: {fecha: unidades}} o None si algún pedido falló (mejor nada que datos a medias)."""
    hoy = hoy or hoy_ba()
    fin = datetime(hoy.year, hoy.month, hoy.day, tzinfo=BA)
    t = fin - timedelta(days=dias)
    headers = {"Authorization": f"Bearer {access_token}"}
    out = defaultdict(lambda: defaultdict(int))
    while t < fin:
        t2 = min(t + timedelta(days=TRAMO), fin)
        offset = 0
        while True:
            for intento in range(6):  # ML responde 429 si se pide muy seguido: se espera y se reintenta
                r = requests.get(f"{MELI_API}/orders/search", headers=headers, timeout=30, params={
                    "seller": meli_user_id, "item": item_id, "limit": 50, "offset": offset,
                    "order.date_created.from": t.isoformat(),
                    "order.date_created.to": (t2 - timedelta(seconds=1)).isoformat()})
                if r.status_code != 429:
                    break
                time.sleep(2 * (intento + 1))
            if r.status_code != 200:
                print(f"Ventas por día de {item_id}: ML respondió {r.status_code}, se reintenta en la próxima sincronización")
                return None
            j = r.json()
            for var, dias_ventas in acumular_ordenes(j.get("results", []), item_id).items():
                for dia, u in dias_ventas.items():
                    out[var][dia] += u
            offset += 50
            if offset >= j.get("paging", {}).get("total", 0):
                break
        t = t2
        time.sleep(pausa)
    return out


def sincronizar_item(conn, access_token, meli_user_id, user_id, item_id, variaciones, hoy=None):
    """Baja y guarda las ventas por día de una publicación (todas sus variaciones). Devuelve True si guardó."""
    hoy = hoy or hoy_ba()
    with conn.cursor() as cur:
        if not esquema.tiene_tabla(cur, "ventas_diarias"):
            return False
        cur.execute("SELECT MAX(day) AS d FROM ventas_diarias WHERE user_id=%s AND item_id=%s", (user_id, item_id))
        ultimo = (cur.fetchone() or {}).get("d")
    dias = dias_a_bajar(ultimo, hoy)
    ventas = ventas_por_dia(access_token, meli_user_id, item_id, dias, hoy)
    if ventas is None:
        return False
    ayer = hoy - timedelta(days=1)
    filas = []
    for var in set(variaciones) | set(ventas):
        por_dia = dict(ventas.get(var, {}))
        por_dia.setdefault(ayer, 0)  # marca hasta qué día está bajado, aunque no haya vendido
        filas += [(user_id, item_id, var, dia, u) for dia, u in por_dia.items()]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO ventas_diarias (user_id, item_id, variation_id, day, unidades) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE unidades = VALUES(unidades)
        """, filas)
    return True


def lunes(dia):
    return dia - timedelta(days=dia.weekday())


def consolidar(conn, hoy=None):
    """Junta en semanas el detalle diario de más de 120 días, lo borra y descarta las semanas de más de 2 años.
    Solo junta semanas completas (hasta el lunes anterior al corte), así no se pisa una semana partida."""
    hoy = hoy or hoy_ba()
    corte = lunes(hoy - timedelta(days=DIAS_DETALLE))
    with conn.cursor() as cur:
        if not (esquema.tiene_tabla(cur, "ventas_diarias") and esquema.tiene_tabla(cur, "ventas_semanales")):
            return 0
        cur.execute("""
            INSERT INTO ventas_semanales (user_id, item_id, variation_id, semana, unidades)
            SELECT user_id, item_id, variation_id, DATE_SUB(day, INTERVAL WEEKDAY(day) DAY), SUM(unidades)
            FROM ventas_diarias WHERE day < %s
            GROUP BY user_id, item_id, variation_id, DATE_SUB(day, INTERVAL WEEKDAY(day) DAY)
            ON DUPLICATE KEY UPDATE unidades = VALUES(unidades)
        """, (corte,))
        cur.execute("DELETE FROM ventas_diarias WHERE day < %s", (corte,))
        borradas = cur.rowcount
        cur.execute("DELETE FROM ventas_semanales WHERE semana < %s", (hoy - timedelta(weeks=SEMANAS_GUARDADAS),))
    return borradas


def serie_diaria(conn, user_id, item_id, variation_id, hoy=None):
    """{fecha: unidades} guardada de una publicación (variation_id '' si no tiene variaciones)."""
    hoy = hoy or hoy_ba()
    with conn.cursor() as cur:
        if not esquema.tiene_tabla(cur, "ventas_diarias"):
            return {}
        cur.execute("""SELECT day, unidades FROM ventas_diarias
                       WHERE user_id=%s AND item_id=%s AND variation_id=%s AND day < %s""",
                    (user_id, item_id, variation_id or "", hoy))
        return {f["day"]: int(f["unidades"]) for f in cur.fetchall()}
