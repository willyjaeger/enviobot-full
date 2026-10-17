"""Historial diario de stock del worker: se anota solo con stock real y corrige la velocidad.
Sin base ni ML: conexión de mentira.
Uso:  python backend/test_worker_historial.py
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esquema  # noqa: E402
import worker  # noqa: E402

HOY = date(2026, 10, 16)


class _Cur:
    def __init__(self, hay_tabla=True, sin=(2, 5, 10), falla=False):
        self.hay_tabla, self.sin, self.falla = hay_tabla, sin, falla
        self.sqls = []
        self._ultimo = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        if self.falla and "stock_daily" in sql and "information_schema" not in sql:
            raise RuntimeError("tabla rota")
        self._ultimo = sql
        self.sqls.append(sql)

    def fetchone(self):
        if "information_schema" in self._ultimo:
            return {"COUNT(*)": 1 if self.hay_tabla else 0}
        return {"sin7": self.sin[0], "sin15": self.sin[1], "sin30": self.sin[2]}


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _escribio(cur):
    return any("INSERT INTO stock_daily" in q for q in cur.sqls)


class TestHistorial(unittest.TestCase):
    def setUp(self):
        esquema.olvidar()

    def test_sin_la_tabla_no_hace_nada_y_devuelve_ceros(self):
        cur = _Cur(hay_tabla=False)
        r = worker.registrar_y_contar_dias_sin_stock(_Conn(cur), 1, "MLA1", "", 5, True, HOY)
        self.assertEqual(r, (0, 0, 0))
        self.assertFalse(_escribio(cur))

    def test_con_stock_real_anota_y_cuenta(self):
        cur = _Cur()
        r = worker.registrar_y_contar_dias_sin_stock(_Conn(cur), 1, "MLA1", "", 0, True, HOY)
        self.assertEqual(r, (2, 5, 10))
        self.assertTrue(_escribio(cur))

    def test_si_el_stock_no_vino_de_ml_no_se_anota(self):
        # Si la consulta a ML falló y se usó el stock declarado, un 0 ahí podría ser falso.
        cur = _Cur()
        r = worker.registrar_y_contar_dias_sin_stock(_Conn(cur), 1, "MLA1", "", 0, False, HOY)
        self.assertEqual(r, (2, 5, 10))
        self.assertFalse(_escribio(cur))

    def test_un_error_de_base_no_corta_la_sincronizacion(self):
        cur = _Cur(falla=True)
        r = worker.registrar_y_contar_dias_sin_stock(_Conn(cur), 1, "MLA1", "", 5, True, HOY)
        self.assertEqual(r, (0, 0, 0))

    def test_el_maximo_del_dia_decide_si_hubo_stock(self):
        cur = _Cur()
        worker.registrar_y_contar_dias_sin_stock(_Conn(cur), 1, "MLA1", "", 0, True, HOY)
        insert = [q for q in cur.sqls if "INSERT INTO stock_daily" in q][0]
        self.assertIn("GREATEST(stock_max", insert)
        self.assertIn("LEAST(stock_min", insert)


if __name__ == "__main__":
    unittest.main()
