"""Proyección a la fecha de ingreso de la colecta. Sin base ni ML.
Uso:  python backend/test_proyeccion.py
"""
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proyeccion as p  # noqa: E402

HOY = date(2026, 10, 16)


class TestDiasHastaIngreso(unittest.TestCase):
    def test_con_fecha_de_llegada_usa_esa_fecha(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, date(2026, 10, 23), 5, 2), 7)

    def test_sin_fecha_usa_preparacion_mas_flete(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, None, 5, 2), 7)
        self.assertEqual(p.dias_hasta_ingreso(None, HOY, None, 5, 2), 7)

    def test_fecha_pasada_no_da_dias_negativos(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, date(2026, 10, 10), 5, 2), 0)

    def test_en_transito_solo_flete(self):
        self.assertEqual(p.dias_hasta_ingreso('in_transit', HOY, date(2026, 10, 30), 5, 2), 2)

    def test_en_recepcion_un_dia(self):
        self.assertEqual(p.dias_hasta_ingreso('in_reception', HOY, None, 5, 2), 1)


class TestProyeccion(unittest.TestCase):
    def test_stock_al_ingreso_nunca_es_negativo(self):
        # 10 u. hoy, 3 por día, 7 días de espera: se agota al día 4 y llega a 0, no a -11.
        self.assertEqual(p.stock_al_ingreso(10, 3, 7), 0)

    def test_stock_al_ingreso_descuenta_lo_vendido(self):
        self.assertEqual(p.stock_al_ingreso(100, 3, 7), 79)

    def test_cobertura_post_colecta(self):
        # 0 en Full al ingreso + 90 u. de colecta, 3 por día = 30 días.
        self.assertEqual(p.cobertura_post_colecta(10, 3, 7, 90), 30.0)

    def test_cobertura_sin_ventas_es_none(self):
        self.assertIsNone(p.cobertura_post_colecta(10, 0, 7, 90))

    def test_sugerido_cuenta_desde_el_ingreso(self):
        # objetivo 30 días a 3/día = 90; al ingreso quedan 0; nada en camino: mandar 90.
        self.assertEqual(p.sugerido_al_ingreso(10, 3, 7, 0, 30), 90)
        # con 40 ya en la colecta faltan 50.
        self.assertEqual(p.sugerido_al_ingreso(10, 3, 7, 40, 30), 50)

    def test_sugerido_no_es_negativo(self):
        self.assertEqual(p.sugerido_al_ingreso(500, 1, 7, 100, 30), 0)

    def test_sugerido_sin_ventas_es_cero(self):
        self.assertEqual(p.sugerido_al_ingreso(10, 0, 7, 0, 30), 0)


class TestAvisoAjuste(unittest.TestCase):
    def test_sin_colecta_no_avisa(self):
        self.assertIsNone(p.aviso_ajuste(10, 3, 7, 0, 30))

    def test_colecta_suficiente_no_avisa(self):
        self.assertIsNone(p.aviso_ajuste(10, 3, 7, 90, 30))

    def test_colecta_corta_sugiere_cuanto_preparar(self):
        # 100 u. a 4,3/día cubren ~23 días de 30: conviene preparar 129 (30*4.3).
        self.assertEqual(p.aviso_ajuste(0, 4.3, 7, 100, 30), 129)

    def test_leve_faltante_no_molesta(self):
        # 26 de 30 días (87%) está dentro de la tolerancia.
        self.assertIsNone(p.aviso_ajuste(0, 1.0, 7, 26, 30))


class TestCuentaRegresiva(unittest.TestCase):
    def test_limite_es_el_dia_anterior_a_las_9_40_de_buenos_aires(self):
        lim = p.limite_edicion(date(2026, 10, 23))
        self.assertEqual((lim.year, lim.month, lim.day, lim.hour, lim.minute), (2026, 10, 22, 9, 40))
        self.assertEqual(lim.utcoffset().total_seconds(), -3 * 3600)

    def test_faltan_dos_dias_y_tres_horas(self):
        ahora = datetime(2026, 10, 20, 6, 40, tzinfo=p.HORA_BA)
        r = p.cuenta_regresiva(date(2026, 10, 23), ahora)
        self.assertTrue(r['abierta'])
        self.assertEqual(r['segundos_restantes'], (2 * 24 + 3) * 3600)

    def test_despues_de_las_9_40_queda_cerrada(self):
        ahora = datetime(2026, 10, 22, 9, 41, tzinfo=p.HORA_BA)
        r = p.cuenta_regresiva(date(2026, 10, 23), ahora)
        self.assertFalse(r['abierta'])
        self.assertEqual(r['segundos_restantes'], 0)

    def test_justo_a_las_9_40_ya_no_alcanza(self):
        ahora = datetime(2026, 10, 22, 9, 40, tzinfo=p.HORA_BA)
        self.assertFalse(p.cuenta_regresiva(date(2026, 10, 23), ahora)['abierta'])


if __name__ == '__main__':
    unittest.main()
