"""Lo que informa Mercado Libre: partes puras, sin red ni base.
Uso:  python backend/test_ml_reposicion.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ml_reposicion as m  # noqa: E402

RESPUESTA = {
    "stock": {"total_stock": 310, "shipping_urgency": "THIS_WEEK"},
    "recommendation": {"recommendation_type": "REPLENISH", "suggested_quantity": {"type": "exact", "value": 606}},
    "sales": {
        "sales_totals": {"period": "30DAYS", "units_sold": [{"full": 524}]},
        "sales_history": [{"units_sold": 63}, {"units_sold": 178}, {"units_sold": 128}, {"units_sold": 107},
                          {"units_sold": 110}, {"units_sold": 99}],
    },
}


class TestInterpretar(unittest.TestCase):
    def test_respuesta_completa(self):
        d = m.interpretar(RESPUESTA)
        self.assertEqual((d["unidades_30d"], d["sugerido"], d["urgencia"], d["stock_total"]), (524, 606, "THIS_WEEK", 310))
        self.assertEqual(d["semanas"], "63,178,128,107,110")  # solo las últimas 5

    def test_respuesta_vacia_no_rompe(self):
        d = m.interpretar({})
        self.assertEqual((d["unidades_30d"], d["sugerido"], d["semanas"]), (0, None, ""))

    def test_sin_recomendacion(self):
        r = dict(RESPUESTA, recommendation={"suggested_quantity": {"type": "range"}})
        self.assertIsNone(m.interpretar(r)["sugerido"])


class TestParaPanel(unittest.TestCase):
    def test_ritmo_por_dia(self):
        fila = {"unidades_30d": 524, "semanas": "63,178,128,107,110", "sugerido": 606, "urgencia": "THIS_WEEK"}
        p = m.para_panel(fila)
        self.assertEqual((p["vpd_30"], p["vpd_ultima_semana"]), (17.5, 9.0))
        self.assertEqual(p["semanas"], [9.0, 25.4, 18.3, 15.3, 15.7])

    def test_sin_datos(self):
        self.assertIsNone(m.para_panel(None))
        self.assertIsNone(m.para_panel({"unidades_30d": None}))

    def test_sin_semanas(self):
        p = m.para_panel({"unidades_30d": 30, "semanas": ""})
        self.assertEqual((p["vpd_30"], p["vpd_ultima_semana"]), (1.0, None))


if __name__ == "__main__":
    unittest.main()
