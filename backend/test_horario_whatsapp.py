"""Los WhatsApp salen solo de lunes a viernes, de 8:30 a 18:00 (hora de Buenos Aires). Sin base ni WhatsApp.
Uso:  python backend/test_horario_whatsapp.py
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proyeccion as p  # noqa: E402
import horario_whatsapp as h  # noqa: E402
import alerts_engine  # noqa: E402


def ba(dia, hora, minuto=0):
    """dia 1..: octubre 2026 (el 16 es viernes, el 17 sábado, el 18 domingo, el 19 lunes)."""
    return datetime(2026, 10, dia, hora, minuto, tzinfo=p.HORA_BA)


class TestHorario(unittest.TestCase):
    def test_dentro_del_horario(self):
        self.assertTrue(h.whatsapp_permitido(ba(16, 8, 30)))
        self.assertTrue(h.whatsapp_permitido(ba(16, 12, 0)))
        self.assertTrue(h.whatsapp_permitido(ba(19, 18, 0)))

    def test_antes_de_abrir_y_despues_de_cerrar(self):
        self.assertFalse(h.whatsapp_permitido(ba(16, 8, 29)))
        self.assertFalse(h.whatsapp_permitido(ba(16, 18, 1)))
        self.assertFalse(h.whatsapp_permitido(ba(16, 22, 0)))
        self.assertFalse(h.whatsapp_permitido(ba(16, 0, 0)))

    def test_fin_de_semana_nunca(self):
        self.assertFalse(h.whatsapp_permitido(ba(17, 12, 0)))  # sábado
        self.assertFalse(h.whatsapp_permitido(ba(18, 12, 0)))  # domingo

    def test_usa_hora_de_buenos_aires_aunque_llegue_en_utc(self):
        from datetime import timezone
        utc = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)  # 08:00 en Buenos Aires
        self.assertFalse(h.whatsapp_permitido(utc.astimezone(p.HORA_BA)))
        utc = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)  # 09:00 en Buenos Aires
        self.assertTrue(h.whatsapp_permitido(utc.astimezone(p.HORA_BA)))


class _Cur:
    def __init__(self):
        self.sql, self.params = "", ()

    def __enter__(self):
        return self

    def __exit__(self, *x):
        return False

    def execute(self, sql, params=()):
        self.sql, self.params = sql, params

    def fetchone(self):
        return None


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def cursor(self):
        return self.cur


class TestCooldownPorCanal(unittest.TestCase):
    def test_sin_canal_se_comporta_como_antes(self):
        c = _Conn()
        alerts_engine.ya_se_envio_alerta_hoy(c, 1, "critical")
        self.assertNotIn("channel", c.cur.sql)
        self.assertEqual(len(c.cur.params), 3)

    def test_con_canal_filtra_por_ese_canal(self):
        c = _Conn()
        alerts_engine.ya_se_envio_alerta_hoy(c, 1, "critical", channel="whatsapp")
        self.assertIn("channel=%s", c.cur.sql)
        self.assertEqual(c.cur.params[-1], "whatsapp")


class TestMotorRespetaElHorario(unittest.TestCase):
    def test_el_motor_consulta_el_horario_antes_de_mandar_whatsapp(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts_engine.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("en_horario(destinos[t], ahora_ba)", src)
        self.assertIn("if enviar_wa:", src)


class TestHorarioPorDestinatario(unittest.TestCase):
    def test_sin_nada_configurado_es_el_defecto(self):
        hor = h.horario_de({})
        self.assertEqual(hor, h.horario_defecto())
        self.assertEqual(h.horario_de({"wa_days": None, "wa_from": None, "wa_to": None}), h.horario_defecto())

    def test_el_destinatario_hereda_el_horario_del_dueno(self):
        dueno = h.horario_de({"wa_days": "0,1,2,3,4,5", "wa_from": "07:00", "wa_to": "20:00"})
        self.assertEqual(dueno["dias"], (0, 1, 2, 3, 4, 5))
        self.assertEqual((dueno["desde"], dueno["hasta"]), ((7, 0), (20, 0)))
        hereda = h.horario_de({"wa_days": None, "wa_from": None, "wa_to": None}, dueno)
        self.assertEqual(hereda, dueno)

    def test_el_destinatario_puede_pisar_solo_lo_suyo(self):
        dueno = h.horario_de({"wa_days": "0,1,2,3,4", "wa_from": "08:30", "wa_to": "18:00"})
        suyo = h.horario_de({"wa_days": "5,6", "wa_from": None, "wa_to": "12:00"}, dueno)
        self.assertEqual(suyo["dias"], (5, 6))
        self.assertEqual(suyo["desde"], (8, 30))
        self.assertEqual(suyo["hasta"], (12, 0))

    def test_sabado_solo_para_quien_lo_pidio(self):
        sab = h.horario_de({"wa_days": "5", "wa_from": "09:00", "wa_to": "13:00"})
        self.assertTrue(h.whatsapp_permitido(ba(17, 10, 0), sab))   # sábado 10:00
        self.assertFalse(h.whatsapp_permitido(ba(17, 14, 0), sab))  # sábado 14:00
        self.assertFalse(h.whatsapp_permitido(ba(16, 10, 0), sab))  # viernes
        self.assertFalse(h.whatsapp_permitido(ba(17, 10, 0)))       # defecto: sábado nunca

    def test_datos_malos_caen_al_defecto(self):
        hor = h.horario_de({"wa_days": "x,9", "wa_from": "25:99", "wa_to": "abc"})
        self.assertEqual(hor, h.horario_defecto())

    def test_validar(self):
        ok, err = h.validar([0, 1, 2], "08:00", "17:30")
        self.assertIsNone(err)
        self.assertEqual(h.a_texto(ok), {"dias": "0,1,2", "desde": "08:00", "hasta": "17:30"})
        self.assertIsNotNone(h.validar([], "08:00", "17:30")[1])
        self.assertIsNotNone(h.validar([0], "18:00", "08:00")[1])
        self.assertIsNotNone(h.validar([0], "ocho", "18:00")[1])
        self.assertIsNotNone(h.validar([7], "08:00", "18:00")[1])


if __name__ == "__main__":
    unittest.main()
