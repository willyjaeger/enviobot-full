"""Solo lectura. Prueba si MercadoLibre informa los movimientos de stock de Full (ingresos de colectas incluidos).
Pide operations/search de un producto de la cuenta 45 por dos rutas y cuenta los tipos de operacion.
El token se usa en memoria y no se imprime."""
import collections
import json
import os
from datetime import date, timedelta

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select ml_access_token, ml_user_id from ml_credentials where user_id=45")
cred = cur.fetchone()
cur.execute("select inventory_id, sku from full_items where user_id=45 and inventory_id is not null order by current_stock_full desc limit 1")
productos = cur.fetchall()
H = {"Authorization": "Bearer " + cred["ml_access_token"]}
hoy = date.today()
for p in productos:
    for ruta in ("/stock/fulfillment/operations/search",):
        for dias in (60,):
            params = {"seller_id": cred["ml_user_id"], "inventory_id": p["inventory_id"],
                      "date_from": str(hoy - timedelta(days=dias)), "date_to": str(hoy)}
            r = requests.get("https://api.mercadolibre.com" + ruta, params=params, headers=H, timeout=30)
            print(f"\n{p['sku']} {ruta} -> HTTP {r.status_code}")
            try:
                j = r.json()
            except ValueError:
                print(r.text[:200]); continue
            if r.status_code != 200:
                print(json.dumps(j)[:300]); continue
            ops = j.get("results") or j.get("operations") or []
            print("claves:", list(j.keys()), "| operaciones:", len(ops))
            print("tipos:", dict(collections.Counter(o.get("type") for o in ops)))
            for o in ops[:3]:
                print({k: o.get(k) for k in ("id", "type", "date_created", "external_references", "result")})
