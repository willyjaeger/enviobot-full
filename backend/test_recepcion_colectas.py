"""Marcar solas las colectas recibidas. Sin base: un cursor de mentira.
Uso:  python backend/test_recepcion_colectas.py
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recepcion_colectas as r  # noqa: E402

HOY = date(2026, 10, 19)


class _Cur:
    def __init__(self, colectas, stock, items):
        self.colectas, self.stock, self.items = colectas, stock, items
        self.escrituras, self._res = [], []

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE"):
            self.escrituras.append((sql, params))
        elif "FROM inbound_shipments" in sql:
            self._res = self.colectas
        elif "FROM full_items" in sql:
            self._res = [{"sku": k, "n": v} for k, v in self.stock.items()]
        else:
            self._res = self.items

    def fetchall(self): return self._res


class _Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur


def _correr(estado_ml, stock):
    cur = _Cur([{"id": 1, "shipment_code": "ML-1", "pickup_date": HOY, "meli_inbound_status": estado_ml}],
               stock, [{"sku": "A1", "units_to_send": 100}, {"sku": "B2", "units_to_send": 50}])
    return r.actualizar(_Conn(cur), 45, hoy=HOY), cur.escrituras


class TestRecepcion(unittest.TestCase):
    def test_con_stock_en_proceso_se_marca_recibida_con_la_fecha_de_hoy(self):
        res, esc = _correr(None, {"A1": 57})
        self.assertEqual(res, {"recibidas": 1, "cerradas": 0})
        self.assertEqual(esc[0][1], ("received", HOY, 1))

    def test_sin_stock_en_proceso_no_hace_nada(self):
        res, esc = _correr(None, {"A1": 0})
        self.assertEqual(res, {"recibidas": 0, "cerradas": 0})
        self.assertEqual(esc, [])

    def test_ya_recibida_y_sin_stock_en_proceso_se_cierra(self):
        res, esc = _correr("received", {"A1": 0})
        self.assertEqual(res, {"recibidas": 0, "cerradas": 1})
        self.assertEqual(esc[0][1], ("delivered", 1))

    def test_ya_recibida_con_stock_en_proceso_sigue_igual(self):
        res, esc = _correr("received", {"A1": 20})
        self.assertEqual(res, {"recibidas": 0, "cerradas": 0})
        self.assertEqual(esc, [])

    def test_el_stock_de_otros_productos_no_cuenta(self):
        res, esc = _correr(None, {"ZZ": 999})
        self.assertEqual(res["recibidas"], 0)


if __name__ == "__main__":
    unittest.main()
