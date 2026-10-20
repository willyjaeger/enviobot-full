"""Planilla de Excel para cargar una colecta en Mercado Libre ("Planificar desde Excel", Envíos Full).

Mercado Libre no tiene API para crear el envío a Full: se arma en el Seller Center, y ahí se puede subir una planilla
con los productos y las cantidades. Este módulo completa ESA planilla (la modelo que baja ML, guardada en
plantillas/ml_envio_full.xlsx) con lo que el cliente armó en "Armar colecta".

Formato de la hoja " Selección de productos" (con el espacio adelante, así se llama en la planilla de ML):
  fila 4 = encabezados, fila 5 = ayudas, datos desde la fila 6
  A SKU | B Código universal | C Código ML | D Número de publicación | E Número de producto | F Cantidad de unidades
ML pide al menos DOS códigos por producto cuando el SKU está repetido (en tu cuenta cada SKU está en dos publicaciones del mismo
producto y con el SKU solo ML responde "Agregá un código más para que podamos reconocer el producto"). Se cargan el SKU y el
Código ML. Verificado el 2026-10-20: el "Código ML" que muestra ML es el inventory_id de la publicación.

Segunda prueba con ML (2026-10-20): con SKU + Código ML aceptó solo los productos que tienen UNA publicación y rechazó los que
tienen dos publicaciones del mismo producto ("no está asociado a ninguna publicación"). La ayuda de ML dice que en ese caso hay
que poner el Número de publicación, uno solo de los asociados al producto. Por eso también se carga la columna D, con los
dígitos del MLA (MLA2793186102 -> 2793186102), tomando una publicación activa si la hay.
ML avisa que no hay que cambiar el orden de las columnas, por eso se parte de su planilla y solo se escriben datos.

Se edita el XML de la hoja directamente (sin librerías): conserva intactos el resto de la planilla, el logo y los estilos.
"""
import io
import os
import re
import zipfile
from xml.sax.saxutils import escape

PLANTILLA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plantillas", "ml_envio_full.xlsx")
HOJA = "xl/worksheets/sheet2.xml"
PRIMERA_FILA = 6
NOMBRE_ARCHIVO = "Envio-de-stock-Full-EnvioBot.xlsx"


def _texto(ref, valor, estilo):
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{escape(str(valor))}</t></is></c>'


def _fila(n, producto):
    """Una fila de datos. El SKU va como texto (no como número) para no perder ceros: 01011 es 01011."""
    sku = str(producto.get("sku") or "").strip()
    codigo_ml = str(producto.get("inventory_id") or "").strip()
    celdas = []
    celdas.append(_texto(f"A{n}", sku, 62) if sku else f'<c r="A{n}" s="62"/>')
    celdas.append(f'<c r="B{n}" s="62"/>')
    celdas.append(_texto(f"C{n}", codigo_ml, 62) if codigo_ml else f'<c r="C{n}" s="62"/>')
    publicacion = re.sub(r"\D", "", str(producto.get("publicacion") or ""))
    celdas.append(f'<c r="D{n}" s="62" t="inlineStr"><is><t>{publicacion}</t></is></c>' if publicacion else f'<c r="D{n}" s="62"/>')
    celdas.append(f'<c r="E{n}" s="63"/>')
    celdas.append(f'<c r="F{n}" s="62"><v>{int(producto["unidades"])}</v></c>')
    return f'<row r="{n}" ht="12.75" customHeight="1">{"".join(celdas)}</row>'


def productos_validos(productos):
    """Solo los que tienen cantidad entera mayor a cero y algún código para que ML los identifique.
    Un mismo inventory_id no se repite: ML lo tomaría como el mismo producto dos veces."""
    salida = []
    vistos = set()
    for p in productos or []:
        try:
            unidades = int(round(float(p.get("unidades"))))
        except (TypeError, ValueError):
            continue
        if unidades <= 0:
            continue
        if not (str(p.get("sku") or "").strip() or str(p.get("inventory_id") or "").strip()):
            continue
        clave = str(p.get("inventory_id") or "").strip() or ("sku:" + str(p.get("sku")).strip())
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append({"sku": p.get("sku"), "inventory_id": p.get("inventory_id"), "publicacion": p.get("publicacion"), "unidades": unidades})
    return salida


def generar(productos, plantilla=PLANTILLA):
    """Bytes del .xlsx con la planilla de ML completa. Levanta ValueError si no hay nada que cargar."""
    filas = productos_validos(productos)
    if not filas:
        raise ValueError("No hay productos con unidades para cargar.")
    with zipfile.ZipFile(plantilla) as origen:
        hoja = origen.read(HOJA).decode("utf-8")
        # Se sacan las filas de datos vacías de la plantilla (desde la 6) y se ponen las nuestras.
        def _es_dato(m):
            return int(m.group(1)) >= PRIMERA_FILA
        hoja = re.sub(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', lambda m: "" if _es_dato(m) else m.group(0), hoja, flags=re.S)
        nuevas = "".join(_fila(PRIMERA_FILA + i, p) for i, p in enumerate(filas))
        hoja = hoja.replace("</sheetData>", nuevas + "</sheetData>", 1)
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino:
            for info in origen.infolist():
                datos = hoja.encode("utf-8") if info.filename == HOJA else origen.read(info.filename)
                destino.writestr(info, datos, compress_type=zipfile.ZIP_DEFLATED)
    return salida.getvalue()
