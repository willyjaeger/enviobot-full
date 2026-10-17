"""Aviso de una hora antes de que cierre el cambio de la colecta. Sin base, ni WhatsApp, ni mail.
Uso:  python backend/test_aviso_limite.py
"""
import os
import sys
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esquema  # noqa: E402
import proyeccion as p  # noqa: E402
import aviso_limite_colecta as a  # noqa: E402


class TestDiaHabil(unittest.TestCase):
    def test_colecta_del_lunes_se_cierra_el_viernes(self):
        lim = p.limite_edicion(date(2026, 10, 19))  # lunes 19/10
        self.assertEqual((lim.day, lim.hour, lim.minute), (16, 9, 44))
        self.assertEqual(lim.weekday(), 4)  # viernes

    def test_colecta_del_martes_se_cierra_el_lunes(self):
        self.assertEqual(p.limite_edicion(date(2026, 10, 20)).day, 19)

    def test_colecta_de_sabado_o_domingo_tambien_cierra_el_viernes(self):
        self.assertEqual(p.limite_edicion(date(2026, 10, 17)).day, 16)
        self.assertEqual(p.limite_edicion(date(2026, 10, 18)).day, 16)

    def test_ventana_de_aviso(self):
        retiro = date(2026, 10, 19)
        antes = datetime(2026, 10, 16, 8, 30, tzinfo=p.HORA_BA)    # 70 min antes
        justo = datetime(2026, 10, 16, 8, 44, tzinfo=p.HORA_BA)    # 60 min antes
        casi = datetime(2026, 10, 16, 9, 35, tzinfo=p.HORA_BA)     # 5 min antes
        tarde = datetime(2026, 10, 16, 9, 45, tzinfo=p.HORA_BA)    # ya cerró
        self.assertFalse(p.en_ventana_de_aviso(retiro, antes))
        self.assertTrue(p.en_ventana_de_aviso(retiro, justo))
        self.assertTrue(p.en_ventana_de_aviso(retiro, casi))
        self.assertFalse(p.en_ventana_de_aviso(retiro, tarde))


class TestTexto(unittest.TestCase):
    def test_dice_lunes_19_y_el_limite_del_viernes(self):
        retiro = date(2026, 10, 19)
        limite = p.limite_edicion(retiro)
        t = a.texto_aviso(retiro, limite, 3500, "COL-1", "https://x")
        self.assertIn("Te queda cerca de una hora", t)
        self.assertIn("colecta del lunes 19/10", t)
        self.assertIn("viernes 16/10 a las 09:44", t)
        self.assertIn("COL-1", t)

    def test_con_poco_tiempo_dice_los_minutos(self):
        retiro = date(2026, 10, 19)
        t = a.texto_aviso(retiro, p.limite_edicion(retiro), 12 * 60)
        self.assertIn("Te quedan 12 minutos", t)


class _Cur:
    def __init__(self, datos):
        self.d, self._ult = datos, ""

    def __enter__(self):
        return self

    def __exit__(self, *x):
        return False

    def execute(self, sql, params=()):
        self._ult = sql

    def fetchone(self):
        if "information_schema" in self._ult:
            return {"COUNT(*)": 0}
        if "FROM users" in self._ult:
            return {"id": 1, "email": "dueño@x.com"}
        if "FROM user_settings" in self._ult:
            return self.d.get("settings")
        return None

    def fetchall(self):
        if "FROM inbound_shipments" in self._ult:
            return self.d["colectas"]
        if "FROM alert_recipients" in self._ult:
            return [{"phone": "+5491111111111"}]
        return []


class _Conn:
    def __init__(self, datos):
        self.datos = datos

    def cursor(self):
        return _Cur(self.datos)


