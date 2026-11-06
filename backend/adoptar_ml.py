"""Productos del PDF de una colecta que todavía no están en el catálogo Full de EnvioBot.

El worker solo trae al catálogo las publicaciones que Mercado Libre ya marca como Full (logistic_type fulfillment) y están activas o
pausadas. Un producto que se acaba de agregar a una colecta puede estar todavía como retiro en sucursal (drop_off): ML ya le dio su
Código ML (inventory_id) y lo pone en el PDF, pero el worker no lo ve y el PDF quedaba con "no encontré este producto".

Verificado con la cuenta MISTERNUT (2026-11-06, Nueces Pecan, YFSK63695): GET /inventories/{inventory_id}/stock/fulfillment devuelve
external_references [{type: item, id, variation_id}], o sea de qué publicación es ese Código ML, y GET /items/{id} trae el resto.
Solo lectura contra ML, un pedido por producto, sin reintentos (regla de la skill api-mercadolibre). La fila nueva se guarda en
full_items recién cuando el usuario confirma la carga; en la vista previa no se escribe nada.
"""
import esquema

MELI_API = "https://api.mercadolibre.com"
MAX_PRODUCTOS = 10          # por carga de PDF: no gastar cuota de ML si algo anda mal
TIMEOUT = 12


def _sku(cuerpo):
    sku = (cuerpo.get("seller_custom_field") or "").strip()
    if sku:
        return sku
    for a in cuerpo.get("attributes") or []:
        if a.get("id") == "SELLER_SKU" and (a.get("value_name") or "").strip():
            return a["value_name"].strip()
    return ""


def _fila_desde_item(cuerpo, codigo_ml, variation_id, cred_id):
    variacion = None
    if variation_id:
        variacion = next((v for v in cuerpo.get("variations") or [] if str(v.get("id")) == str(variation_id)), None)
    sku = _sku(variacion or {}) or _sku(cuerpo)
    nombre = ""
    if variacion:
        nombre = ", ".join(str(c.get("value_name")) for c in variacion.get("attribute_combinations") or [] if c.get("value_name"))
    return {
        "id": None, "nuevo": True, "ml_credential_id": cred_id,
        "item_id": cuerpo.get("id"), "variation_id": str(variation_id or ""), "variation_name": nombre or None,
        "inventory_id": codigo_ml, "sku": sku, "title": cuerpo.get("title") or "",
        "thumbnail": cuerpo.get("thumbnail"), "permalink": cuerpo.get("permalink"),
        "listing_type_id": cuerpo.get("listing_type_id") or "gold_special", "is_catalog": bool(cuerpo.get("catalog_listing")),
        "status": cuerpo.get("status") or "active", "sub_status": ",".join(cuerpo.get("sub_status") or []) or None,
        "current_stock_full": 0,
    }


def resolver(sin_match, credenciales, http):
    """Intenta resolver por Mercado Libre los productos del PDF que no están en el catálogo.

    sin_match: productos del PDF sin emparejar (cada uno con 'codigo_ml').
    credenciales: [{'id':..., 'token':...}] de la cuenta (puede haber más de una cuenta de ML).
    http: algo con .get(url, headers=, timeout=) como `requests`.
    Devuelve (nuevos, sin_resolver): nuevos = [producto del PDF + 'fila' virtual], sin_resolver = los que no se pudieron.
    """
    nuevos, sin_resolver = [], []
    for n, p in enumerate(sin_match):
        codigo = str(p.get("codigo_ml") or "").strip().upper()
        fila = None
        if codigo and n < MAX_PRODUCTOS:
            for cred in credenciales:
                try:
                    cab = {"Authorization": "Bearer " + cred["token"]}
                    r = http.get("%s/inventories/%s/stock/fulfillment" % (MELI_API, codigo), headers=cab, timeout=TIMEOUT)
                    if r.status_code != 200:
                        continue
                    ref = next((x for x in (r.json() or {}).get("external_references") or [] if x.get("type") == "item" and x.get("id")), None)
                    if not ref:
                        continue
                    r2 = http.get("%s/items/%s" % (MELI_API, ref["id"]), headers=cab, timeout=TIMEOUT)
                    if r2.status_code != 200:
                        continue
                    fila = _fila_desde_item(r2.json() or {}, codigo, ref.get("variation_id"), cred.get("id"))
                    break
                except Exception:
                    continue          # sin red o respuesta rara: queda como "no encontrado", como antes
        if fila:
            nuevos.append(dict(p, fila=fila))
        else:
            sin_resolver.append(p)
    return nuevos, sin_resolver


def guardar(cur, user_id, nuevos):
    """Agrega al catálogo de EnvioBot los productos resueltos (solo al confirmar la carga). Lo mismo que hace el worker: si el
    producto ya existe se actualiza, y cuando ML lo marque como Full el worker sigue desde acá."""
    for p in nuevos:
        f = p["fila"]
        cur.execute("""
            INSERT INTO full_items
                (user_id, ml_credential_id, item_id, variation_id, variation_name, inventory_id, sku, title, thumbnail, permalink,
                 listing_type_id, is_catalog, status, current_stock_full, not_available_stock_full, last_synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, NOW())
            ON DUPLICATE KEY UPDATE
                ml_credential_id = VALUES(ml_credential_id), variation_name = VALUES(variation_name), inventory_id = VALUES(inventory_id),
                sku = VALUES(sku), title = VALUES(title), thumbnail = VALUES(thumbnail), permalink = VALUES(permalink),
                listing_type_id = VALUES(listing_type_id), is_catalog = VALUES(is_catalog), status = VALUES(status), last_synced_at = NOW()
        """, (user_id, f["ml_credential_id"], f["item_id"], f["variation_id"], f["variation_name"], f["inventory_id"], f["sku"],
              f["title"], f["thumbnail"], f["permalink"], f["listing_type_id"], 1 if f["is_catalog"] else 0, f["status"]))
        if f.get("sub_status") and esquema.tiene_columna(cur, "full_items", "sub_status"):
            cur.execute("UPDATE full_items SET sub_status=%s WHERE user_id=%s AND item_id=%s AND variation_id=%s",
                        (f["sub_status"], user_id, f["item_id"], f["variation_id"]))
