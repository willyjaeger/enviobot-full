"""Solo lectura. Prueba el recurso de recomendacion de reposicion de ML con el producto de mayor stock de la cuenta 45.
Un solo pedido por paso, sin reintentos. El token se usa en memoria y no se imprime."""
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
cur.execute("select item_id, sku, title, current_stock_full from full_items where user_id=45 and status='active' order by current_stock_full desc limit 1")
p = cur.fetchone()
print("Producto:", p["sku"], "|", p["title"][:60], "| stock Full:", p["current_stock_full"])

r = requests.get("https://api.mercadolibre.com/items/" + p["item_id"], headers=H, timeout=30)
print("GET /items ->", r.status_code)
up = (r.json() or {}).get("user_product_id") if r.status_code == 200 else None
print("user_product_id:", up)
if not up:
    raise SystemExit("Sin user_product_id: no se puede pedir la reposicion.")

r = requests.get(f"https://api.mercadolibre.com/marketplace/fbm/user-products/{up}/replenishment",
                 params={"country": "AR"}, headers=H, timeout=30)
print("GET replenishment ->", r.status_code, "| X-Content-Missing:", r.headers.get("X-Content-Missing"))
try:
    j = r.json()
except ValueError:
    print(r.text[:300]); raise SystemExit
if r.status_code in (200, 206):
    print(json.dumps({k: j.get(k) for k in ("identifiers", "stock", "recommendation", "eligibility_benefits")}, indent=1, ensure_ascii=False))
    print("ventas 30d:", (j.get("sales") or {}).get("sales_totals"))
    print("historial semanal:", (j.get("sales") or {}).get("sales_history"))
else:
    print(json.dumps(j)[:400])