class TestProcesar(unittest.TestCase):
    def setUp(self):
        esquema.olvidar()
        _env = mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "activos"})
        _env.start()
        self.addCleanup(_env.stop)
        self.wa, self.mails, self.logs, self.ya = [], [], [], set()
        a.enviar_lote_con_demora = lambda tels, txt, **k: self.wa.append((tels, txt)) or []
        a.enviar_email = lambda dest, asunto, txt, *x, **k: self.mails.append((dest, txt)) or {"ok": True}
        a.obtener_configuracion_whatsapp = lambda: {"enabled": True}
        a.whatsapp_permitido = lambda ahora=None, horario=None: True
        a.alerts_engine.ya_se_envio_alerta_hoy = lambda conn, uid, tipo, clave, horas_cooldown=20: clave in self.ya
        a.alerts_engine.registrar_alerta_en_log = lambda conn, uid, clave, tipo, msg, channel="whatsapp": (
            self.logs.append((clave, channel)), self.ya.add(clave))

    def _conn(self, **extra):
        datos = {"colectas": [{"shipment_code": "COL-9", "pickup_date": date(2026, 10, 19)}],
                 "settings": {"notify_email": True, "notify_whatsapp": True, "alert_email": "avisos@x.com"}}
        datos.update(extra)
        return _Conn(datos)

    def test_a_una_hora_manda_whatsapp_y_mail(self):
        ahora = datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA)
        r = a.procesar_usuario(self._conn(), 1, ahora)
        self.assertEqual(r["avisos"], 1)
        self.assertEqual(len(self.wa), 1)
        self.assertEqual(self.mails[0][0], "avisos@x.com")
        self.assertIn("lunes 19/10", self.wa[0][1])

    def test_con_los_avisos_pausados_no_sale_nada(self):
        with mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "pausados"}):
            ahora = datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA)
            r = a.procesar_usuario(self._conn(), 1, ahora)
        self.assertEqual(r["avisos"], 0)
        self.assertTrue(r["pausado"])
        self.assertEqual(self.wa, [])
        self.assertEqual(self.mails, [])
        self.assertEqual(self.logs, [])

    def test_lejos_del_limite_no_avisa(self):
        ahora = datetime(2026, 10, 16, 7, 0, tzinfo=p.HORA_BA)
        self.assertEqual(a.procesar_usuario(self._conn(), 1, ahora)["avisos"], 0)
        self.assertEqual(self.wa, [])

    def test_despues_del_limite_no_avisa(self):
        ahora = datetime(2026, 10, 16, 10, 0, tzinfo=p.HORA_BA)
        self.assertEqual(a.procesar_usuario(self._conn(), 1, ahora)["avisos"], 0)

    def test_no_repite_el_aviso_en_la_corrida_siguiente(self):
        c = self._conn()
        a.procesar_usuario(c, 1, datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA))
        a.procesar_usuario(c, 1, datetime(2026, 10, 16, 8, 55, tzinfo=p.HORA_BA))
        self.assertEqual(len(self.wa), 1)
        self.assertEqual(len(self.mails), 1)

    def test_respeta_si_el_cliente_apagó_whatsapp_o_mail(self):
        c = self._conn(settings={"notify_email": False, "notify_whatsapp": False, "alert_email": "x@x.com"})
        r = a.procesar_usuario(c, 1, datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA))
        self.assertEqual(r["avisos"], 0)
        self.assertEqual((self.wa, self.mails), ([], []))

    def test_fuera_de_horario_el_whatsapp_espera_pero_el_mail_sale(self):
        c = self._conn()
        ahora = datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA)
        a.whatsapp_permitido = lambda ahora=None, horario=None: False
        a.procesar_usuario(c, 1, ahora)
        self.assertEqual(self.wa, [])
        self.assertEqual(len(self.mails), 1)
        # Corrida siguiente, ya dentro del horario: sale el WhatsApp y el mail NO se repite.
        a.whatsapp_permitido = lambda ahora=None, horario=None: True
        a.procesar_usuario(c, 1, datetime(2026, 10, 16, 8, 55, tzinfo=p.HORA_BA))
        self.assertEqual(len(self.wa), 1)
        self.assertEqual(len(self.mails), 1)

    def test_sin_colectas_en_preparacion_no_hace_nada(self):
        c = self._conn(colectas=[])
        self.assertEqual(a.procesar_usuario(c, 1, datetime(2026, 10, 16, 8, 45, tzinfo=p.HORA_BA))["avisos"], 0)


if __name__ == "__main__":
    unittest.main()
