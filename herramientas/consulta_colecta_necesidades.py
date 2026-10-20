"""Solo lectura. Para la colecta 79759779: que tiene cargado en EnvioBot y que productos necesitan sumarse
segun el panel (mismos numeros que ve el usuario: sugerido_al_ingreso). No escribe nada."""
import json
import sys

sys.path.insert(0, "/var/www/enviobot-full/backend")
import app as _app  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

with _app.app.app_context():
    tok = create_access_token(identity="45")
H = {"Authorization": "Bearer " + tok}
c = _app.app.test_client()

lista = c.get("/api/full/inbound/shipments", headers=H).get_json()
envios = lista.get("shipments") or lista.get("colectas") or []
mio = next((e for e in envios if str(e.get("shipment_code", "")).endswith("79759779")), None)
print("envio en EnvioBot:", None if not mio else {k: mio.get(k) for k in ("id", "shipment_code", "status", "pickup_date", "total_units", "total_items")})
detalle = {}
if mio:
    d = c.get(f"/api/full/inbound/shipments/{mio['id']}", headers=H).get_json()
    detalle = d
    print("items cargados:", len(d.get("items") or []), "| cerrada_por_ml:", (d.get("shipment") or {}).get("cerrada_por_ml"),
          "| limite:", (d.get("shipment") or {}).get("limite_edicion"))
    for it in d.get("items") or []:
        print("   ", it.get("sku"), it.get("inventory_id"), it.get("units_to_send"), "|", (it.get("title") or "")[:50])

r = c.get("/api/full/items", headers=H).get_json()
en_colecta = {str(it.get("inventory_id")) for it in (detalle.get("items") or [])}
print("\nProductos que el panel sugiere sumar (no estan en la colecta):")
total = 0
for it in r.get("items") or []:
    if it.get("pausado"):
        continue
    sug = it.get("sugerido_al_ingreso") or 0
    if sug > 0 and str(it.get("inventory_id")) not in en_colecta:
        total += sug
        print(f"   {it.get('sku')} {it.get('inventory_id')} sugerido={sug} estado={it.get('status')} stock={it.get('current_stock')} dias={it.get('days_left')} | {(it.get('title') or '')[:48]}")
print("total unidades a sumar:", total)
print("\nYa en la colecta pero con aviso de ajuste:")
for it in r.get("items") or []:
    if it.get("aviso_ajuste_units"):
        print(f"   {it.get('sku')} {it.get('inventory_id')} en_preparacion={it.get('in_preparation_stock')} -> {it.get('aviso_ajuste_units')}")
