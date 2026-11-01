"""Solo lectura. Vuelca lo que recibe el panel (cuenta 45) como JSON, para reproducir en local lo que se ve en pantalla."""
import json
import sys

sys.path.insert(0, "/var/www/enviobot-full/backend")
import app as A  # noqa: E402

A.get_jwt_identity = lambda: "45"
with A.app.test_request_context("/api/full/items"):
    r = A.get_full_items.__wrapped__()
resp = r[0] if isinstance(r, tuple) else r
print(json.dumps(resp.get_json(), default=str))
