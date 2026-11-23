import unittest
from datetime import date

import periodos_sin_stock as p


class TestPeriodos(unittest.TestCase):
    def test_junta_los_dias_seguidos(self):
        r = p.agrupar([date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 10), date(2026, 11, 23)], hoy=date(2026, 11, 23))
        self.assertEqual([(t["desde"], t["hasta"], t["dias"], t["en_curso"]) for t in r],
                         [("2026-11-03", "2026-11-05", 3, False), ("2026-11-10", "2026-11-10", 1, False), ("2026-11-23", "2026-11-23", 1, True)])

    def test_cruza_el_fin_de_mes_y_ignora_repetidos(self):
        r = p.agrupar(["2026-10-31", "2026-11-01", "2026-11-01"])
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["dias"], 2)
        self.assertEqual(p.agrupar([]), [])


if __name__ == "__main__":
    unittest.main()
