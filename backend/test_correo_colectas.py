"""Reenvío por WhatsApp de los mails de ML sobre la colecta. Sin casilla real, ni WhatsApp, ni base.
Uso:  python backend/test_correo_colectas.py
Los mails de ejemplo imitan el texto de la página del envío; el formato real del mail de ML no está verificado.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correo_colectas as c  # noqa: E402
import pausa_avisos  # noqa: E402
import proyeccion  # noqa: E402

LUNES_10 = datetime(2026, 10, 19, 10, 0, tzinfo=proyeccion.HORA_BA)   # lunes, dentro del horario
LUNES_20 = datetime(2026, 10, 19, 20, 0, tzinfo=proyeccion.HORA_BA)   # lunes, fuera del horario

CUERPO_ML = (
    "Envío N.º 78889570\n"
    "La colecta pasará el 19 de octubre entre las 16:00 y las 18:00 hs\n"
    "Cód. autorización 9F769D2F\n"
    "Transportista Luciano Damian Marenzi Patente AB304TX Transportadora Dos Haches\n"
)


def _mail(asunto="Tu colecta de Full", cuerpo=CUERPO_ML, de="Mercado Libre <no-responder@mercadolibre.com>",
          fecha=None, html=None):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = asunto, de, "colectas@enviobot.com.ar"
    m["Date"] = format_datetime(fecha or LUNES_10 - timedelta(minutes=5))
    if html:
        m.set_content("x")
        m.clear_content()
        m.set_content(html, subtype="html")
    else:
        m.set_content(cuerpo)
    return m.as_bytes()


class _Imap:
    """Casilla de mentira: guarda qué mails se marcaron como leídos."""
    def __init__(self, mails):
        self.mails, self.vistos, self.flags, self.expunged = mails, set(), {}, False

    def search(self, _c, _crit):
        pendientes = [str(i + 1).encode() for i in range(len(self.mails)) if (i + 1) not in self.vistos]
        return "OK", [b" ".join(pendientes)]

    def fetch(self, num, _q):
        return "OK", [(b"1 (BODY[] {1})", self.mails[int(num) - 1])]

    def store(self, num, _f, flag):
        self.vistos.add(int(num))
        self.flags[int(num)] = flag

    def expunge(self):
        self.expunged = True

    def logout(self):
        pass


CFG = {"host": "h", "port": 993, "user": "u", "password": "p", "telefonos": ["+5491155550001"], "max_horas": 36}


def _correr(mails, ahora=LUNES_10, ok=True, cfg=CFG):
    imap = _Imap(mails)
    enviados = []

    def enviar(tels, texto):
        enviados.append((tels, texto))
        return [{"phone": t, "result": {"ok": ok}} for t in tels]

    with mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "pausados"}):
        res = c.ejecutar(ahora=ahora, config=cfg, conectar=lambda _cfg: imap, enviar=enviar)
    return res, enviados, imap


class TestFiltro(unittest.TestCase):
    def test_un_mail_de_ml_con_la_palabra_colecta_pasa(self):
        self.assertTrue(c.es_de_colecta("Tu colecta", "texto", "Mercado Libre <a@mercadolibre.com>"))

    def test_sin_la_palabra_colecta_no_pasa(self):
        self.assertFalse(c.es_de_colecta("Tu venta", "se vendió algo", "ML <a@mercadolibre.com>"))

    def test_colecta_con_mayusculas_y_acentos(self):
        self.assertTrue(c.es_de_colecta("COLECTA PROGRAMADA", "", "Mercado Libre"))

    def test_colecta_de_otra_empresa_no_pasa(self):
        self.assertFalse(c.es_de_colecta("Colecta de residuos", "barrio", "municipio@ciudad.gob.ar"))

    def test_el_reenvio_que_nombra_a_ml_en_el_cuerpo_pasa(self):
        self.assertTrue(c.es_de_colecta("Fwd: colecta", "---- Mensaje de Mercado Libre ----", "soporte@logax.com.ar"))


class TestDatos(unittest.TestCase):
    def test_extrae_lo_que_trae_la_pagina_del_envio(self):
        d = c.extraer_datos(CUERPO_ML)
        self.assertEqual(d["fecha"], "19 de octubre")
        self.assertEqual((d["desde"], d["hasta"]), ("16:00", "18:00"))
        self.assertEqual(d["codigo"], "9F769D2F")
        self.assertEqual(d["patente"], "AB304TX")
        self.assertEqual(d["transportista"], "Luciano Damian Marenzi")
        self.assertEqual(d["envio"], "78889570")

    def test_lo_que_no_esta_queda_afuera_sin_romper(self):
        self.assertEqual(c.extraer_datos("Hola, novedades de tu colecta."), {})

    def test_el_mensaje_lleva_los_datos_y_un_extracto(self):
        txt = c.armar_mensaje("Tu colecta", CUERPO_ML, c.extraer_datos(CUERPO_ML))
        for esperado in ("Código de autorización: 9F769D2F", "entre las 16:00 y las 18:00 hs", "Patente AB304TX", "78889570"):
            self.assertIn(esperado, txt)

    def test_el_extracto_se_acorta(self):
        txt = c.armar_mensaje("x", "palabra " * 500, {})
        self.assertLess(len(txt), c.LARGO_EXTRACTO + 120)
        self.assertTrue(txt.endswith("…"))

    def test_mail_en_html_se_lee_como_texto(self):
        html = "<html><style>p{}</style><body><p>La colecta pasará el 19 de octubre entre las 16:00 y las 18:00 hs</p><p>Cód. autorización ABC123</p></body></html>"
        res, enviados, _ = _correr([_mail(html=html)])
        self.assertEqual(res["avisados"], 1)
        self.assertIn("Código de autorización: ABC123", enviados[0][1])


class TestEjecucion(unittest.TestCase):
    def test_avisa_y_marca_como_leido(self):
        res, enviados, imap = _correr([_mail()])
        self.assertEqual(res["avisados"], 1)
        self.assertEqual(enviados[0][0], ["+5491155550001"])
        self.assertEqual(imap.vistos, {1})

    def test_el_mail_resuelto_se_borra_de_la_casilla(self):
        res, _, imap = _correr([_mail(), _mail(asunto="Vendiste", cuerpo="hola")])
        self.assertEqual(imap.flags, {1: "\\Deleted", 2: "\\Deleted"})
        self.assertTrue(imap.expunged)

    def test_lo_pendiente_no_se_borra(self):
        _, _, imap = _correr([_mail()], ahora=LUNES_20)
        self.assertEqual(imap.flags, {})
        self.assertFalse(imap.expunged)

    def test_se_puede_pedir_que_queden_como_leidos(self):
        _, _, imap = _correr([_mail()], cfg=dict(CFG, borrar=False))
        self.assertEqual(imap.flags, {1: "\\Seen"})
        self.assertFalse(imap.expunged)

    def test_fuera_de_horario_no_manda_y_deja_el_mail_sin_leer(self):
        res, enviados, imap = _correr([_mail()], ahora=LUNES_20)
        self.assertEqual((res["avisados"], res["pendientes"]), (0, 1))
        self.assertEqual(enviados, [])
        self.assertEqual(imap.vistos, set())

    def test_mail_que_no_es_de_colecta_se_ignora_y_se_marca_leido(self):
        res, enviados, imap = _correr([_mail(asunto="Vendiste un producto", cuerpo="Felicitaciones")])
        self.assertEqual((res["ignorados"], res["avisados"]), (1, 0))
        self.assertEqual(enviados, [])
        self.assertEqual(imap.vistos, {1})

    def test_mail_viejo_no_se_manda(self):
        res, enviados, imap = _correr([_mail(fecha=LUNES_10 - timedelta(hours=40))])
        self.assertEqual((res["viejos"], res["avisados"]), (1, 0))
        self.assertEqual(enviados, [])
        self.assertEqual(imap.vistos, {1})

    def test_si_falla_el_whatsapp_queda_para_reintentar(self):
        res, enviados, imap = _correr([_mail()], ok=False)
        self.assertEqual((res["avisados"], res["pendientes"]), (0, 1))
        self.assertEqual(imap.vistos, set())

    def test_varios_mails_se_tratan_cada_uno_por_su_cuenta(self):
        res, enviados, _ = _correr([_mail(), _mail(asunto="Spam", cuerpo="oferta"), _mail(asunto="Colecta modificada")])
        self.assertEqual((res["leidos"], res["avisados"], res["ignorados"]), (3, 2, 1))

    def test_sin_configurar_no_hace_nada(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(c.leer_configuracion())
            res = c.ejecutar(ahora=LUNES_10, conectar=lambda _c: self.fail("no debe conectarse"))
        self.assertTrue(res.get("sin_configurar"))

    def test_configuracion_completa(self):
        env = {"COLECTAS_IMAP_USER": "colectas@enviobot.com.ar", "COLECTAS_IMAP_PASSWORD": "x",
               "COLECTAS_WHATSAPP": "+5491100000001, +5491100000002", "SMTP_HOST": "po.ferozo.com"}
        cfg = c.leer_configuracion(env)
        self.assertEqual(cfg["telefonos"], ["+5491100000001", "+5491100000002"])
        self.assertEqual((cfg["host"], cfg["port"], cfg["max_horas"]), ("po.ferozo.com", 993, c.MAX_HORAS_DEFECTO))
        self.assertTrue(cfg["borrar"])
        self.assertFalse(c.leer_configuracion(dict(env, COLECTAS_BORRAR="no"))["borrar"])

    def test_falta_el_telefono_y_no_se_configura(self):
        self.assertIsNone(c.leer_configuracion({"COLECTAS_IMAP_USER": "a", "COLECTAS_IMAP_PASSWORD": "b"}))


class TestPausa(unittest.TestCase):
    def test_este_aviso_pasa_la_pausa_general_porque_lo_pidio_guillermo(self):
        with mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "pausados"}):
            self.assertTrue(pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA))
            self.assertFalse(pausa_avisos.puede_enviar(pausa_avisos.ALERTA_STOCK))
            self.assertFalse(pausa_avisos.puede_enviar(pausa_avisos.AVISO_LIMITE_COLECTA))


if __name__ == "__main__":
    unittest.main()
