"""Aviso de suba de ventas que pone en riesgo el stock. Sin base, ni WhatsApp, ni mail.
Uso:  python backend/test_cambio_tasa.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cambio_tasa as c  # noqa: E402


class TestEvaluar(unittest.TestCase):
    """Primer filtro: la venta se aceleró de forma notoria."""

    def test_ritmo_estable_no_avisa(self):
        self.assertIsNone(c.evaluar(14, 60))

    def test_una_baja_nunca_avisa(self):
        # antes 2/día, ahora 0,7/día: no hay riesgo de quedarse sin stock
        self.assertIsNone(c.evaluar(5, 51))

    def test_suba_notoria(self):
        r = c.evaluar(21, 44)  # antes 1/día, ahora 3/día
        self.assertEqual((r["sentido"], r["pct"]), ("suba", 200))

    def test_suba_chica_no_avisa(self):
        self.assertIsNone(c.evaluar(17, 60))  # de 2 a 2,4 por día (+21 %)

    def test_suba_desde_cero(self):
        r = c.evaluar(8, 8)
        self.assertEqual((r["sentido"], r["pct"]), ("suba", None))

    def test_sin_stock_no_avisa(self):
        self.assertIsNone(c.evaluar(21, 44, stock=0))

    def test_pocas_ventas_es_ruido(self):
        self.assertIsNone(c.evaluar(3, 4))

    def test_dias_sin_stock_no_cuentan_como_suba(self):
        # vendió 7 en 3 días con stock = 2,3/día, igual que antes
        self.assertIsNone(c.evaluar(7, 53, sin7=4, sin30=4))

    def test_pocos_dias_con_stock_no_alcanzan(self):
        self.assertIsNone(c.evaluar(20, 20, sin7=5, sin30=5))


class TestRiesgo(unittest.TestCase):
    """Segundo filtro: la suba rompe lo previsto."""

    def test_suba_que_igual_alcanza_no_avisa(self):
        # 100 u., ritmo de 1 a 2 por día, reponer lleva 10 días: sobra
        self.assertIsNone(c.riesgo(100, 1.0, 2.0, 0, 0, 10))

    def test_sin_colecta_se_queda_sin_stock_antes_de_poder_reponer(self):
        # 15 u.: a 1/día duran 15 días (alcanza para los 10 de reposición); a 3/día duran 5
        r = c.riesgo(15, 1.0, 3.0, 0, 0, 10)
        self.assertEqual((r["causa"], r["dias_stock"]), ("quiebre", 5.0))

    def test_con_colecta_el_stock_no_llega_a_la_fecha_de_ingreso(self):
        # 20 u., la colecta (15 u.) entra en 12 días: a 1/día alcanza, a 3/día se acaba en 6,7 días
        r = c.riesgo(20, 1.0, 3.0, 15, 12, 10)
        self.assertEqual(r["causa"], "quiebre")
        self.assertEqual(r["dias_ingreso"], 12)

    def test_la_colecta_llega_pero_las_15_unidades_no_alcanzan(self):
        # 10 u., entra en 5 días con 15 u.: a 1/día cubre 20 días; a 3/día, (0+15)/3 = 5 días (< 10 que lleva reponer)
        r = c.riesgo(15, 1.0, 3.0, 15, 5, 10)
        self.assertEqual(r["causa"], "colecta_corta")
        self.assertEqual(r["dias_stock"], 5.0)

    def test_si_ya_estaba_mal_antes_no_es_culpa_de_la_suba(self):
        # a 1/día ya se acababa en 5 días (< 10): eso lo dicen las alertas de stock de siempre
        self.assertIsNone(c.riesgo(5, 1.0, 3.0, 0, 0, 10))

    def test_antes_sin_ventas_y_ahora_si(self):
        r = c.riesgo(15, 0.0, 3.0, 0, 0, 10)
        self.assertEqual(r["causa"], "quiebre")


class TestTextos(unittest.TestCase):
    CAMBIO = {"gk": "abc123", "sentido": "suba", "antes": 1.0, "ahora": 3.0, "pct": 200, "item_id": "MLA123",
              "variation_id": "", "sku": "ABC-1", "titulo": "Funda de silicona", "stock": 40,
              "causa": "quiebre", "dias_stock": 5.0, "dias_ingreso": 12, "entrante": 15}

    def test_whatsapp_explica_el_riesgo(self):
        t = c.texto_whatsapp([self.CAMBIO], "https://x")
        for parte in ("Funda de silicona", "MLA123", "SKU ABC-1", "ahora vende 3,0 por día (antes 1,0)",
                      "dura 5,0 días", "llega en 12", "15 unidades", "próxima colecta"):
            self.assertIn(parte, t)

    def test_panel_ida_y_vuelta(self):
        reg = c._registro_panel(self.CAMBIO)
        a = c.texto_panel(reg)
        self.assertEqual((a["sentido"], a["sku"], a["stock"], a["revertido"]), ("suba", "ABC-1", 40, False))
        self.assertIn("te quedás sin stock antes", a["detalle"])
        self.assertLess(len(reg), 250)

    def test_lo_guardado_se_reconstruye_para_mandar_despues(self):
        d = c._desde_registro(c._clave(self.CAMBIO), c._registro_panel(self.CAMBIO))
        self.assertEqual((d["item_id"], d["causa"], d["entrante"]), ("MLA123", "quiebre", 15))
        self.assertEqual(c._clave(d), c._clave(self.CAMBIO))
        self.assertIsNone(c._desde_registro("x:suba", "roto"))

    def test_reversion_se_muestra_como_tal(self):
        a = c.texto_panel(c._registro_panel(self.CAMBIO, revertido=True))
        self.assertTrue(a["revertido"])
        self.assertIn("se revirtió", a["detalle"])

    def test_avisos_del_primer_formato_siguen_leyendose(self):
        a = c.texto_panel('{"s":"baja","a":2.0,"n":0.7,"p":-65,"sku":"X","st":9,"t":"Algo","i":"MLA1"}')
        self.assertIn("bajó", a["detalle"])

    def test_aviso_abierto_hasta_que_se_revierte(self):
        f = lambda i, k: {"id": i, "item_id": k, "message": "{}", "sent_at": None}
        filas = [f(1, "g1:suba"), f(2, "g2:suba"), f(3, "g1:rev-suba")]
        self.assertEqual(set(c._activos(filas)), {"g2:suba"})
        filas.append(f(4, "g1:suba"))
        self.assertEqual(c._activos(filas)["g1:suba"]["id"], 4)

    def test_panel_con_registro_roto_se_ignora(self):
        self.assertIsNone(c.texto_panel("no es json"))


if __name__ == "__main__":
    unittest.main()
