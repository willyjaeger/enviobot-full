"""Solo lectura. Cuenta items de la cuenta 45 por estado y lista los no activos o sin monitorear."""
import json
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select status, is_monitored, count(*) n, count(distinct sku) skus, sum(current_stock_full) stock "
            "from full_items where user_id=45 group by status, is_monitored")
resumen = cur.fetchall()
cur.execute("select item_id, sku, title, status, is_monitored, current_stock_full, not_available_stock_full, last_synced_at "
            "from full_items where user_id=45 and (status<>'active' or is_monitored=0) order by title")
fuera = cur.fetchall()
print(json.dumps({"resumen": resumen, "fuera": fuera}, default=str))
