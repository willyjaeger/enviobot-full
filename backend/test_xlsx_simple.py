import io
import unittest
import zipfile
import xml.dom.minidom

import xlsx_simple


class TestXlsxSimple(unittest.TestCase):
    def test_arma_un_excel_valido_con_numeros_y_texto(self):
        datos = xlsx_simple.generar(["Producto", "Dias", "Facturacion perdida"],
                                    [["Almendras <1kg>", 6, 696000.5], ["Total", 6, 696000.5]],
                                    "Facturacion", ["texto", "numero", "pesos"])
        z = zipfile.ZipFile(io.BytesIO(datos))
        for nombre in z.namelist():
            xml.dom.minidom.parseString(z.read(nombre))          # todo el XML es valido
        hoja = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Almendras &lt;1kg&gt;", hoja)               # el texto va escapado y como texto
        self.assertIn('<v>696000.5</v>', hoja)                     # el numero va como numero
        self.assertIn('t="inlineStr"', hoja)

    def test_libro_con_dos_hojas_titulo_datos_clave_y_total(self):
        datos = xlsx_simple.generar_libro([
            {"nombre": "Resumen", "titulo": "Facturacion perdida", "subtitulo": "Ultimos 30 dias",
             "kpis": [{"rotulo": "TOTAL", "valor": 1000, "formato": "pesos"}],
             "columnas": ["Producto", "Periodos", "Dias"], "formatos": ["texto", "texto", "numero"],
             "filas": [["A", "03/11 al 08/11 (6 dias)" + chr(10) + "10/11 (1 dia)", 7], ["Total", "", 7]], "notas": ["Nota"]},
            {"nombre": "Periodos", "columnas": ["Producto", "Desde"], "formatos": ["texto", "fecha"], "filas": [["A", "03/11/2026"]]}])
        z = zipfile.ZipFile(io.BytesIO(datos))
        for nombre in z.namelist():
            xml.dom.minidom.parseString(z.read(nombre))
        self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
        h1 = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("mergeCell", h1)
        self.assertIn("autoFilter", h1)
        self.assertIn("10/11 (1 dia)", h1)
        try:
            import openpyxl
        except ImportError:
            return
        wb = openpyxl.load_workbook(io.BytesIO(datos))
        self.assertEqual(wb.sheetnames, ["Resumen", "Periodos"])
        self.assertEqual(wb["Resumen"]["A1"].value, "Facturacion perdida")

    def test_rechaza_lo_que_no_corresponde(self):
        with self.assertRaises(ValueError):
            xlsx_simple.generar([], [])
        with self.assertRaises(ValueError):
            xlsx_simple.generar(["a"], [["x"]] * (xlsx_simple.MAX_FILAS + 1))


if __name__ == "__main__":
    unittest.main()
