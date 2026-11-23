"""Marca solas las colectas que Mercado Libre ya recibió, con la fecha real, y las cierra cuando terminó de procesarlas.

Lo corre el sincronizador (worker.py) después de traer el stock de Full. No usa columnas nuevas:
- Una colecta en tránsito cuyos productos tienen stock en proceso en Full (no disponible) ya fue recibida:
  se anota meli_inbound_status = 'received' y la fecha de ingreso (estimated_arrival_date) pasa a ser la real.
- Cuando ya estaba recibida y ese stock en proceso volvió a 0, Mercado Libre terminó de procesarla: pasa a 'delivered'.
- Una colecta que todavía no salió (scheduled) no se toca: ese stock en proceso puede ser de otra colecta anterior.
La demora real (retiro -> recepción) queda guardada en las colectas recibidas y sirve para corregir las estimaciones.
"""
import logging
from datetime import date, datetime

logger = logging.getLogger("recepcion_colectas")

DIAS_PARA_DAR_POR_RECIBIDA = 7
FRACCION_PARA_DAR_POR_RECIBIDA = 0.5   # el stock tiene que haber subido, al menos, la mitad de lo enviado


def ingreso_por_stock(stock_por_dia, ventas_por_dia, retiro, unidades, fraccion=FRACCION_PARA_DAR_POR_RECIBIDA):
    """Primer día en que el stock de Full subió lo que se mandó (evidencia de que Mercado Libre la recibió), o None.

    `stock_por_dia` y `ventas_por_dia`: {date: unidades} sumando los productos de la colecta. Lo que entró hasta un día
    es: stock de ese día - stock del retiro + lo vendido en el medio (las ventas esconden parte de la suba).
    Sin dato de stock del retiro no se afirma nada."""
    if not unidades or unidades <= 0 or retiro is None or retiro not in stock_por_dia:
        return None
    base = stock_por_dia[retiro]
    vendido = 0
    for dia in sorted(d for d in stock_por_dia if d > retiro):
        vendido += ventas_por_dia.get(dia, 0)
        if stock_por_dia[dia] - base + vendido >= unidades * fraccion:
            return dia
    return None


def decidir(fila, en_proceso, hoy, ingreso_stock=None):
    """Qué hacer con una colecta en tránsito. Devuelve (nuevo estado de ML, nueva fecha de ingreso, nuevo status)
    con None en lo que no cambia. `ingreso_stock`: día en que el stock de Full subió lo enviado (ingreso_por_stock)."""
    recibida = (fila.get("meli_inbound_status") or "") == "received"
    if not recibida and en_proceso > 0:
        return "received", hoy, None
    # El stock de Full subió lo que se mandó y no queda nada en proceso: entró y ya está a la venta.
    if not recibida and en_proceso <= 0 and ingreso_stock is not None:
        return "received", ingreso_stock, "delivered"
    # Ya pasó mucho desde el retiro y Mercado Libre no tiene nada en proceso: la recibió y la procesó entre dos
    # sincronizaciones (o antes de que existiera este control). Sin esto quedaba "en camino" para siempre y se contaba doble.
    retiro = fila.get("pickup_date")
    if not recibida and en_proceso <= 0 and retiro is not None and (hoy - retiro).days > DIAS_PARA_DAR_POR_RECIBIDA:
        return None, None, "delivered"
    if recibida and en_proceso <= 0:
        return None, None, "delivered"
    return None, None, None


def _ingreso_segun_stock(cur, user_id, fila, renglones, hoy):
    """Lee la foto diaria de stock y las ventas de los productos de la colecta. Sin esas tablas o sin datos, None."""
    try:
        retiro = fila.get("pickup_date")
        items = {r["item_id"] for r in renglones if r.get("item_id")}
        unidades = sum(int(r["units_to_send"] or 0) for r in renglones if r.get("item_id"))
        if retiro is None or not items or unidades <= 0:
            return None
        marcas = ",".join(["%s"] * len(items))
        cur.execute("SELECT day, SUM(stock_max) AS n FROM stock_daily WHERE user_id=%s AND item_id IN (" + marcas +
                    ") AND day >= %s GROUP BY day", (user_id, *items, retiro))
        stock = {f["day"]: int(f["n"] or 0) for f in cur.fetchall()}
        cur.execute("SELECT day, SUM(unidades) AS n FROM ventas_diarias WHERE user_id=%s AND item_id IN (" + marcas +
                    ") AND day >= %s GROUP BY day", (user_id, *items, retiro))
        ventas = {f["day"]: int(f["n"] or 0) for f in cur.fetchall()}
        return ingreso_por_stock(stock, ventas, retiro, unidades)
    except Exception:
        return None


def actualizar(conn, user_id, hoy=None):
    """Una pasada por las colectas en tránsito de la cuenta. Devuelve {'recibidas': n, 'cerradas': n}."""
    hoy = hoy or datetime.now().date()
    res = {"recibidas": 0, "cerradas": 0}
    with conn.cursor() as cur:
        cur.execute("SELECT id, shipment_code, pickup_date, meli_inbound_status FROM inbound_shipments "
                    "WHERE user_id=%s AND status='in_transit'", (user_id,))
        filas = cur.fetchall()
        if not filas:
            return res
        cur.execute("SELECT UPPER(TRIM(sku)) AS sku, SUM(not_available_stock_full) AS n FROM full_items "
                    "WHERE user_id=%s AND sku IS NOT NULL GROUP BY UPPER(TRIM(sku))", (user_id,))
        en_proceso_sku = {f["sku"]: int(f["n"] or 0) for f in cur.fetchall()}
        for fila in filas:
            cur.execute("SELECT sku, units_to_send, item_id FROM inbound_shipment_items WHERE shipment_id=%s", (fila["id"],))
            renglones = cur.fetchall()
            en_proceso = sum(min(en_proceso_sku.get((p["sku"] or "").strip().upper(), 0), int(p["units_to_send"] or 0))
                             for p in renglones)
            ingreso_stock = _ingreso_segun_stock(cur, user_id, fila, renglones, hoy)
            estado_ml, ingreso, status = decidir(fila, en_proceso, hoy, ingreso_stock)
            if estado_ml and status:
                cur.execute("UPDATE inbound_shipments SET meli_inbound_status=%s, estimated_arrival_date=%s, status=%s WHERE id=%s",
                            (estado_ml, ingreso, status, fila["id"]))
                res["recibidas"] += 1
                res["cerradas"] += 1
                logger.info(f"[Recepción colecta] {fila['shipment_code']} entró a Full el {ingreso} (el stock subió lo enviado): cerrada")
            elif estado_ml:
                cur.execute("UPDATE inbound_shipments SET meli_inbound_status=%s, estimated_arrival_date=%s WHERE id=%s",
                            (estado_ml, ingreso, fila["id"]))
                res["recibidas"] += 1
                logger.info(f"[Recepción colecta] {fila['shipment_code']} recibida por Mercado Libre el {ingreso}")
            elif status:
                cur.execute("UPDATE inbound_shipments SET status=%s WHERE id=%s", (status, fila["id"]))
                res["cerradas"] += 1
                logger.info(f"[Recepción colecta] {fila['shipment_code']} terminó de procesarse: cerrada")
    return res
