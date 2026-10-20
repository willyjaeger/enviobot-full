"""Solo lectura. Pide a la app (en el servidor, con un token de la cuenta 45) los items tal como los recibe el panel,
y devuelve solo los campos que usa el boton de la planilla."""
import json
import sys

sys.path.insert(0, "/var/www/enviobot-full/backend")
import app as _app  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

with _app.app.app_context():
    tok = create_access_token(identity="45")
c = _app.app.test_client()
r = c.get("/api/full/items", headers={"Authorization": "Bearer " + tok})
j = r.get_json()
items = j.get("items") or j.get("data") or []
print(json.dumps({"http": r.status_code, "claves": list(j.keys()),
                  "items": [{k: it.get(k) for k in ("id", "item_id", "sku", "inventory_id", "title", "pausado", "status")} | {"channels": [{"item_id": ch.get("item_id"), "status": ch.get("status")} for ch in (it.get("channels") or [])]} for it in items]}))
