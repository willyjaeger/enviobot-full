"""Ritmo de venta con margen: sin base ni ML.
Uso:  python backend/test_demanda.py
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demanda as d  # noqa: E402

HOY = date(2026, 11, 1)


def serie(valores):
    """valores de más viejo a más nuevo; el último es AYER."""
    n = len(valores)
    return {HOY - timedelta(days=n - i): v for i, v in enumerate(valores)}


class TestEstimar(unittest.TestCase):
    def test_ritmo_parejo_no_necesita_margen(self):
        e = d.estimar(serie([10] * 40), HOY)
        self.assertEqual((e["bajo"], e["base"], e["protegido"], e["alto"], e["sigma"]), (10.0, 10.0, 10.0, 10.0, 0.0))
        self.assertEqual((e["tendencia"], e["confianza"]), ("estable", "alta"))

    def test_base_es_el_promedio_de_28_dias(self):
        e = d.estimar(serie([20] * 20 + [10] * 28), HOY)
        self.assertEqual(e["base"], 10.0)

    def test_el_margen_crece_con_la_variacion(self):
        parejo = d.estimar(serie([10] * 40), HOY)
        variable = d.estimar(serie([0, 20] * 20), HOY)  # mismo promedio, mucha más variación
        self.assertEqual(variable["base"], parejo["base"])
        self.assertGreater(variable["protegido"], parejo["protegido"])
        self.assertEqual(variable["protegido"], 15.0)   # 10 + 0,5 x 10
        self.assertEqual(variable["alto"], 20.0)        # 10 + 1 x 10

    def test_escenarios_ordenados(self):
        e = d.estimar(serie([5, 12, 8, 15, 6, 9, 11] * 6), HOY)
        self.assertLessEqual(e["bajo"], e["base"])
        self.assertLessEqual(e["base"], e["protegido"])
        self.assertLessEqual(e["protegido"], e["alto"])

    def test_bajo_sigue_a_la_ultima_semana(self):
        e = d.estimar(serie([20] * 28 + [5] * 7), HOY)
        self.assertEqual(e["ultimos7"], 5.0)
        self.assertEqual(e["bajo"], 5.0)

    def test_dia_sin_stock_confirmado_no_cuenta(self):
        v = [8] * 30 + [0] + [8] * 6
        cero = HOY - timedelta(days=7)
        e = d.estimar(serie(v), HOY, sin_stock=[cero])
        self.assertEqual(e["descartados"]["sin_stock"], 1)
        self.assertEqual(e["base"], 8.0)

    def test_ceros_sin_dato_de_stock_cuentan_como_venta_cero(self):
        # no se inventan quiebres: sin dato de stock un cero es un cero
        e = d.estimar(serie([10] * 30 + [0, 0] + [10] * 5), HOY)
        self.assertEqual(e["descartados"]["sin_stock"], 0)
        self.assertLess(e["base"], 10.0)

    def test_cuenta_los_quiebres(self):
        v = [8] * 40
        sin = [HOY - timedelta(days=n) for n in (5, 4, 20)]
        self.assertEqual(d.estimar(serie(v), HOY, sin_stock=sin)["quiebres"], 2)

    def test_tendencia_a_la_baja_sostenida(self):
        self.assertEqual(d.estimar(serie([20] * 28 + [8] * 7), HOY)["tendencia"], "baja")

    def test_poca_historia_baja_la_confianza(self):
        self.assertEqual(d.estimar(serie([3] * 6), HOY)["confianza"], "baja")

    def test_sin_ventas(self):
        e = d.estimar({}, HOY)
        self.assertEqual((e["base"], e["protegido"]), (0.0, 0.0))

    def test_referencia_son_las_buenas_semanas(self):
        e = d.estimar(serie([10] * 35 + [22, 24, 20, 23, 25, 21, 22] * 2 + [8, 7, 9, 6, 8, 7, 9]), HOY)
        self.assertGreater(e["referencia"], 15)
        self.assertEqual(e["ultimos3"], 8.0)


class TestPedido(unittest.TestCase):
    def test_dias_de_stock(self):
        self.assertEqual(d.dias_de_stock(310, 10), 31.0)
        self.assertIsNone(d.dias_de_stock(310, 0))

    def test_pedido_cubre_lo_que_falta(self):
        self.assertEqual(d.unidades_a_pedir(10, 100, 0, 30), 200)

    def test_la_espera_se_descuenta(self):
        self.assertEqual(d.unidades_a_pedir(10, 100, 0, 30, dias_hasta_ingreso=5), 250)

    def test_con_stock_de_sobra_no_pide(self):
        self.assertEqual(d.unidades_a_pedir(2, 500, 0, 30), 0)


class TestPanel(unittest.TestCase):
    def test_con_historia_planifica_con_el_protegido(self):
        e = d.ritmo_para_panel(serie([0, 20] * 20), HOY, (), 14.0)
        self.assertEqual((e["fuente"], e["vpd"], e["vpd_anterior"]), ("limpio", 15.0, 14.0))

    def test_sin_historia_queda_el_de_siempre(self):
        e = d.ritmo_para_panel({}, HOY, (), 3.0)
        self.assertEqual((e["fuente"], e["vpd"]), ("anterior", 3.0))

    def test_poca_historia_queda_el_de_siempre(self):
        e = d.ritmo_para_panel(serie([5, 5, 5]), HOY, (), 4.0)
        self.assertEqual((e["fuente"], e["vpd"]), ("anterior", 4.0))

    def test_sin_ventas_recientes_no_apaga_un_producto_que_vendia(self):
        e = d.ritmo_para_panel(serie([0] * 12), HOY, (), 5.0)
        self.assertEqual(e["fuente"], "anterior")


if __name__ == "__main__":
    unittest.main()
