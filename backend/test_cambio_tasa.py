"""Cambio notorio en el ritmo de venta. Sin base, ni WhatsApp, ni mail.
Uso:  python backend/test_cambio_tasa.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cambio_tasa as c  # noqa: E402


class TestEvaluar(unittest.TestCase):
    def test_ritmo_estable_no_avisa(self):
        # 2 por día toda la vida: v7=14, v30=60
        self.assertIsNone(c.evaluar(14, 60))

    def test_baja_notoria(self):
        # antes 2/día (46 en 23 días), ahora 0,7/día (5 en 7 días)
        r = c.evaluar(5, 51)
        self.assertEqual(r["sentido"], "baja")
        self.assertEqual(r["antes"], 2.0)
        self.assertLess(r["pct"], -40)

    def test_suba_notoria(self):
        # antes 1/día (23), ahora 3/día (21)
        r = c.evaluar(21, 44)
        self.assertEqual(r["sentido"], "suba")
        self.assertEqual(r["pct"], 200)

    def test_suba_desde_cero(self):
        r = c.evaluar(8, 8)
        self.assertEqual((r["sentido"], r["pct"]), ("suba", None))

    def test_sin_stock_no_avisa(self):
        self.assertIsNone(c.evaluar(0, 46, stock=0))

    def test_pocas_ventas_es_ruido(self):
        # de 1 a 0 unidades por semana: no es tendencia
        self.assertIsNone(c.evaluar(0, 3))
        self.assertIsNone(c.evaluar(3, 4))

    def test_dias_sin_stock_no_cuentan_como_baja(self):
        # vendió 7 en 7 días pero 4 días sin stock: tuvo 3 con stock => 2,3/día, igual que antes
        self.assertIsNone(c.evaluar(7, 53, sin7=4, sin30=4))

    def test_pocos_dias_con_stock_no_alcanzan(self):
        self.assertIsNone(c.evaluar(1, 50, sin7=5, sin30=5))


class TestTextos(unittest.TestCase):
    CAMBIO = {"gk": "abc123", "sentido": "baja", "antes": 2.0, "ahora": 0.7, "pct": -65, "item_id": "MLA123", "variation_id": "",
              "sku": "ABC-1", "titulo": "Funda de silicona", "stock": 40}

    def test_whatsapp_incluye_producto_publicacion_y_sku(self):
        t = c.texto_whatsapp([self.CAMBIO], "https://x")
        for parte in ("Funda de silicona", "MLA123", "SKU ABC-1", "bajó de 2,0 a 0,7", "-65 %", "próxima colecta"):
            self.assertIn(parte, t)

    def test_panel_ida_y_vuelta(self):
        a = c.texto_panel(c._registro_panel(self.CAMBIO))
        self.assertEqual((a["sentido"], a["sku"], a["stock"]), ("baja", "ABC-1", 40))
        self.assertIn("bajó", a["detalle"])
        self.assertLess(len(c._registro_panel(self.CAMBIO)), 250)

    def test_lo_guardado_se_reconstruye_para_mandar_despues(self):
        d = c._desde_registro(c._clave(self.CAMBIO), c._registro_panel(self.CAMBIO))
        self.assertEqual((d["item_id"], d["sentido"], d["sku"]), ("MLA123", "baja", "ABC-1"))
        self.assertEqual(c._clave(d), c._clave(self.CAMBIO))
        self.assertIsNone(c._desde_registro("x:y:baja", "roto"))

    def test_reversion_se_muestra_como_tal(self):
        rev = dict(self.CAMBIO, ahora=1.9)
        a = c.texto_panel(c._registro_panel(rev, revertido=True))
        self.assertTrue(a["revertido"])
        self.assertIn("se revirtió", a["detalle"])
        self.assertEqual(a["item_id"], "MLA123")

    def test_aviso_abierto_hasta_que_se_revierte(self):
        f = lambda i, k: {"id": i, "item_id": k, "message": "{}", "sent_at": None}
        filas = [f(1, "g1:baja"), f(2, "g2:suba"), f(3, "g1:rev-baja")]
        self.assertEqual(set(c._activos(filas)), {"g2:suba"})
        # si vuelve a bajar después de revertirse, es un aviso nuevo
        filas.append(f(4, "g1:baja"))
        self.assertEqual(c._activos(filas)["g1:baja"]["id"], 4)

    def test_panel_con_registro_roto_se_ignora(self):
        self.assertIsNone(c.texto_panel("no es json"))


if __name__ == "__main__":
    unittest.main()
