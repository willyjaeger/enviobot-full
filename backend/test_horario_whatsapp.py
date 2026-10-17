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
        self.assertIn("whatsapp_permitido()", src)
        self.assertIn("if enviar_wa and telefonos", src)


if __name__ == "__main__":
    unittest.main()
