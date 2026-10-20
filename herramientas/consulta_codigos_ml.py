"""Solo lectura. Compara los 'Codigo ML' que muestra la pantalla de ML (colecta 79759779) con los inventory_id guardados."""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
vistos_en_ml = ["OLMK57428", "OXDW59563", "PDSG12023", "PNBB59129"]
for cod in vistos_en_ml:
    cur.execute("select sku, title, item_id, inventory_id from full_items where user_id=45 and inventory_id=%s", (cod,))
    f = cur.fetchall()
    print(cod, "->", [(x["sku"], x["inventory_id"], x["item_id"]) for x in f] or "NO esta como inventory_id")
cur.execute("select sku, count(*) n from full_items where user_id=45 group by sku having n>1")
print("SKU repetidos:", cur.fetchall())
cur.execute("select count(*) n, sum(inventory_id is null or inventory_id='') sin_inv from full_items where user_id=45 and status='active'")
print("activos:", cur.fetchone())
cur.execute("select sku, inventory_id, item_id from full_items where user_id=45 and sku in ('05012','07011','01011') limit 5")
print(cur.fetchall())
