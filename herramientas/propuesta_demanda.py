"""Solo lectura. Baja las ventas por día de los últimos 120 días de Mercado Libre, calcula el ritmo limpio
(sin días sin stock, sin rebote, sin picos) y muestra por producto cuántos días de stock hay y cuánto convendría pedir.
No escribe en la base ni en ML. El token se usa en memoria y no se imprime.

Uso en el servidor:  python propuesta_demanda.py <user_id> [texto del título]
"""
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pymysql
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import demanda  # noqa: E402

BA = timezone(timedelta(hours=-3))
DIAS = 120
TRAMO = 10  # días por pedido: orders/search no pasa de ~1000 resultados por consulta

load_dotenv("/var/www/enviobot-full/backend/.env")
user_id = int(sys.argv[1])
filtro = " ".join(sys.argv[2:]).lower()

c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
                    database=os.getenv("DB_NAME"), cursorclass=pymysql.cursors.DictCursor)
cur = c.cursor()
cur.execute("SELECT ml_user_id, ml_access_token FROM ml_credentials WHERE user_id=%s", (user_id,))
cred = cur.fetchone()
H = {"Authorization": "Bearer " + cred["ml_access_token"]}
cur.execute("SELECT target_coverage_days FROM user_settings WHERE user_id=%s", (user_id,))
objetivo = int((cur.fetchone() or {}).get("target_coverage_days") or 30)

cur.execute("""SELECT f.item_id, f.variation_id, f.inventory_id, f.sku, f.title, f.current_stock_full stock, fc.vpd_weighted vpd, fc.sales_last_30d s30
               FROM full_items f LEFT JOIN forecasts fc ON fc.user_id=f.user_id AND fc.item_id=f.item_id AND fc.variation_id<=>f.variation_id
               WHERE f.user_id=%s AND f.status='active'""", (user_id,))
productos = [p for p in cur.fetchall() if not filtro or filtro in (p["title"] or "").lower()]
print(f"{len(productos)} publicaciones, objetivo {objetivo} días de cobertura. Bajando ventas de {DIAS} días...\n")

hoy = datetime.now(BA).date()


def ventas_item(item_id):
    """{variation_id: {fecha: unidades}} de las últimas DIAS jornadas completas."""
    out = defaultdict(lambda: defaultdict(int))
    fin = datetime.now(BA).replace(hour=0, minute=0, second=0, microsecond=0)
    ini = fin - timedelta(days=DIAS)
    t = ini
    while t < fin:
        t2 = min(t + timedelta(days=TRAMO), fin)
        offset = 0
        while True:
            for intento in range(6):  # ML responde 429 si se pide muy seguido: se espera y se reintenta
                r = requests.get("https://api.mercadolibre.com/orders/search", headers=H, timeout=30, params={
                    "seller": cred["ml_user_id"], "item": item_id, "limit": 50, "offset": offset,
                    "order.date_created.from": t.isoformat(), "order.date_created.to": (t2 - timedelta(seconds=1)).isoformat()})
                if r.status_code != 429:
                    break
                time.sleep(2 * (intento + 1))
            if r.status_code != 200:
                print(f"  aviso: {item_id} {r.status_code} {r.text[:80]}")
                break
            j = r.json()
            for o in j.get("results", []):
                if o.get("status") in ("cancelled", "invalid"):
                    continue
                dia = datetime.fromisoformat(o["date_created"]).astimezone(BA).date()
                for oi in o.get("order_items", []):
                    it = oi.get("item", {})
                    if it.get("id") == item_id:
                        out[str(it.get("variation_id") or "")][dia] += oi.get("quantity", 1)
            offset += 50
            if offset >= j.get("paging", {}).get("total", 0):
                break
        t = t2
        time.sleep(0.15)
    return out


try:
    cur.execute("SELECT item_id, variation_id, day FROM stock_daily WHERE user_id=%s AND stock_max=0", (user_id,))
    sin_stock = defaultdict(set)
    for f in cur.fetchall():
        sin_stock[(f["item_id"], f["variation_id"] or "")].add(f["day"])
except pymysql.Error:
    sin_stock = defaultdict(set)

# Un producto físico puede estar en varias publicaciones que comparten stock (mismo inventory_id):
# se suman las ventas y el stock se cuenta una sola vez.
grupos = defaultdict(list)
for p in productos:
    grupos[p["inventory_id"] or ("%s|%s" % (p["item_id"], p["variation_id"] or ""))].append(p)

cache = {}
filas = []
for ps in grupos.values():
    serie, sin = defaultdict(int), set()
    for p in ps:
        iid = p["item_id"]
        if iid not in cache:
            cache[iid] = ventas_item(iid)
        for dia, u in cache[iid].get(str(p["variation_id"] or ""), {}).items():
            serie[dia] += u
        sin |= sin_stock[(iid, p["variation_id"] or "")]
    p = dict(ps[0])
    p["stock"] = max(int(x["stock"] or 0) for x in ps)
    p["vpd"] = sum(float(x["vpd"] or 0) for x in ps)
    p["s30"] = sum(int(x["s30"] or 0) for x in ps)
    p["title"] = max((x["title"] or "" for x in ps), key=len)
    e = demanda.estimar(dict(serie), hoy, sin, dias=DIAS)
    stock = p["stock"]
    if e["base"] == 0 and not p["s30"] and stock == 0:
        continue
    filas.append((p, e, stock))
    if os.getenv("DETALLE"):
        print(f"\n--- {p['sku']} {p['title'][:40]}: día, unidades, motivo de descarte")
        for dd in demanda.limpiar(dict(serie), hoy, DIAS, sin):
            if dd["unidades"] or dd["motivo"]:
                print(f"{dd['dia']} {dd['dia'].strftime('%a')} {dd['unidades']:>4}  {dd['motivo'] or ''}")
        print()

filas.sort(key=lambda x: -(x[1]["base"] * 1000 + x[2]))
print(f"{'SKU':<10}{'Producto':<34}{'Stock':>6} {'App':>6} {'Bajo':>6} {'Base':>6} {'Alto':>6} {'Media':>6} {'Quieb':>5}  {'Tendencia':<9}{'Conf.':<6}{'Días stock (alto-bajo)':<24}Pedir {objetivo}d (bajo/base/alto)")
for p, e, stock in filas:
    ds = [demanda.dias_de_stock(stock, e[k]) for k in ("alto", "base", "bajo")]
    rango = " - ".join("sin venta" if v is None else f"{v:.0f}" for v in (ds[0], ds[2]))
    pedir = "/".join(str(demanda.unidades_a_pedir(e[k], stock, 0, objetivo)) for k in ("bajo", "base", "alto"))
    d = e["descartados"]
    print(f"{(p['sku'] or '')[:9]:<10}{(p['title'] or '')[:32]:<34}{stock:>6} {float(p['vpd'] or 0):>6.1f} {e['bajo']:>6.1f} {e['base']:>6.1f} {e['alto']:>6.1f} {e['media_con_stock']:>6.1f} {e['quiebres']:>5}  {e['tendencia']:<9}{e['confianza']:<6}{rango:<24}{pedir}   (descartados: {d['sin_stock']} sin stock, {d['rebote']} rebote)")
