"""Menú de avisos por destinatario. Sin base ni WhatsApp.
Uso:  python backend/test_avisos_tipos.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import avisos_tipos as a  # noqa: E402
import aviso_limite_colecta as lim  # noqa: E402
import esquema  # noqa: E402
import pausa_avisos  # noqa: E402


class TestCatalogo(unittest.TestCase):
    def test_las_claves_son_las_de_la_pausa(self):
        for k in (pausa_avisos.ALERTA_STOCK, pausa_avisos.AVISO_LIMITE_COLECTA, pausa_avisos.MAIL_COLECTA, "cambio_tasa_venta"):
            self.assertIn(k, a.CLAVES)

    def test_sin_eleccion_recibe_todo(self):
        for k in a.CLAVES:
            self.assertTrue(a.recibe({"avisos": None}, k))
            self.assertTrue(a.recibe({}, k))       # sin la columna (migración sin aplicar)

    def test_vacio_no_recibe_ninguno(self):
        for k in a.CLAVES:
            self.assertFalse(a.recibe({"avisos": ""}, k))

    def test_solo_los_elegidos(self):
        fila = {"avisos": "colecta_mail,alerta_stock"}
        self.assertTrue(a.recibe(fila, "colecta_mail"))
        self.assertTrue(a.recibe(fila, "alerta_stock"))
        self.assertFalse(a.recibe(fila, "colecta_limite"))

    def test_claves_desconocidas_no_cuentan(self):
        self.assertEqual(a.parsear("colecta_mail,inventado"), frozenset({"colecta_mail"}))

    def test_a_texto_ordena_y_valida(self):
        self.assertEqual(a.a_texto(["colecta_mail", "alerta_stock"]), ("alerta_stock,colecta_mail", None))
        self.assertEqual(a.a_texto([]), ("", None))
        self.assertIsNotNone(a.a_texto(["nada"])[1])

    def test_resumen_para_la_pantalla(self):
        self.assertEqual(a.resumen(None), "Todos")
        self.assertEqual(a.resumen(""), "Ninguno")
        self.assertEqual(a.resumen("alerta_stock,colecta_mail"), "Stock, Mails de ML")
        self.assertEqual(a.resumen(",".join(a.CLAVES)), "Todos")


class _Cur:
    def __init__(self, agenda):
        self.agenda = agenda

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.agenda


class _Conn:
    def __init__(self, agenda):
        self.agenda = agenda

    def cursor(self):
        return _Cur(self.agenda)


class TestDestinatarios(unittest.TestCase):
    AGENDA = [{"phone": "+5491100000001", "avisos": None},
              {"phone": "+5491100000002", "avisos": "colecta_mail"},
              {"phone": "+5491100000003", "avisos": "alerta_stock"}]

    def _quienes(self, tipo, agenda=None, settings=None):
        esquema.olvidar()
        with mock.patch.object(esquema, "tiene_columna", return_value=True):
            return sorted(lim._destinatarios(_Conn(agenda if agenda is not None else self.AGENDA), 1, settings or {}, tipo))

    def test_cada_aviso_llega_a_quien_lo_pidio(self):
        self.assertEqual(self._quienes("colecta_mail"), ["+5491100000001", "+5491100000002"])
        self.assertEqual(self._quienes("alerta_stock"), ["+5491100000001", "+5491100000003"])
        self.assertEqual(self._quienes("colecta_limite"), ["+5491100000001"])

    def test_sin_tipo_llegan_todos_como_antes(self):
        self.assertEqual(len(self._quienes(None)), 3)

    def test_si_todos_se_dieron_de_baja_no_cae_al_telefono_del_dueno(self):
        agenda = [{"phone": "+5491100000009", "avisos": ""}]
        self.assertEqual(self._quienes("colecta_mail", agenda, {"whatsapp_phone": "+5491100000099"}), [])

    def test_con_la_agenda_vacia_queda_el_telefono_del_dueno(self):
        self.assertEqual(self._quienes("colecta_mail", [], {"whatsapp_phone": "+5491100000099"}), ["+5491100000099"])


if __name__ == "__main__":
    unittest.main()
