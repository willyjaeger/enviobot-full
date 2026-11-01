"""Ritmo de venta limpio: sin base ni ML.
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
    def test_ritmo_parejo(self):
        e = d.estimar(serie([10] * 40), HOY)
        self.assertEqual((e["bajo"], e["base"], e["alto"]), (10.0, 10.0, 10.0))
        self.assertEqual(e["tendencia"], "estable")
        self.assertEqual(e["confianza"], "alta")

    def test_un_pico_suelto_no_infla(self):
        v = [10] * 40
        v[30] = 120
        e = d.estimar(serie(v), HOY)
        self.assertLess(e["base"], 11)

    def test_rebote_tras_quiebre_se_descarta(self):
        # 8/día normal, dos días en cero (quiebre) y una semana de rebote con 50, 40, 33, 28, 20, 12, 9
        v = [8, 9, 7, 8, 9, 8, 7] * 4 + [0, 0, 50, 40, 33, 28, 20, 12, 9, 8, 7, 8, 9, 6]
        e = d.estimar(serie(v), HOY)
        self.assertEqual(e["descartados"]["rebote"], 6)
        self.assertEqual(e["descartados"]["sin_stock"], 2)
        self.assertLess(e["base"], 10)
        # el cálculo de siempre da bastante más
        self.assertGreater(e["vpd_crudo_30"], e["base"] + 2)

    def test_quiebre_conocido_por_stock_diario(self):
        # un solo día en cero no alcanza para inferirlo, pero stock_daily dice que no había stock
        v = [8] * 30 + [0] + [8] * 6
        cero = HOY - timedelta(days=7)
        e = d.estimar(serie(v), HOY, sin_stock=[cero])
        self.assertEqual(e["descartados"]["sin_stock"], 1)

    def test_cero_aislado_no_es_quiebre(self):
        v = [8] * 30
        v[10] = 0
        e = d.estimar(serie(v), HOY)
        self.assertEqual(e["descartados"]["sin_stock"], 0)

    def test_tendencia_a_la_baja_sostenida(self):
        e = d.estimar(serie([20] * 28 + [8] * 7), HOY)
        self.assertEqual(e["tendencia"], "baja")
        self.assertLess(e["bajo"], e["base"] + 0.001)

    def test_escenarios_ordenados(self):
        v = [5, 12, 8, 15, 6, 9, 11] * 6
        e = d.estimar(serie(v), HOY)
        self.assertLessEqual(e["bajo"], e["base"])
        self.assertLessEqual(e["base"], e["alto"])

    def test_poca_historia_baja_la_confianza(self):
        e = d.estimar(serie([3] * 6), HOY)
        self.assertEqual(e["confianza"], "baja")

    def test_sin_ventas(self):
        e = d.estimar({}, HOY)
        self.assertEqual(e["base"], 0.0)


class TestPedido(unittest.TestCase):
    def test_dias_de_stock(self):
        self.assertEqual(d.dias_de_stock(310, 10), 31.0)
        self.assertIsNone(d.dias_de_stock(310, 0))

    def test_pedido_cubre_lo_que_falta(self):
        # 30 días a 10/día = 300; hay 100 y no hay nada en camino
        self.assertEqual(d.unidades_a_pedir(10, 100, 0, 30), 200)

    def test_la_espera_se_descuenta(self):
        # a 10/día, en 5 días quedan 50 en vez de 100
        self.assertEqual(d.unidades_a_pedir(10, 100, 0, 30, dias_hasta_ingreso=5), 250)

    def test_con_stock_de_sobra_no_pide(self):
        self.assertEqual(d.unidades_a_pedir(2, 500, 0, 30), 0)


if __name__ == "__main__":
    unittest.main()
