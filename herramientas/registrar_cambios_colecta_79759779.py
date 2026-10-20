"""ESCRIBE en la base (con OK de Guillermo, 2026-10-20). Registra en EnvioBot lo que ya esta guardado en Mercado Libre para la
colecta 79759779: suma 07011 x20 (ML ya lo tenia), 05142 x13 y 05012 x5. No toca los productos que ya estaban.
Se puede correr de nuevo sin duplicar: salta lo que ya esta cargado."""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"), autocommit=False)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id from inbound_shipments where shipment_code='ML-79759779' and user_id=45")
envio = cur.fetchone()["id"]

NUEVOS = [("MWPS65912", 20), ("RIEA08071", 13), ("GYWY38682", 5)]   # inventory_id, unidades (las mismas que ya guardo ML)
try:
    for inv, unidades in NUEVOS:
        cur.execute("select count(*) n from inbound_shipment_items where shipment_id=%s and inventory_id=%s", (envio, inv))
        if cur.fetchone()["n"]:
            print(inv, "ya estaba cargado: se omite")
            continue
        cur.execute("select item_id, inventory_id, variation_id, variation_name, sku, title, current_stock_full from full_items "
                    "where user_id=45 and inventory_id=%s order by (status='active') desc, id limit 1", (inv,))
        f = cur.fetchone()
        cur.execute("""INSERT INTO inbound_shipment_items (shipment_id, item_id, inventory_id, variation_id, variation_name, sku, title,
                       current_full_stock, vpd, suggested_units, units_to_send, units_per_box, box_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, %s, 0, 0)""",
                    (envio, f["item_id"], f["inventory_id"], f["variation_id"], f["variation_name"], f["sku"], f["title"],
                     int(f["current_stock_full"] or 0), unidades))
        print("agregado:", f["sku"], inv, unidades, "u.")
    cur.execute("select count(*) n, coalesce(sum(units_to_send), 0) u from inbound_shipment_items where shipment_id=%s", (envio,))
    t = cur.fetchone()
    cur.execute("UPDATE inbound_shipments SET total_items=%s, total_units=%s, updated_at=NOW() WHERE id=%s", (t["n"], int(t["u"]), envio))
    c.commit()
    print("listo: la colecta queda con", t["n"], "productos y", int(t["u"]), "unidades")
except Exception:
    c.rollback()
    raise
