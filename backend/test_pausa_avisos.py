"""Pausa general de avisos: hasta definir cuáles mandar, no sale ninguno salvo el de cambio de tasa de venta.
Uso:  python backend/test_pausa_avisos.py
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pausa_avisos as pa  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


def _entorno(valor):
    base = {k: v for k, v in os.environ.items() if k != "ENVIOBOT_AVISOS"}
    if valor is not None:
        base["ENVIOBOT_AVISOS"] = valor
    return mock.patch.dict(os.environ, base, clear=True)


class TestPausa(unittest.TestCase):
    def test_sin_la_variable_los_avisos_estan_pausados(self):
        with _entorno(None):
            self.assertTrue(pa.avisos_pausados())
            self.assertFalse(pa.puede_enviar(pa.ALERTA_STOCK))
            self.assertFalse(pa.puede_enviar(pa.AVISO_LIMITE_COLECTA))

    def test_solo_el_cambio_de_tasa_de_venta_pasa_en_pausa(self):
        with _entorno("pausados"):
            self.assertTrue(pa.puede_enviar("cambio_tasa_venta"))
            self.assertFalse(pa.puede_enviar("cualquier_otro"))

    def test_para_reanudar_hay_que_decir_activos_claramente(self):
        with _entorno("activos"):
            self.assertFalse(pa.avisos_pausados())
            self.assertTrue(pa.puede_enviar(pa.ALERTA_STOCK))
        with _entorno(" Activos "):
            self.assertFalse(pa.avisos_pausados())
        for raro in ("si", "1", "true", "", "no"):
            with _entorno(raro):
                self.assertTrue(pa.avisos_pausados(), raro)


class TestLosEnviosEstanProtegidos(unittest.TestCase):
    """El motor de alertas no se puede probar entero sin base: se cuida que cada envío dependa de la pausa."""

    def _fuente(self, nombre):
        return open(os.path.join(AQUI, nombre), encoding="utf-8").read()

    def test_alerts_engine_no_manda_whatsapp_ni_mail_en_pausa(self):
        fuente = self._fuente("alerts_engine.py")
        self.assertRegex(fuente, r"enviar_wa = .*and stock_permitido")
        self.assertRegex(fuente, r"enviar_mail = \(not ya_mail\) and stock_permitido")
        self.assertIn("pausa_avisos.puede_enviar(pausa_avisos.ALERTA_STOCK)", fuente)

    def test_el_aviso_de_limite_de_colecta_respeta_la_pausa(self):
        fuente = self._fuente("aviso_limite_colecta.py")
        self.assertGreaterEqual(len(re.findall(r"pausa_avisos\.puede_enviar\(pausa_avisos\.AVISO_LIMITE_COLECTA\)", fuente)), 2)

    def test_la_pausa_no_corta_antes_del_cambio_de_tasa(self):
        # el aviso de cambio de tasa corre al empezar procesar_alertas_usuario: la pausa no puede cortar antes
        fuente = self._fuente("alerts_engine.py")
        corte = fuente.index("def procesar_alertas_usuario")
        cuerpo = fuente[corte:]
        self.assertLess(cuerpo.index("conn = get_db()"), cuerpo.index("stock_permitido"))
        self.assertNotIn("return resultado\n    conn = get_db()", cuerpo)


    def test_los_codigos_de_vinculacion_por_mail_estan_apagados_salvo_que_se_active(self):
        import os
        import pausa_avisos
        previo = os.environ.pop("ENVIOBOT_CODIGO_EMAIL", None)
        try:
            self.assertFalse(pausa_avisos.codigo_email_activo())
            os.environ["ENVIOBOT_CODIGO_EMAIL"] = "activo"
            self.assertTrue(pausa_avisos.codigo_email_activo())
            os.environ["ENVIOBOT_CODIGO_EMAIL"] = "si"
            self.assertFalse(pausa_avisos.codigo_email_activo())
        finally:
            os.environ.pop("ENVIOBOT_CODIGO_EMAIL", None)
            if previo is not None:
                os.environ["ENVIOBOT_CODIGO_EMAIL"] = previo

    def test_los_dos_lugares_que_mandan_el_codigo_preguntan_si_esta_activo(self):
        fuente = self._fuente("app.py")
        self.assertEqual(fuente.count("_pausa_avisos.codigo_email_activo()"), 2)


if __name__ == "__main__":
    unittest.main()
