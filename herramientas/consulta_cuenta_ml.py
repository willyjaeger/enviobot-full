"""Solo lectura. Muestra numero y nombre de las cuentas de MercadoLibre (sin tokens)."""
import json
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select user_id, ml_user_id, ml_nickname from ml_credentials order by user_id")
print(json.dumps(cur.fetchall(), default=str))
