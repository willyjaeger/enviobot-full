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


def decidir(fila, en_proceso, hoy):
    """Qué hacer con una colecta en tránsito. Devuelve (nuevo estado de ML, nueva fecha de ingreso, nuevo status)
    con None en lo que no cambia."""
    recibida = (fila.get("meli_inbound_status") or "") == "received"
    if not recibida and en_proceso > 0:
        return "received", hoy, None
    if recibida and en_proceso <= 0:
        return None, None, "delivered"
    return None, None, None


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
            cur.execute("SELECT sku, units_to_send FROM inbound_shipment_items WHERE shipment_id=%s", (fila["id"],))
            en_proceso = sum(min(en_proceso_sku.get((p["sku"] or "").strip().upper(), 0), int(p["units_to_send"] or 0))
                             for p in cur.fetchall())
            estado_ml, ingreso, status = decidir(fila, en_proceso, hoy)
            if estado_ml:
                cur.execute("UPDATE inbound_shipments SET meli_inbound_status=%s, estimated_arrival_date=%s WHERE id=%s",
                            (estado_ml, ingreso, fila["id"]))
                res["recibidas"] += 1
                logger.info(f"[Recepción colecta] {fila['shipment_code']} recibida por Mercado Libre el {ingreso}")
            elif status:
                cur.execute("UPDATE inbound_shipments SET status=%s WHERE id=%s", (status, fila["id"]))
                res["cerradas"] += 1
                logger.info(f"[Recepción colecta] {fila['shipment_code']} terminó de procesarse: cerrada")
    return res
