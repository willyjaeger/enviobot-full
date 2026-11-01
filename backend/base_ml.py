"""Lo que Mercado Libre tiene de cada colecta (la "base"), guardado en el servidor.

Mercado Libre manda: el último PDF cargado de un envío es lo que realmente está en Mercado Libre. Cuando EnvioBot
sugiere cambios y se guardan acá, esos cambios no están en Mercado Libre hasta que el usuario los hace a mano allá.
La base es la foto de lo que Mercado Libre tiene, y sirve para que todas las computadoras de la cuenta vean la misma
hoja de "qué hacer en Mercado Libre" (sacar, cambiar, agregar). Se renueva cada vez que se carga un PDF.

Se guarda como JSON en inbound_shipments.ml_base (migración 008). Sin la columna, la función se apaga sola.
"""
import json

CAMPOS = ("item_id", "inventory_id", "variation_id", "variation_name", "sku", "title", "units_to_send")


def instantanea(items):
    """JSON con lo mínimo de cada producto. items: dicts con las claves de inbound_shipment_items."""
    lista = []
    for it in items or []:
        fila = {c: it.get(c) for c in CAMPOS}
        fila["units_to_send"] = int(fila.get("units_to_send") or 0)
        lista.append(fila)
    return json.dumps(lista, ensure_ascii=False)


def desde_pdf(encontrados):
    """Foto de lo que dice el PDF (lo que emparejó con los productos del usuario)."""
    return instantanea([{
        "item_id": p["fila"].get("item_id"), "inventory_id": p["fila"].get("inventory_id"),
        "variation_id": p["fila"].get("variation_id"), "variation_name": p["fila"].get("variation_name"),
        "sku": p["fila"].get("sku") or p.get("sku"), "title": p["fila"].get("title") or p.get("titulo"),
        "units_to_send": p["unidades"],
    } for p in encontrados])


def cargar(texto):
    """Lista de productos, o None si no hay base o está dañada."""
    if not texto:
        return None
    try:
        lista = json.loads(texto)
    except (TypeError, ValueError):
        return None
    return lista if isinstance(lista, list) else None
