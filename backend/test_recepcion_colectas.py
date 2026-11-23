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


class TestColectaVencida(unittest.TestCase):
    """Una colecta en transito vieja y sin nada en proceso ya entro: se cierra (no queda 'en camino' para siempre)."""
    def test_retirada_hace_mas_de_7_dias_sin_stock_en_proceso_se_cierra(self):
        fila = {"pickup_date": date(2026, 10, 10), "meli_inbound_status": "picked_up"}
        self.assertEqual(r.decidir(fila, 0, HOY), (None, None, "delivered"))

    def test_retirada_hace_poco_sigue_en_camino(self):
        fila = {"pickup_date": date(2026, 10, 15), "meli_inbound_status": "picked_up"}
        self.assertEqual(r.decidir(fila, 0, HOY), (None, None, None))

    def test_vieja_pero_con_stock_en_proceso_se_marca_recibida(self):
        fila = {"pickup_date": date(2026, 10, 10), "meli_inbound_status": "picked_up"}
        self.assertEqual(r.decidir(fila, 5, HOY), ("received", HOY, None))


class TestIngresoPorStock(unittest.TestCase):
    R = date(2026, 11, 10)

    def test_de_4_a_32_con_30_enviadas_es_recibida(self):
        stock = {date(2026, 11, 10): 4, date(2026, 11, 11): 3, date(2026, 11, 12): 32}
        self.assertEqual(r.ingreso_por_stock(stock, {}, self.R, 30), date(2026, 11, 12))

    def test_las_ventas_no_esconden_la_suba(self):
        stock = {date(2026, 11, 10): 10, date(2026, 11, 11): 10, date(2026, 11, 12): 10}
        ventas = {date(2026, 11, 11): 6, date(2026, 11, 12): 6}
        self.assertEqual(r.ingreso_por_stock(stock, ventas, self.R, 20), date(2026, 11, 12))

    def test_si_solo_baja_no_hay_ingreso(self):
        stock = {date(2026, 11, 10): 10, date(2026, 11, 11): 8, date(2026, 11, 12): 5}
        self.assertIsNone(r.ingreso_por_stock(stock, {}, self.R, 30))

    def test_sin_dato_del_dia_de_retiro_no_afirma_nada(self):
        self.assertIsNone(r.ingreso_por_stock({date(2026, 11, 12): 99}, {}, self.R, 30))

    def test_decidir_cierra_con_la_fecha_real(self):
        fila = {"pickup_date": self.R, "meli_inbound_status": "picked_up"}
        self.assertEqual(r.decidir(fila, 0, HOY, date(2026, 11, 12)), ("received", date(2026, 11, 12), "delivered"))


class TestIngresoPorStock(unittest.TestCase):
    R = date(2026, 11, 10)

    def test_de_4_a_32_con_30_enviadas_es_recibida(self):
        stock = {date(2026, 11, 10): 4, date(2026, 11, 11): 3, date(2026, 11, 12): 32}
        self.assertEqual(r.ingreso_por_stock(stock, {}, self.R, 30), date(2026, 11, 12))

    def test_las_ventas_no_esconden_la_suba(self):
        stock = {date(2026, 11, 10): 10, date(2026, 11, 11): 10, date(2026, 11, 12): 10}
        ventas = {date(2026, 11, 11): 6, date(2026, 11, 12): 6}
        self.assertEqual(r.ingreso_por_stock(stock, ventas, self.R, 20), date(2026, 11, 12))

    def test_si_solo_baja_no_hay_ingreso(self):
        stock = {date(2026, 11, 10): 10, date(2026, 11, 11): 8, date(2026, 11, 12): 5}
        self.assertIsNone(r.ingreso_por_stock(stock, {}, self.R, 30))

    def test_sin_dato_del_dia_de_retiro_no_afirma_nada(self):
        self.assertIsNone(r.ingreso_por_stock({date(2026, 11, 12): 99}, {}, self.R, 30))

    def test_decidir_cierra_con_la_fecha_real(self):
        fila = {"pickup_date": self.R, "meli_inbound_status": "picked_up"}
        self.assertEqual(r.decidir(fila, 0, HOY, date(2026, 11, 12)), ("received", date(2026, 11, 12), "delivered"))


if __name__ == "__main__":
    unittest.main()



