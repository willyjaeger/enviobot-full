"""Solo lectura. Pide a MercadoLibre el sub_status de las publicaciones pausadas de la cuenta 45.
El token se usa en memoria y no se imprime."""
import json
import os

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select ml_access_token from ml_credentials where user_id=45")
token = cur.fetchone()["ml_access_token"]
cur.execute("select item_id, sku, title from full_items where user_id=45 and status='paused'")
items = cur.fetchall()
por_id = {i["item_id"]: i for i in items}
ids = list(por_id)
salida = []
for k in range(0, len(ids), 20):
    r = requests.get("https://api.mercadolibre.com/items",
                     params={"ids": ",".join(ids[k:k + 20]),
                             "attributes": "id,status,sub_status,available_quantity,last_updated"},
                     headers={"Authorization": "Bearer " + token}, timeout=30)
    if r.status_code != 200:
        print(json.dumps({"error": r.status_code}))
        raise SystemExit
    for x in r.json():
        b = x.get("body", {})
        i = por_id.get(b.get("id"), {})
        salida.append({"item_id": b.get("id"), "sku": i.get("sku"), "title": i.get("title"),
                       "status": b.get("status"), "sub_status": b.get("sub_status"),
                       "cantidad": b.get("available_quantity"), "actualizada": b.get("last_updated")})
print(json.dumps(salida, default=str))
