import unittest

import pdf_envio_ml as m

# Texto con la misma forma que entrega el PDF de ML (dos hojas, código universal partido en dos renglones).
HOJA1 = """Envío #78889570
Productos del envío: 3 | Total de unidades: 185
Listado de productos e instrucciones de preparación
Código ML: G XGZ66331 Código universal: 779219 7070517
SKU: 07051
Mix Completo Frutos Secos Mr Nut X Kilo
SUPERMERCADO
Código universal
Código ML: G WNU14510 Código universal:
7792197050212 SKU: 05022
Pistachos C/ Cascara Tostado Y Salados Mr Nut X Medio
Kilo
SUPERMERCADO
Código universal
PRODUCTO UNIDADES IDENTIFICACIÓN INSTRUCCIONES DE PREPARACIÓN
40 • La fecha de vencimiento debe estar impresa en el
empaque primario de cada unidad, ser legible.
45 días desde la cita de envío agendada.
40 • La fecha de vencimiento debe estar impresa en el
empaque primario."""
HOJA2 = """Código ML: YLZ Q20763 Código universal: 779219 7041111
SKU: 4111
Granola Energia Natural X Kilo - Misternut
SUPERMERCADO
Etiquetado
obligatorio
PRODUCTO UNIDADES IDENTIFICACIÓN INSTRUCCIONES DE PREPARACIÓN
105 • La fecha de vencimiento debe estar impresa."""
TEXTO = HOJA1 + '\f' + HOJA2


class TestParser(unittest.TestCase):
    def test_lee_numero_productos_y_unidades(self):
        r = m.parsear_texto(TEXTO)
        self.assertEqual(r['numero_ml'], '78889570')
        self.assertEqual([(p['codigo_ml'], p['sku'], p['unidades']) for p in r['productos']],
                         [('GXGZ66331', '07051', 40), ('GWNU14510', '05022', 40), ('YLZQ20763', '4111', 105)])

    def test_titulo_en_dos_renglones(self):
        r = m.parsear_texto(TEXTO)
        self.assertEqual(r['productos'][1]['titulo'], 'Pistachos C/ Cascara Tostado Y Salados Mr Nut X Medio Kilo')

    def test_las_cifras_de_las_instrucciones_no_se_cuentan_como_unidades(self):
        r = m.parsear_texto(TEXTO)
        self.assertEqual(sum(p['unidades'] for p in r['productos']), 185)

    def test_si_el_total_no_cierra_no_carga(self):
        with self.assertRaises(m.PdfEnvioError):
            m.parsear_texto(TEXTO.replace('Total de unidades: 185', 'Total de unidades: 999'))

    def test_pdf_que_no_es_de_ml(self):
        with self.assertRaises(m.PdfEnvioError):
            m.parsear_texto('Factura A 0001-00000012')

    def test_archivo_que_no_es_pdf(self):
        with self.assertRaises(m.PdfEnvioError):
            m.extraer_texto(b'esto no es un pdf')


class TestEmparejar(unittest.TestCase):
    FILAS = [
        {'id': 1, 'inventory_id': 'GXGZ66331', 'sku': '07051', 'title': 'Mix'},
        {'id': 2, 'inventory_id': 'OTRO1', 'sku': '04111', 'title': 'Granola'},
        {'id': 3, 'inventory_id': 'GXGZ66331', 'sku': '07051', 'title': 'Mix (premium)'},
    ]

    def test_por_codigo_y_por_sku_sin_ceros(self):
        prods = [{'codigo_ml': 'GXGZ66331', 'sku': '07051', 'unidades': 40},
                 {'codigo_ml': 'YLZQ20763', 'sku': '4111', 'unidades': 105},
                 {'codigo_ml': 'NOEXISTE', 'sku': '999', 'unidades': 1}]
        ok, falta = m.emparejar_productos(prods, self.FILAS)
        self.assertEqual([p['fila']['id'] for p in ok], [1, 2])
        self.assertEqual(len(falta), 1)

    def test_publicaciones_hermanas_no_duplican(self):
        ok, _ = m.emparejar_productos([{'codigo_ml': 'GXGZ66331', 'sku': '07051', 'unidades': 40}], self.FILAS)
        self.assertEqual(len(ok), 1)


if __name__ == '__main__':
    unittest.main()
