"""Solo lectura. Columnas y datos de los productos de la colecta ML-79759779 en EnvioBot (para saber que se perderia al reescribirlos)."""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv("/var/www/enviobot-full/backend/.env")
c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id, total_items, total_units, total_boxes, status, packaging_type, carrier_notes from inbound_shipments where shipment_code='ML-79759779' and user_id=45")
print(cur.fetchone())
cur.execute("select * from inbound_shipment_items where shipment_id=(select id from inbound_shipments where shipment_code='ML-79759779' and user_id=45)")
for f in cur.fetchall():
    extra = {k: v for k, v in f.items() if k not in ("id", "shipment_id", "item_id", "inventory_id", "variation_id", "variation_name", "sku", "title",
                                                       "current_full_stock", "vpd", "suggested_units", "units_to_send", "units_per_box", "box_count", "created_at")}
    print(f["sku"], f["inventory_id"], f["units_to_send"], "| otros campos:", extra)
