"""Exporta una tabla simple a un Excel (.xlsx) sin librerias: arma el zip y el XML a mano, igual que planilla_ml.

Sirve para "Exportar a Excel" de las pantallas del panel (por ejemplo, la facturacion perdida por quiebres).
Recibe los encabezados y las filas; los numeros salen como numeros (se pueden sumar) y el texto como texto.
Una celda con texto nunca se interpreta como formula: va como texto en linea.
"""
import io
import zipfile
from xml.sax.saxutils import escape

MAX_FILAS = 5000
MAX_COLUMNAS = 20
TIPO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Estilos: 0 normal, 1 negrita (encabezado), 2 numero con miles, 3 pesos con miles, 4 negrita con pesos (total).
_ESTILOS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;\\ #,##0"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="5">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    '</cellXfs></styleSheet>'
)


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _celda(ref, valor, estilo=0):
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        valor = str(valor)
    if isinstance(valor, (int, float)):
        return f'<c r="{ref}" s="{estilo}"><v>{valor}</v></c>'
    return f'<c r="{ref}" s="{1 if estilo == 1 else 0}" t="inlineStr"><is><t xml:space="preserve">{escape(str(valor))}</t></is></c>'


def generar(columnas, filas, nombre_hoja="Hoja1", formatos=None):
    """columnas: lista de encabezados. filas: lista de listas. formatos: por columna 'numero' o 'pesos' (opcional).
    Una fila cuyo primer valor es 'Total' sale en negrita."""
    if not columnas or not isinstance(columnas, list) or len(columnas) > MAX_COLUMNAS:
        raise ValueError("Faltan las columnas o son demasiadas.")
    if not isinstance(filas, list) or len(filas) > MAX_FILAS:
        raise ValueError("Hay demasiadas filas para exportar.")
    formatos = list(formatos or [])
    est = {"numero": 2, "pesos": 3}
    por_col = [est.get(formatos[i] if i < len(formatos) else None, 0) for i in range(len(columnas))]
    nombre_hoja = "".join(c for c in str(nombre_hoja) if c not in '[]:*?/\\')[:31] or "Hoja1"
    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0">'
           '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>']
    xml.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{40 if i == 0 else 18}" customWidth="1"/>' for i in range(len(columnas))) + "</cols><sheetData>")
    xml.append('<row r="1">' + "".join(_celda(f"{_col(i)}1", c, 1) for i, c in enumerate(columnas)) + "</row>")
    for n, fila in enumerate(filas, start=2):
        fila = list(fila)[:len(columnas)]
        total = bool(fila) and str(fila[0]) == "Total"
        celdas = ""
        for i, v in enumerate(fila):
            estilo = por_col[i]
            if total:
                estilo = 4 if estilo == 3 else 1
            celdas += _celda(f"{_col(i)}{n}", v, estilo)
        xml.append(f'<row r="{n}">{celdas}</row>')
    xml.append("</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="' + escape(nombre_hoja, {'"': "&quot;"}) + '" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", _ESTILOS)
        z.writestr("xl/worksheets/sheet1.xml", "".join(xml))
    return buf.getvalue()
