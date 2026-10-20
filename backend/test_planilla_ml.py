"""Tests de la planilla de Excel para cargar la colecta en Mercado Libre."""
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planilla_ml as p  # noqa: E402


def _abrir(datos):
    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(datos))


class TestPlanillaML(unittest.TestCase):
    PRODS = [{"sku": "01011", "inventory_id": "LZLB58855", "unidades": 120},
             {"sku": "05012", "inventory_id": "ABCD12345", "unidades": "5"},
             {"sku": "", "inventory_id": "ZZZZ99999", "unidades": 7}]

    def test_la_planilla_conserva_la_estructura_de_mercado_libre(self):
        wb = _abrir(p.generar(self.PRODS))
        self.assertEqual(wb.sheetnames, ["Ayuda", " Selección de productos"])   # el espacio adelante es de ML
        hoja = wb[" Selección de productos"]
        self.assertIn("SKU", hoja["A4"].value)
        self.assertIn("Cantidad de unidades", hoja["F4"].value)

    def test_los_datos_van_desde_la_fila_6_en_el_orden_de_columnas(self):
        hoja = _abrir(p.generar(self.PRODS))[" Selección de productos"]
        self.assertEqual([hoja["A6"].value, hoja["F6"].value], ["01011", 120])
        self.assertEqual([hoja["A7"].value, hoja["F7"].value], ["05012", 5])

    def test_el_sku_conserva_el_cero_inicial(self):
        hoja = _abrir(p.generar(self.PRODS))[" Selección de productos"]
        self.assertIsInstance(hoja["A6"].value, str)
        self.assertEqual(hoja["A6"].value, "01011")

    def test_lleva_el_sku_y_el_codigo_ml_porque_el_sku_solo_no_alcanza(self):
        hoja = _abrir(p.generar(self.PRODS))[" Selección de productos"]
        self.assertEqual([hoja["A6"].value, hoja["C6"].value], ["01011", "LZLB58855"])   # lo que ML pidió: un código más
        self.assertIsNone(hoja["A8"].value)                  # sin SKU queda solo el código ML
        self.assertEqual(hoja["C8"].value, "ZZZZ99999")

    def test_lleva_el_numero_de_publicacion_sin_el_prefijo_mla(self):
        prods = [{"sku": "01011", "inventory_id": "LZLB58855", "publicacion": "MLA1493630699", "unidades": 5},
                 {"sku": "02022", "inventory_id": "BBBB22222", "unidades": 3}]
        hoja = _abrir(p.generar(prods))[" Selección de productos"]
        self.assertEqual(str(hoja["D6"].value), "1493630699")   # solo los dígitos, como el ejemplo de ML
        self.assertIsNone(hoja["D7"].value)                     # sin publicación queda vacío

    def test_un_mismo_producto_no_se_repite_en_la_planilla(self):
        dup = [{"sku": "01011", "inventory_id": "LZLB58855", "unidades": 5}, {"sku": "01011", "inventory_id": "LZLB58855", "unidades": 9}]
        self.assertEqual(len(p.productos_validos(dup)), 1)

    def test_se_ignoran_cantidades_vacias_ceros_y_productos_sin_codigo(self):
        validos = p.productos_validos([{"sku": "A", "unidades": 0}, {"sku": "B", "unidades": -3}, {"sku": "C", "unidades": "x"},
                                       {"sku": "", "inventory_id": "", "unidades": 4}, {"sku": "OK", "unidades": 2.4}])
        self.assertEqual([(v["sku"], v["unidades"]) for v in validos], [("OK", 2)])

    def test_sin_productos_no_genera_nada(self):
        with self.assertRaises(ValueError):
            p.generar([{"sku": "A", "unidades": 0}])

    def test_los_caracteres_raros_del_sku_no_rompen_el_archivo(self):
        hoja = _abrir(p.generar([{"sku": 'A&B <x> "y"', "unidades": 1}]))[" Selección de productos"]
        self.assertEqual(hoja["A6"].value, 'A&B <x> "y"')

    def test_el_resto_del_archivo_queda_igual_que_el_de_ml(self):
        with zipfile.ZipFile(p.PLANTILLA) as orig, zipfile.ZipFile(io.BytesIO(p.generar(self.PRODS))) as nuevo:
            self.assertEqual(orig.namelist(), nuevo.namelist())
            for n in orig.namelist():
                if n != p.HOJA:
                    self.assertEqual(orig.read(n), nuevo.read(n), n)

    def test_cabe_una_colecta_grande(self):
        grande = [{"sku": f"S{i}", "unidades": i + 1} for i in range(300)]
        hoja = _abrir(p.generar(grande))[" Selección de productos"]
        self.assertEqual(hoja["A305"].value, "S299")


if __name__ == "__main__":
    unittest.main()
