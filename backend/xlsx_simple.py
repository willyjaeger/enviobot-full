"""Exporta tablas a un Excel (.xlsx) sin librerias: arma el zip y el XML a mano, igual que planilla_ml.

Sirve para "Exportar a Excel" de las pantallas del panel (por ejemplo, la facturacion perdida por quiebres).
Cada hoja sale presentable: titulo, subtitulo, cuadros con los datos clave, tabla con encabezado de color, filas alternadas,
bordes finos, filtros, primera fila fija, orientada para imprimir en horizontal y con notas al pie.
Los numeros salen como numeros (se pueden sumar) y el texto como texto: una celda con texto nunca se interpreta como formula.
"""
import io
import zipfile
from xml.sax.saxutils import escape

MAX_FILAS = 5000
MAX_COLUMNAS = 20
MAX_HOJAS = 5
TIPO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# Estilos (indice en cellXfs)
E_TITULO, E_SUB, E_KPI_ROT, E_KPI_TXT, E_KPI_PESOS, E_KPI_NUM, E_ENC = 1, 2, 3, 4, 5, 6, 7
E_TXT, E_NUM, E_PESOS = 8, 9, 10                 # celda normal
E_TXT_Z, E_NUM_Z, E_PESOS_Z = 11, 12, 13         # celda de fila alternada
E_TXT_T, E_NUM_T, E_PESOS_T = 14, 15, 16         # fila de total
E_CTR, E_CTR_Z = 17, 18                          # texto centrado (fechas)

_ESTILOS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="' + _NS + '">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot; #,##0"/></numFmts>'
    '<fonts count="6">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="18"/><color rgb="FF1F2430"/><name val="Calibri"/></font>'
    '<font><i/><sz val="10"/><color rgb="FF6B7280"/><name val="Calibri"/></font>'
    '<font><b/><sz val="9"/><color rgb="FF6B7280"/><name val="Calibri"/></font>'
    '<font><b/><sz val="15"/><color rgb="FFB42318"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="6">'
    '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFF5A623"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFF6F7F9"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFDEFD3"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF7E6"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills>'
    '<borders count="3">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left style="thin"><color rgb="FFD9DCE3"/></left><right style="thin"><color rgb="FFD9DCE3"/></right>'
    '<top style="thin"><color rgb="FFD9DCE3"/></top><bottom style="thin"><color rgb="FFD9DCE3"/></bottom><diagonal/></border>'
    '<border><left style="thin"><color rgb="FFD9DCE3"/></left><right style="thin"><color rgb="FFD9DCE3"/></right>'
    '<top style="medium"><color rgb="FFF5A623"/></top><bottom style="thin"><color rgb="FFD9DCE3"/></bottom><diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="19">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    # 1 titulo
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment vertical="center"/></xf>'
    # 2 subtitulo
    '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment vertical="center" wrapText="1"/></xf>'
    # 3 rotulo de dato clave
    '<xf numFmtId="0" fontId="4" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="left" vertical="center"/></xf>'
    # 4,5,6 valor de dato clave (texto, pesos, numero)
    '<xf numFmtId="0" fontId="5" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="left" vertical="center"/></xf>'
    '<xf numFmtId="164" fontId="5" fillId="5" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="left" vertical="center"/></xf>'
    '<xf numFmtId="3" fontId="5" fillId="5" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="left" vertical="center"/></xf>'
    # 7 encabezado de tabla
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    # 8,9,10 celdas
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"><alignment vertical="top"/></xf>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"><alignment vertical="top"/></xf>'
    # 11,12,13 celdas alternadas
    '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="3" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>'
    '<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>'
    # 14,15,16 total
    '<xf numFmtId="0" fontId="1" fillId="4" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="center"/></xf>'
    '<xf numFmtId="3" fontId="1" fillId="4" borderId="2" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="center"/></xf>'
    '<xf numFmtId="164" fontId="1" fillId="4" borderId="2" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="center"/></xf>'
    # 17,18 texto centrado
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment horizontal="center" vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="top"/></xf>'
    '</cellXfs></styleSheet>'
)


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _celda(ref, valor, estilo):
    if valor is None or valor == "":
        return f'<c r="{ref}" s="{estilo}"/>'
    if isinstance(valor, bool):
        valor = str(valor)
    if isinstance(valor, (int, float)):
        return f'<c r="{ref}" s="{estilo}"><v>{valor}</v></c>'
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{escape(str(valor))}</t></is></c>'


def _nombre_hoja(nombre, defecto):
    prohibidos = "[]:*?/" + chr(92)
    return "".join(c for c in str(nombre or "") if c not in prohibidos)[:31] or defecto


_ESTILO_COLUMNA = {"texto": (E_TXT, E_TXT_Z, E_TXT_T), "numero": (E_NUM, E_NUM_Z, E_NUM_T), "pesos": (E_PESOS, E_PESOS_Z, E_PESOS_T),
                   "fecha": (E_CTR, E_CTR_Z, E_TXT_T)}


