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

    def test_rechaza_lo_que_no_corresponde(self):
        with self.assertRaises(ValueError):
            xlsx_simple.generar([], [])
        with self.assertRaises(ValueError):
            xlsx_simple.generar(["a"], [["x"]] * (xlsx_simple.MAX_FILAS + 1))


if __name__ == "__main__":
    unittest.main()
