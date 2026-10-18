"""Solo lectura. Se manda por ssh al servidor y escribe el JSON por la salida."""
import json
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute(
    "select i.user_id, i.sku, i.title, i.variation_name, i.current_stock_full, "
    "i.not_available_stock_full, f.sales_last_7d, f.sales_last_15d, f.sales_last_30d, "
    "f.vpd_weighted, f.days_left, f.status "
    "from full_items i left join forecasts f on f.user_id=i.user_id "
    "and f.item_id=i.item_id and f.variation_id=i.variation_id "
    "where i.status=%s order by i.user_id, i.title", ("active",))
print(json.dumps(cur.fetchall(), default=str))
