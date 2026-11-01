"""Historial de ventas por día: partes puras, sin base ni ML.
Uso:  python backend/test_ventas_historial.py
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ventas_historial as v  # noqa: E402


def orden(fecha, item, qty, var=None, status="paid"):
    return {"status": status, "date_created": fecha,
            "order_items": [{"item": {"id": item, "variation_id": var}, "quantity": qty}]}


class TestAcumular(unittest.TestCase):
    def test_suma_por_dia_en_hora_argentina(self):
        # 02:30 UTC del 2 es la noche del 1 en Buenos Aires
        o = [orden("2026-10-02T02:30:00.000+00:00", "MLA1", 3), orden("2026-10-01T15:00:00.000-03:00", "MLA1", 2)]
        r = v.acumular_ordenes(o, "MLA1")
        self.assertEqual(dict(r[""]), {date(2026, 10, 1): 5})

    def test_cancelada_no_cuenta(self):
        self.assertEqual(len(v.acumular_ordenes([orden("2026-10-01T10:00:00.000-03:00", "MLA1", 1, status="cancelled")], "MLA1")), 0)

    def test_separa_variaciones_y_otros_items(self):
        o = [orden("2026-10-01T10:00:00.000-03:00", "MLA1", 1, var=11),
             orden("2026-10-01T11:00:00.000-03:00", "MLA1", 2, var=22),
             orden("2026-10-01T12:00:00.000-03:00", "MLA9", 7)]
        r = v.acumular_ordenes(o, "MLA1")
        self.assertEqual((r["11"][date(2026, 10, 1)], r["22"][date(2026, 10, 1)], "" in r), (1, 2, False))


class TestVentana(unittest.TestCase):
    HOY = date(2026, 11, 1)

    def test_primera_vez_baja_todo(self):
        self.assertEqual(v.dias_a_bajar(None, self.HOY), 120)

    def test_al_dia_baja_solo_unos_pocos(self):
        self.assertEqual(v.dias_a_bajar(date(2026, 10, 31), self.HOY), 4)

    def test_tras_un_corte_baja_lo_que_falta(self):
        self.assertEqual(v.dias_a_bajar(date(2026, 10, 21), self.HOY), 14)

    def test_nunca_mas_de_120(self):
        self.assertEqual(v.dias_a_bajar(date(2025, 1, 1), self.HOY), 120)

    def test_semana_empieza_el_lunes(self):
        self.assertEqual(v.lunes(date(2026, 11, 1)), date(2026, 10, 26))  # 1/11/2026 es domingo


if __name__ == "__main__":
    unittest.main()
