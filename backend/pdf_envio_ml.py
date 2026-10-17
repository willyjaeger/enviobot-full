"""Lee el PDF "Instrucciones de preparación" que Mercado Libre genera por cada envío a Full.

Del PDF salen: el número de envío de ML, y por producto el código ML (inventory_id), el SKU,
el título y las unidades. La fecha de retiro NO viene en el PDF: la pone quien carga.
Funciones puras: extraer_texto() es lo único que toca el archivo.
"""
import io
import re

_RE_NUMERO = re.compile(r'Env[ií]o\s*#\s*(\d{5,})')
_RE_TOTAL = re.compile(r'Total de unidades:\s*(\d+)')
_RE_CODIGO = re.compile(r'C[oó]digo ML:\s*(.+?)\s+C[oó]digo universal')
_RE_SKU = re.compile(r'(?:^|\s)SKU:\s*(\S+)')
# cantidad + viñeta de la primera instrucción ("40 • La fecha..."); un "45 días" suelto no cuenta
_RE_UNIDADES = re.compile(r'^(\d{1,6})\s+[^\w\s]\s')
_RE_ENCABEZADO_TABLA = re.compile(r'^PRODUCTO\s+UNIDADES')
# Rubro de ML en mayúsculas ("SUPERMERCADO"): corta el título, que puede ocupar dos renglones.
_RE_RUBRO = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 &/.,'-]{4,}$")


class PdfEnvioError(ValueError):
    pass


def extraer_texto(contenido: bytes) -> str:
    try:
        import pypdf
    except ImportError as e:  # pragma: no cover
        raise PdfEnvioError('Falta la librería pypdf en el servidor.') from e
    try:
        lector = pypdf.PdfReader(io.BytesIO(contenido))
        return '\f'.join((p.extract_text() or '') for p in lector.pages)
    except Exception as e:
        raise PdfEnvioError('No pude abrir el PDF. ¿Es el de instrucciones de preparación de Mercado Libre?') from e


def normalizar_sku(sku) -> str:
    """'04111' y '4111' son el mismo producto."""
    s = str(sku or '').strip().upper()
    return s.lstrip('0') or s


def _productos_de_pagina(lineas):
    productos = []
    unidades = []
    en_tabla = False
    i = 0
    while i < len(lineas):
        linea = lineas[i].strip()
        if _RE_ENCABEZADO_TABLA.match(linea):
            en_tabla = True
        elif en_tabla:
            m = _RE_UNIDADES.match(linea)
            if m:
                unidades.append(int(m.group(1)))
        else:
            m = _RE_CODIGO.search(linea)
            if m:
                prod = {'codigo_ml': re.sub(r'\s+', '', m.group(1)).upper(), 'sku': '', 'titulo': ''}
                j = i + 1
                # el código universal a veces salta de renglón: buscar el SKU en los próximos renglones
                while j < len(lineas) and not _RE_SKU.search(lineas[j]):
                    j += 1
                if j < len(lineas):
                    prod['sku'] = _RE_SKU.search(lineas[j]).group(1)
                    partes = []
                    k = j + 1
                    while k < len(lineas) and not _RE_RUBRO.match(lineas[k].strip()) and len(partes) < 3:
                        partes.append(lineas[k].strip())
                        k += 1
                    prod['titulo'] = ' '.join(partes)
                    i = k
                productos.append(prod)
        i += 1
    return productos, unidades


def parsear_texto(texto: str) -> dict:
    """Devuelve {'numero_ml', 'total_declarado', 'productos': [{codigo_ml, sku, titulo, unidades}]}."""
    m = _RE_NUMERO.search(texto)
    if not m:
        raise PdfEnvioError('No encuentro el número de envío. ¿Es el PDF de instrucciones de preparación de Mercado Libre?')
    numero = m.group(1)
    t = _RE_TOTAL.search(texto)
    total_declarado = int(t.group(1)) if t else None

    productos = []
    # El PDF repite el encabezado de la tabla en cada hoja; cada hoja trae sus productos y sus unidades en el mismo orden.
    hojas = texto.split('\f') if '\f' in texto else [texto]
    for hoja in hojas:
        prods, unid = _productos_de_pagina(hoja.splitlines())
        if len(prods) != len(unid):
            raise PdfEnvioError(
                'No pude emparejar los productos con sus unidades (%d productos, %d cantidades). '
                'Cargá la colecta con "Armar colecta".' % (len(prods), len(unid)))
        for p, u in zip(prods, unid):
            p['unidades'] = u
            productos.append(p)

    if not productos:
        raise PdfEnvioError('No encontré productos en el PDF.')
    suma = sum(p['unidades'] for p in productos)
    if total_declarado is not None and suma != total_declarado:
        raise PdfEnvioError('Las unidades no cierran: el PDF dice %d y sumé %d. No lo cargo para no equivocarme.'
                            % (total_declarado, suma))
    return {'numero_ml': numero, 'total_declarado': total_declarado, 'productos': productos}


def leer_pdf(contenido: bytes) -> dict:
    return parsear_texto(extraer_texto(contenido))


def emparejar_productos(productos_pdf, filas_full):
    """Une cada producto del PDF con su publicación en EnvioBot, por código ML (inventory_id) y si no por SKU.

    Devuelve (encontrados, sin_match). Cada encontrado = producto del PDF + 'fila' (la de full_items).
    Si hay varias publicaciones del mismo producto físico se usa una sola, para no contar dos veces.
    """
    por_inv, por_sku = {}, {}
    for f in filas_full:
        inv = str(f.get('inventory_id') or '').replace(' ', '').upper()
        if inv:
            por_inv.setdefault(inv, f)
        sku = normalizar_sku(f.get('sku'))
        if sku:
            por_sku.setdefault(sku, f)
    encontrados, sin_match = [], []
    for p in productos_pdf:
        fila = por_inv.get(p['codigo_ml']) or por_sku.get(normalizar_sku(p['sku']))
        if fila:
            encontrados.append(dict(p, fila=fila))
        else:
            sin_match.append(p)
    return encontrados, sin_match
