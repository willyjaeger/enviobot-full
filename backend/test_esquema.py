"""Detección de columnas/tablas de la migración 001 y que el SQL sea re-ejecutable. Sin base."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esquema  # noqa: E402


class _Cur:
    def __init__(self, cuenta=1, falla=False):
        self.cuenta, self.falla, self.llamadas = cuenta, falla, 0

    def execute(self, sql, params=()):
        self.llamadas += 1
        if self.falla:
            raise RuntimeError("sin permiso")

    def fetchone(self):
        return {"COUNT(*)": self.cuenta}


class TestEsquema(unittest.TestCase):
    def setUp(self):
        esquema.olvidar()

    def test_columna_que_existe(self):
        self.assertTrue(esquema.tiene_columna(_Cur(1), "warehouses", "edit_cutoff_time", ahora=1000))

    def test_columna_que_falta(self):
        self.assertFalse(esquema.tiene_columna(_Cur(0), "warehouses", "edit_cutoff_time", ahora=1000))

    def test_ante_un_error_queda_apagada(self):
        self.assertFalse(esquema.tiene_tabla(_Cur(falla=True), "stock_daily", ahora=1000))

    def test_usa_cache_y_la_renueva_pasado_el_tiempo(self):
        cur = _Cur(0)
        esquema.tiene_columna(cur, "t", "c", ahora=1000)
        esquema.tiene_columna(cur, "t", "c", ahora=1100)
        self.assertEqual(cur.llamadas, 1)
        cur.cuenta = 1  # se aplicó la migración
        self.assertTrue(esquema.tiene_columna(cur, "t", "c", ahora=1000 + esquema._TTL + 1))
        self.assertEqual(cur.llamadas, 2)


class TestMigracionSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration_001_colecta_ajustes.sql")
        with open(ruta, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_cada_alter_mira_antes_el_estado(self):
        alters = re.findall(r"ALTER TABLE", self.sql)
        chequeos = re.findall(r"information_schema\.COLUMNS", self.sql)
        self.assertEqual(len(alters), 3)
        self.assertEqual(len(chequeos), 3)

    def test_no_usa_add_column_if_not_exists(self):
        self.assertNotIn("ADD COLUMN IF NOT EXISTS", self.sql.upper())

    def test_la_tabla_nueva_es_idempotente(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS stock_daily", self.sql)

    def test_lock_wait_corto(self):
        self.assertIn("lock_wait_timeout", self.sql)

    def test_los_nombres_coinciden_con_lo_que_lee_el_codigo(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8") as f:
            app = f.read()
        for nombre in ("sobrestock_factor", "edit_cutoff_time", "prep_status", "stock_daily"):
            self.assertIn(nombre, self.sql)
            self.assertIn(nombre, app, f"app.py no usa {nombre}")


if __name__ == "__main__":
    unittest.main()
