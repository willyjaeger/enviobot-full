"""Aviso de baja de ventas que deja stock de más. Sin base, ni WhatsApp, ni mail.
Uso:  python backend/test_cambio_tasa.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cambio_tasa as c  # noqa: E402


def est(base, ref, confianza="alta", ultimos7=None):
    return {"base": base, "referencia": ref, "confianza": confianza, "ultimos7": base if ultimos7 is None else ultimos7}


class TestEvaluarBaja(unittest.TestCase):
    """El caso de las nueces: se planificó con 14 por día, hoy vende 6 y hay 310 en Full."""

    def test_baja_sostenida_con_stock_de_mas_avisa(self):
        a, medible = c.evaluar_baja(est(6, 14), stock=310, entrante=0, objetivo=30)
        self.assertTrue(medible)
        self.assertEqual((a["sentido"], a["antes"], a["ahora"], a["pct"]), ("baja", 14.0, 6.0, -57))
        self.assertEqual(a["dias_stock"], 51.7)
        self.assertEqual(a["exceso"], 130)  # 310 - 6 x 30

    def test_cuenta_lo_que_viene_en_camino(self):
        a, _ = c.evaluar_baja(est(6, 20), stock=100, entrante=555, objetivo=30)
        self.assertEqual(a["exceso"], 475)

    def test_baja_chica_no_avisa(self):
        a, medible = c.evaluar_baja(est(11, 14), stock=310, entrante=0, objetivo=30)
        self.assertEqual((a, medible), (None, True))

    def test_baja_que_igual_deja_el_stock_en_orden_no_avisa(self):
        # vende la mitad, pero hay poco stock: sigue alcanzando para menos que el umbral (45 días)
        a, medible = c.evaluar_baja(est(5, 10), stock=100, entrante=0, objetivo=30)
        self.assertEqual((a, medible), (None, True))

    def test_si_ya_sobraba_antes_de_la_baja_lo_dice_el_panel(self):
        # con el ritmo de referencia ya había 100 días de stock: no es culpa de la baja
        a, _ = c.evaluar_baja(est(6, 8), stock=800, entrante=0, objetivo=30)
        self.assertIsNone(a)

    def test_pocas_unidades_de_mas_no_valen_un_aviso(self):
        a, _ = c.evaluar_baja(est(0.2, 0.5), stock=10, entrante=0, objetivo=1)
        self.assertIsNone(a)

    def test_sobrante_de_pocos_dias_no_avisa(self):
        # 59 unidades a 2,6 por día: 23 días de stock, apenas 8 días por encima del objetivo
        a, _ = c.evaluar_baja(est(2.6, 4.1), stock=59, entrante=0, objetivo=15)
        self.assertIsNone(a)

    def test_suba_de_ventas_no_avisa(self):
        a, medible = c.evaluar_baja(est(30, 10), stock=100, entrante=0, objetivo=30)
        self.assertEqual((a, medible), (None, True))

    def test_sin_stock_o_sin_historia_no_se_puede_medir(self):
        self.assertEqual(c.evaluar_baja(est(6, 14), stock=0, entrante=500, objetivo=30), (None, False))
        self.assertEqual(c.evaluar_baja(est(6, 14, confianza="baja"), stock=310, entrante=0, objetivo=30), (None, False))
        self.assertEqual(c.evaluar_baja(est(6, None), stock=310, entrante=0, objetivo=30), (None, False))

    def test_zona_gris_no_se_da_por_revertida(self):
        # sobrestock con umbral 45: a 7 por día son 44 días (justo debajo, pero arriba de 36 = 80 % del umbral)
        a, medible = c.evaluar_baja(est(7, 14), stock=308, entrante=0, objetivo=30)
        self.assertEqual((a, medible), (None, False))

    def test_dejo_de_vender(self):
        a, _ = c.evaluar_baja(est(0, 14), stock=310, entrante=0, objetivo=30)
        self.assertEqual(a["dias_stock"], 999.0)


class TestTextos(unittest.TestCase):
    CAMBIO = {"gk": "abc123", "sentido": "baja", "antes": 14.0, "ahora": 6.0, "pct": -57, "item_id": "MLA123",
              "variation_id": "", "sku": "ABC-1", "titulo": "Nueces peladas", "stock": 310,
              "causa": "exceso", "dias_stock": 51.7, "dias_ingreso": 0, "entrante": 0, "objetivo": 30, "en_prep": 0, "exceso": 130}

    def test_whatsapp_explica_el_exceso(self):
        t = c.texto_whatsapp([self.CAMBIO], "https://x")
        for parte in ("bajó la venta de 1 producto", "Nueces peladas", "MLA123", "SKU ABC-1",
                      "ahora vende 6,0 por día (antes 14,0)", "310 unidades", "52 días", "tu objetivo es 30",
                      "no mandar más", "ajustar la próxima colecta"):
            self.assertIn(parte, t)

    def test_con_colecta_en_preparacion_dice_que_se_puede_achicar(self):
        cambio = dict(self.CAMBIO, en_prep=555, entrante=555)
        t = c.texto_whatsapp([cambio])
        self.assertIn("achicar la colecta en preparación (555 unidades)", t)
        self.assertIn("865 unidades", t)

    def test_panel_ida_y_vuelta(self):
        reg = c._registro_panel(self.CAMBIO)
        a = c.texto_panel(reg)
        self.assertEqual((a["sentido"], a["sku"], a["stock"], a["revertido"]), ("baja", "ABC-1", 310, False))
        self.assertIn("(-57 %)", a["detalle"])
        self.assertIn("tu objetivo es 30", a["detalle"])
        self.assertLess(len(reg), 250)

    def test_lo_guardado_se_reconstruye_para_mandar_despues(self):
        d = c._desde_registro(c._clave(self.CAMBIO), c._registro_panel(self.CAMBIO))
        self.assertEqual((d["item_id"], d["causa"], d["objetivo"]), ("MLA123", "exceso", 30))
        self.assertEqual(c._clave(d), c._clave(self.CAMBIO))
        self.assertIsNone(c._desde_registro("x:baja", "roto"))

    def test_reversion_se_muestra_como_tal(self):
        a = c.texto_panel(c._registro_panel(self.CAMBIO, revertido=True))
        self.assertTrue(a["revertido"])
        self.assertIn("ya no te sobra stock", a["detalle"])

    def test_avisos_de_suba_anteriores_siguen_leyendose(self):
        viejo = {"gk": "g", "sentido": "suba", "antes": 1.0, "ahora": 3.0, "pct": 200, "item_id": "MLA1", "sku": "X",
                 "titulo": "Algo", "stock": 5, "causa": "quiebre", "dias_stock": 5.0, "dias_ingreso": 12, "entrante": 0}
        a = c.texto_panel(c._registro_panel(viejo))
        self.assertIn("te quedás sin stock antes", a["detalle"])
        self.assertIn("ya no hay riesgo", c.texto_panel(c._registro_panel(viejo, revertido=True))["detalle"])

    def test_avisos_del_primer_formato_siguen_leyendose(self):
        a = c.texto_panel('{"s":"baja","a":2.0,"n":0.7,"p":-65,"sku":"X","st":9,"t":"Algo","i":"MLA1"}')
        self.assertIn("bajó", a["detalle"])

    def test_aviso_abierto_hasta_que_se_revierte(self):
        f = lambda i, k: {"id": i, "item_id": k, "message": "{}", "sent_at": None}
        filas = [f(1, "g1:baja"), f(2, "g2:baja"), f(3, "g1:rev-baja")]
        self.assertEqual(set(c._activos(filas)), {"g2:baja"})
        filas.append(f(4, "g1:baja"))
        self.assertEqual(c._activos(filas)["g1:baja"]["id"], 4)

    def test_panel_con_registro_roto_se_ignora(self):
        self.assertIsNone(c.texto_panel("no es json"))


class _Cur:
    def __init__(self, filas):
        self.filas, self.borrados = filas, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.sql = sql
        if sql.strip().startswith("DELETE") and "id IN" in sql:
            self.borrados += list(params[1:])

    def fetchall(self):
        return self.filas


class _Conn:
    def __init__(self, filas):
        self.cur = _Cur(filas)

    def cursor(self):
        return self.cur


class TestLimpieza(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timedelta
        ahora = datetime.utcnow()
        f = lambda i, k, dias: {"id": i, "item_id": k, "message": "{}", "sent_at": ahora - timedelta(days=dias)}
        self.filas = [
            f(1, "g1:baja", 20), f(2, "g1:rev-baja", 15),   # cerrado y viejo: se borra
            f(3, "g2:baja", 20),                              # sigue abierto aunque es viejo: se conserva
            f(4, "g3:baja", 3), f(5, "g3:rev-baja", 2),      # cerrado pero reciente: se ve y se conserva
        ]

    def test_se_borra_solo_lo_cerrado_y_viejo(self):
        conn = _Conn(self.filas)
        self.assertEqual(c.limpiar(conn, 1), 2)
        self.assertEqual(sorted(conn.cur.borrados), [1, 2])

    def test_la_ventana_muestra_la_ultima_semana_y_lo_que_sigue_abierto(self):
        ids = [f["id"] for f in c.avisos_visibles(_Conn(self.filas), 1)]
        self.assertEqual(ids, [5, 4, 3])  # lo más nuevo primero


if __name__ == "__main__":
    unittest.main()
