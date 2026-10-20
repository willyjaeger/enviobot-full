"""Solo lectura. Para sumar a la colecta 79759779: por cada candidato, lo que sugiere el panel, lo que sugeriria si se
registra en EnvioBot lo que ML ya tiene cargado (07011 x 20) y la recomendacion de reposicion de ML. No escribe nada."""
import json
import sys

import pymysql
import requests

sys.path.insert(0, "/var/www/enviobot-full/backend")
import app as _app  # noqa: E402
import proyeccion as P  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

with _app.app.app_context():
    tok = create_access_token(identity="45")
c = _app.app.test_client()
items = c.get("/api/full/items", headers={"Authorization": "Bearer " + tok}).get_json()["items"]

conn = _app.get_db()
with conn.cursor() as cur:
    cur.execute("select ml_access_token from ml_credentials where user_id=45")
    H = {"Authorization": "Bearer " + cur.fetchone()["ml_access_token"]}
conn.close()

YA_EN_ML = {"MWPS65912": 20}   # lo que ML tiene cargado y EnvioBot no (visto en la pantalla del envio)
candidatos = ["05012", "07011", "04041", "05142", "04091", "01031"]
for it in items:
    if it.get("sku") not in candidatos or it.get("pausado"):
        continue
    stock = it.get("current_stock_full") or it.get("current_stock") or 0
    vpd = it.get("vpd_weighted") or it.get("vpd") or 0
    dias = it.get("dias_hasta_ingreso")
    incoming = it.get("total_incoming") or 0
    objetivo = it.get("target_coverage_days") or 30
    extra = YA_EN_ML.get(it.get("inventory_id"), 0)
    ajustado = P.sugerido_al_ingreso(stock, vpd, dias, incoming + extra, objetivo) if extra else it.get("sugerido_al_ingreso")
    up = None
    ml = {}
    r = requests.get("https://api.mercadolibre.com/items/" + it["item_id"], params={"attributes": "user_product_id"}, headers=H, timeout=30)
    if r.status_code == 200:
        up = r.json().get("user_product_id")
    if up:
        r2 = requests.get(f"https://api.mercadolibre.com/marketplace/fbm/user-products/{up}/replenishment", params={"country": "AR"}, headers=H, timeout=30)
        if r2.status_code in (200, 206):
            j = r2.json()
            rec = j.get("recommendation") or {}
            ml = {"tipo": rec.get("recommendation_type"), "cantidad": rec.get("suggested_quantity"), "plazo": rec.get("replenishment_deadline"),
                  "urgencia": (j.get("stock") or {}).get("shipping_urgency"), "stock_total_ml": (j.get("stock") or {}).get("total_stock")}
        else:
            ml = {"http": r2.status_code}
    print(json.dumps({"sku": it["sku"], "inv": it["inventory_id"], "titulo": (it.get("title") or "")[:40], "estado_panel": it.get("status"),
                      "stock": stock, "vpd": round(vpd, 2), "dias": it.get("days_left"), "en_camino_enviobot": incoming,
                      "sugerido_panel": it.get("sugerido_al_ingreso"), "sugerido_con_ML_cargado": ajustado, "ml": ml}, ensure_ascii=False))