def _hoja_xml(h, primera):
    columnas = h.get("columnas")
    filas = h.get("filas") or []
    if not columnas or not isinstance(columnas, list) or len(columnas) > MAX_COLUMNAS:
        raise ValueError("Faltan las columnas o son demasiadas.")
    if not isinstance(filas, list) or len(filas) > MAX_FILAS:
        raise ValueError("Hay demasiadas filas para exportar.")
    n = len(columnas)
    formatos = list(h.get("formatos") or [])
    anchos = list(h.get("anchos") or [])
    fmt = [formatos[i] if i < len(formatos) and formatos[i] in _ESTILO_COLUMNA else "texto" for i in range(n)]
    filas_xml = []
    combinadas = []
    r = 1
    # Titulo y subtitulo
    titulo, sub = h.get("titulo"), h.get("subtitulo")
    if titulo:
        filas_xml.append(f'<row r="{r}" ht="30" customHeight="1">{_celda(f"A{r}", titulo, E_TITULO)}</row>')
        combinadas.append(f"A{r}:{_col(n - 1)}{r}")
        r += 1
    if sub:
        filas_xml.append(f'<row r="{r}" ht="30" customHeight="1">{_celda(f"A{r}", sub, E_SUB)}</row>')
        combinadas.append(f"A{r}:{_col(n - 1)}{r}")
        r += 1
    # Datos clave: rotulo arriba y valor abajo, uno por columna
    kpis = [k for k in (h.get("kpis") or []) if isinstance(k, dict)][:n]
    if kpis:
        r += 1
        est_valor = {"pesos": E_KPI_PESOS, "numero": E_KPI_NUM}
        filas_xml.append(f'<row r="{r}" ht="20" customHeight="1">' + "".join(_celda(f"{_col(i)}{r}", k.get("rotulo"), E_KPI_ROT) for i, k in enumerate(kpis)) + "</row>")
        r += 1
        filas_xml.append(f'<row r="{r}" ht="30" customHeight="1">' + "".join(
            _celda(f"{_col(i)}{r}", k.get("valor"), est_valor.get(k.get("formato"), E_KPI_TXT)) for i, k in enumerate(kpis)) + "</row>")
        r += 1
    r += 1
    # Tabla
    fila_enc = r
    filas_xml.append(f'<row r="{r}" ht="34" customHeight="1">' + "".join(_celda(f"{_col(i)}{r}", c, E_ENC) for i, c in enumerate(columnas)) + "</row>")
    r += 1
    primera_dato = r
    ultima_dato = r - 1
    for k, fila in enumerate(filas):
        fila = list(fila)[:n]
        total = bool(fila) and str(fila[0]) == "Total"
        celdas = ""
        for i in range(n):
            v = fila[i] if i < len(fila) else None
            normal, zebra, tot = _ESTILO_COLUMNA[fmt[i]]
            celdas += _celda(f"{_col(i)}{r}", v, tot if total else (zebra if k % 2 else normal))
        filas_xml.append(f'<row r="{r}"' + (' ht="24" customHeight="1"' if total else "") + f">{celdas}</row>")
        if not total:
            ultima_dato = r
        r += 1
    # Notas al pie
    notas = [t for t in (h.get("notas") or []) if t][:10]
    if notas:
        r += 1
        for t in notas:
            filas_xml.append(f'<row r="{r}" ht="30" customHeight="1">{_celda(f"A{r}", t, E_SUB)}</row>')
            combinadas.append(f"A{r}:{_col(n - 1)}{r}")
            r += 1
    ancho = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{(anchos[i] if i < len(anchos) and isinstance(anchos[i], (int, float)) else (42 if i == 0 else 18))}" customWidth="1"/>'
                    for i in range(n))
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<worksheet xmlns="{_NS}"><sheetPr><tabColor rgb="FFF5A623"/><pageSetUpPr fitToPage="1"/></sheetPr>'
           f'<sheetViews><sheetView showGridLines="0"{" tabSelected=" + chr(34) + "1" + chr(34) if primera else ""} workbookViewId="0">'
           f'<pane ySplit="{fila_enc}" topLeftCell="A{fila_enc + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
           f'<sheetFormatPr defaultRowHeight="15"/><cols>{ancho}</cols><sheetData>' + "".join(filas_xml) + "</sheetData>")
    if filas and ultima_dato >= primera_dato:
        xml += f'<autoFilter ref="A{fila_enc}:{_col(n - 1)}{ultima_dato}"/>'
    if combinadas:
        xml += f'<mergeCells count="{len(combinadas)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in combinadas) + "</mergeCells>"
    xml += ('<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
            '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')
    return xml, fila_enc, ultima_dato


def generar_libro(hojas):
    """hojas: lista de {nombre, titulo, subtitulo, kpis:[{rotulo, valor, formato}], columnas, filas, formatos, anchos, notas}.
    formatos por columna: texto, numero, pesos o fecha. Una fila cuyo primer valor es 'Total' sale destacada."""
    if not isinstance(hojas, list) or not hojas or len(hojas) > MAX_HOJAS:
        raise ValueError("Faltan las hojas o son demasiadas.")
    partes = []
    nombres = []
    for i, h in enumerate(hojas):
        if not isinstance(h, dict):
            raise ValueError("Hoja invalida.")
        xml, _, _ = _hoja_xml(h, i == 0)
        partes.append(xml)
        nombre = _nombre_hoja(h.get("nombre"), f"Hoja{i + 1}")
        while nombre in nombres:
            nombre = nombre[:28] + f"({i + 1})"
        nombres.append(nombre)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(partes)))
                   + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="' + _NS + '" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(nombres[i], {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i in range(len(partes)))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(partes)))
                   + f'<Relationship Id="rId{len(partes) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", _ESTILOS)
        for i, xml in enumerate(partes):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", xml)
    return buf.getvalue()


def generar(columnas, filas, nombre_hoja="Hoja1", formatos=None):
    """Una sola hoja simple (compatibilidad)."""
    return generar_libro([{"nombre": nombre_hoja, "columnas": columnas, "filas": filas, "formatos": formatos}])
