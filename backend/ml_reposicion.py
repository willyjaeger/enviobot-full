"""Lo que Mercado Libre informa de cada producto en Full: ventas de los últimos 30 días, ventas por semana y
recomendación de reposición (recurso /marketplace/fbm/user-products/{id}/replenishment). Se guarda en ml_reposicion
(migración 007) para mostrar al lado de nuestro ritmo de venta. Solo lee de ML. Sin la tabla no hace nada.
"""
import time

import requests

import esquema

MELI_API = "https://api.mercadolibre.com"
SEMANAS_GUARDADAS = 5


def interpretar(j):
    """De la respuesta de ML a lo que se guarda: {unidades_30d, semanas, sugerido, urgencia, stock_total}."""
    ventas = (j.get("sales") or {})
    u30 = None
    try:
        u30 = int(sum((x or {}).get("full", 0) or 0 for x in (ventas.get("sales_totals") or {}).get("units_sold", [])))
    except (TypeError, ValueError, AttributeError):
        u30 = None
    historial = ventas.get("sales_history") or []
    semanas = [int(h.get("units_sold") or 0) for h in historial[:SEMANAS_GUARDADAS]]
    rec = j.get("recommendation") or {}
    sugerido = (rec.get("suggested_quantity") or {}).get("value")
    stock = j.get("stock") or {}
    return {
        "unidades_30d": u30,
        "semanas": ",".join(str(x) for x in semanas),
        "sugerido": int(sugerido) if isinstance(sugerido, (int, float)) else None,
        "urgencia": stock.get("shipping_urgency"),
        "stock_total": stock.get("total_stock"),
    }


def _get(url, headers, params=None):
    for intento in range(5):  # ML responde 429 si se pide muy seguido: se espera y se reintenta
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 429:
            return r
        time.sleep(2 * (intento + 1))
    return r


def sincronizar_item(conn, access_token, user_id, item_id, pausa=0.4):
    """Baja y guarda lo que ML informa de una publicación. Devuelve True si guardó."""
    with conn.cursor() as cur:
        if not esquema.tiene_tabla(cur, "ml_reposicion"):
            return False
        cur.execute("SELECT user_product_id FROM ml_reposicion WHERE user_id=%s AND item_id=%s", (user_id, item_id))
        fila = cur.fetchone() or {}
    headers = {"Authorization": f"Bearer {access_token}"}
    up = fila.get("user_product_id")
    if not up:
        r = _get(f"{MELI_API}/items/{item_id}", headers)
        up = (r.json() or {}).get("user_product_id") if r.status_code == 200 else None
        if not up:
            return False
    r = _get(f"{MELI_API}/marketplace/fbm/user-products/{up}/replenishment", headers, {"country": "AR"})
    if r.status_code not in (200, 206):
        print(f"Reposición ML de {item_id}: ML respondió {r.status_code}")
        return False
    d = interpretar(r.json())
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ml_reposicion (user_id, item_id, user_product_id, unidades_30d, semanas, sugerido, urgencia, stock_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE user_product_id=VALUES(user_product_id), unidades_30d=VALUES(unidades_30d),
                semanas=VALUES(semanas), sugerido=VALUES(sugerido), urgencia=VALUES(urgencia), stock_total=VALUES(stock_total)
        """, (user_id, item_id, up, d["unidades_30d"], d["semanas"], d["sugerido"], d["urgencia"], d["stock_total"]))
    time.sleep(pausa)
    return True


def para_panel(fila):
    """Lo que ve el panel de una fila de ml_reposicion: ritmos por día según ML. None si no hay datos."""
    if not fila or fila.get("unidades_30d") is None:
        return None
    semanas = [int(x) for x in (fila.get("semanas") or "").split(",") if x != ""]
    return {
        "vpd_30": round(fila["unidades_30d"] / 30.0, 1),
        "vpd_ultima_semana": round(semanas[0] / 7.0, 1) if semanas else None,
        "semanas": [round(x / 7.0, 1) for x in semanas],
        "sugerido": fila.get("sugerido"),
        "urgencia": fila.get("urgencia"),
    }
