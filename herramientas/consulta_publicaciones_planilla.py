"""Solo lectura. Por que ML acepto 2 filas de la planilla y rechazo 12: compara publicaciones por producto (cuenta 45)."""
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
H = {"Authorization": "Bearer " + cur.fetchone()["ml_access_token"]}
ok = {"04091", "06012"}
invs = ["GYWY38682", "MWPS65912", "DRQH11846", "RIEA08071", "DVMJ65268", "VZWH85028", "LZLB58855", "PDSG12023",
        "TUMT28072", "PDCL66192", "PNBB59129", "BIDY66377", "OXDW59563"]
for inv in invs:
    cur.execute("select sku, item_id, variation_id, status from full_items where user_id=45 and inventory_id=%s", (inv,))
    filas = cur.fetchall()
    ids = [f["item_id"] for f in filas]
    estados = {}
    if ids:
        r = requests.get("https://api.mercadolibre.com/items", params={"ids": ",".join(ids), "attributes": "id,status,sub_status,user_product_id,catalog_listing,variations"}, headers=H, timeout=30)
        for x in r.json():
            b = x.get("body", {})
            estados[b.get("id")] = (b.get("status"), b.get("sub_status"), b.get("user_product_id"), len(b.get("variations") or []))
    sku = filas[0]["sku"] if filas else "?"
    print(("OK  " if sku in ok else "FALLA"), sku, inv, "publicaciones:", len(filas), "variation_ids:", [f["variation_id"] for f in filas])
    for i in ids:
        print("      ", i, estados.get(i))
