"""Reenvío por WhatsApp de los mails de ML sobre la colecta, a cada cliente el suyo.
Sin casilla real, ni WhatsApp, ni base.  Uso:  python backend/test_correo_colectas.py
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
DOMINGO = {"dias": (6,), "desde": (0, 0), "hasta": (23, 59)}
HORARIO = c.horario_defecto()

CUERPO_ML = (
    "Envío N.º 78889570\n"
    "La colecta pasará el 19 de octubre entre las 16:00 y las 18:00 hs\n"
    "Cód. autorización 9F769D2F\n"
    "Transportista Luciano Damian Marenzi Patente AB304TX Transportadora Dos Haches\n"
)


def _mail(asunto="Tu colecta de Full", cuerpo=CUERPO_ML, de="Mercado Libre <no-responder@mercadolibre.com>",
          para="ventasml@logax.com.ar", fecha=None, html=None):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = asunto, de, para
    m["Date"] = format_datetime(fecha or LUNES_10 - timedelta(minutes=5))
    if html:
        m.set_content(html, subtype="html")
    else:
        m.set_content(cuerpo)
    return m.as_bytes()


class _Imap:
    """Casilla de mentira: guarda qué mails se marcaron y cómo."""
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


CFG = {"host": "h", "port": 993, "user": "colectas@enviobot.com.ar", "password": "p", "max_horas": 36}
MISTERNUT = ("MISTERNUT", {"+5491100000001": HORARIO})


def _correr(mails, ahora=LUNES_10, ok=True, cfg=CFG, cuentas=None):
    """cuentas: lo que devolvería la base. Por defecto, MISTERNUT con un destinatario."""
    imap = _Imap(mails)
    enviados, consultas = [], []

    def enviar(tels, texto):
        enviados.append((tels, texto))
        return [{"phone": t, "result": {"ok": ok}} for t in tels]

    def resolver(direcciones):
        consultas.append(direcciones)
        return [MISTERNUT] if cuentas is None else cuentas

    with mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "pausados"}):
        res = c.ejecutar(ahora=ahora, config=cfg, conectar=lambda _cfg: imap, enviar=enviar, resolver=resolver)
    res["consultas"] = consultas
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

    def test_el_mensaje_dice_de_que_cuenta_es_la_colecta(self):
        txt = c.armar_mensaje("Tu colecta", CUERPO_ML, c.extraer_datos(CUERPO_ML), "MISTERNUT")
        self.assertTrue(txt.startswith("La colecta de MISTERNUT está programada para el 19 de octubre, entre las 16:00 y las 18:00 hs"))
        for esperado in ("Código de autorización: 9F769D2F", "Patente AB304TX", "78889570"):
            self.assertIn(esperado, txt)

    def test_si_no_se_leyo_la_hora_igual_dice_la_cuenta(self):
        txt = c.armar_mensaje("Novedades de tu colecta", "Pasamos a otro día.", {}, "MISTERNUT")
        self.assertTrue(txt.startswith("Mercado Libre avisó por mail sobre la colecta de MISTERNUT"))
        self.assertIn("Pasamos a otro día.", txt)

    def test_sin_nombre_de_cuenta_el_mensaje_sigue_siendo_valido(self):
        self.assertTrue(c.armar_mensaje("x", "y", {}).startswith("Mercado Libre avisó por mail sobre la colecta"))

    def test_el_extracto_se_acorta(self):
        txt = c.armar_mensaje("x", "palabra " * 500, {}, "A")
        self.assertLess(len(txt), c.LARGO_EXTRACTO + 160)
        self.assertTrue(txt.endswith("…"))

    def test_mail_en_html_se_lee_como_texto(self):
        html = "<html><style>p{}</style><body><p>La colecta pasará el 19 de octubre entre las 16:00 y las 18:00 hs</p><p>Cód. autorización ABC123</p></body></html>"
        res, enviados, _ = _correr([_mail(html=html)])
        self.assertEqual(res["avisados"], 1)
        self.assertIn("Código de autorización: ABC123", enviados[0][1])


class TestDireccion(unittest.TestCase):
    def _msg(self, **h):
        import email
        import email.policy
        m = EmailMessage()
        for k, v in h.items():
            m[k.replace("_", "-")] = v
        m.set_content("x")
        return email.message_from_bytes(m.as_bytes(), policy=email.policy.default)

    def test_toma_la_direccion_a_la_que_escribio_ml(self):
        m = self._msg(To="Ventas ML <VentasML@logax.com.ar>")
        self.assertEqual(c.direcciones_del_mail(m), {"ventasml@logax.com.ar"})

    def test_junta_to_cc_y_delivered_to_y_saca_la_casilla_comun(self):
        m = self._msg(To="a@x.com, colectas@enviobot.com.ar", Cc="b@x.com", Delivered_To="C@x.com")
        self.assertEqual(c.direcciones_del_mail(m, propias=("colectas@enviobot.com.ar",)), {"a@x.com", "b@x.com", "c@x.com"})


class TestEjecucion(unittest.TestCase):
    def test_avisa_y_borra_el_mail(self):
        res, enviados, imap = _correr([_mail()])
        self.assertEqual(res["avisados"], 1)
        self.assertEqual(enviados[0][0], ["+5491100000001"])
        self.assertIn("La colecta de MISTERNUT", enviados[0][1])
        self.assertEqual(imap.flags, {1: "\\Deleted"})
        self.assertTrue(imap.expunged)

    def test_pregunta_por_la_direccion_a_la_que_llego_y_no_por_la_casilla_comun(self):
        res, _, _ = _correr([_mail(para="ventasml@logax.com.ar, colectas@enviobot.com.ar")])
        self.assertEqual(res["consultas"], [{"ventasml@logax.com.ar"}])

    def test_cada_cliente_recibe_solo_lo_suyo(self):
        """Dos cuentas, dos mails: el de una no sale al WhatsApp de la otra."""
        a = ("MISTERNUT", {"+5491100000001": HORARIO})
        b = ("OTROCLIENTE", {"+5491100000002": HORARIO})
        mapa = {"ventasml@logax.com.ar": [a], "ventas@otro.com": [b]}
        imap = _Imap([_mail(para="ventasml@logax.com.ar"), _mail(para="ventas@otro.com", asunto="Colecta de otro")])
        enviados = []
        res = c.ejecutar(ahora=LUNES_10, config=CFG, conectar=lambda _c: imap,
                         enviar=lambda t, x: enviados.append((t, x)) or [{"phone": t[0], "result": {"ok": True}}],
                         resolver=lambda dirs: [cu for d in dirs for cu in mapa.get(d, [])])
        self.assertEqual(res["avisados"], 2)
        self.assertEqual(enviados[0][0], ["+5491100000001"])
        self.assertIn("MISTERNUT", enviados[0][1])
        self.assertEqual(enviados[1][0], ["+5491100000002"])
        self.assertIn("OTROCLIENTE", enviados[1][1])
        self.assertNotIn("MISTERNUT", enviados[1][1])

    def test_solo_les_llega_a_quienes_estan_en_su_horario(self):
        cuentas = [("MISTERNUT", {"+5491100000001": HORARIO, "+5491100000002": DOMINGO})]
        res, enviados, _ = _correr([_mail()], cuentas=cuentas)
        self.assertEqual(enviados[0][0], ["+5491100000001"])
        self.assertEqual(res["avisados"], 1)

    def test_fuera_de_horario_no_manda_y_deja_el_mail(self):
        res, enviados, imap = _correr([_mail()], ahora=LUNES_20)
        self.assertEqual((res["avisados"], res["pendientes"]), (0, 1))
        self.assertEqual((enviados, imap.flags, imap.expunged), ([], {}, False))

    def test_mail_de_una_direccion_que_nadie_configuro_se_deja_y_caduca(self):
        res, enviados, imap = _correr([_mail()], cuentas=[])
        self.assertEqual((res["sin_cuenta"], res["avisados"]), (1, 0))
        self.assertEqual((enviados, imap.flags), ([], {}))

    def test_si_nadie_de_la_agenda_pidio_este_aviso_no_se_manda_ni_se_borra(self):
        res, enviados, imap = _correr([_mail()], cuentas=[("MISTERNUT", {})])
        self.assertEqual((res.get("sin_destinatarios"), res["avisados"]), (1, 0))
        self.assertEqual((enviados, imap.flags), ([], {}))

    def test_si_falla_el_whatsapp_queda_para_reintentar(self):
        res, enviados, imap = _correr([_mail()], ok=False)
        self.assertEqual((res["avisados"], res["pendientes"]), (0, 1))
        self.assertEqual(imap.flags, {})

    def test_mail_que_no_es_de_colecta_se_ignora_sin_consultar_cuentas(self):
        res, enviados, imap = _correr([_mail(asunto="Vendiste un producto", cuerpo="Felicitaciones")])
        self.assertEqual((res["ignorados"], res["avisados"], res["consultas"]), (1, 0, []))
        self.assertEqual(imap.flags, {1: "\\Deleted"})

    def test_mail_viejo_no_se_manda(self):
        res, enviados, imap = _correr([_mail(fecha=LUNES_10 - timedelta(hours=40))])
        self.assertEqual((res["viejos"], res["avisados"]), (1, 0))
        self.assertEqual(enviados, [])

    def test_se_puede_pedir_que_queden_como_leidos(self):
        _, _, imap = _correr([_mail()], cfg=dict(CFG, borrar=False))
        self.assertEqual(imap.flags, {1: "\\Seen"})
        self.assertFalse(imap.expunged)

    def test_varios_mails_se_tratan_cada_uno_por_su_cuenta(self):
        res, enviados, _ = _correr([_mail(), _mail(asunto="Spam", cuerpo="oferta"), _mail(asunto="Colecta modificada")])
        self.assertEqual((res["leidos"], res["avisados"], res["ignorados"]), (3, 2, 1))

    def test_sin_configurar_no_hace_nada(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(c.leer_configuracion())
            res = c.ejecutar(ahora=LUNES_10, conectar=lambda _c: self.fail("no debe conectarse"))
        self.assertTrue(res.get("sin_configurar"))

    def test_configuracion_solo_pide_la_casilla(self):
        env = {"COLECTAS_IMAP_USER": "colectas@enviobot.com.ar", "COLECTAS_IMAP_PASSWORD": "x", "SMTP_HOST": "po.ferozo.com"}
        cfg = c.leer_configuracion(env)
        self.assertEqual((cfg["host"], cfg["port"], cfg["max_horas"]), ("po.ferozo.com", 993, c.MAX_HORAS_DEFECTO))
        self.assertTrue(cfg["borrar"])
        self.assertFalse(c.leer_configuracion(dict(env, COLECTAS_BORRAR="no"))["borrar"])
        self.assertIsNone(c.leer_configuracion({"COLECTAS_IMAP_USER": "a"}))


class _CurBase:
    """Base de mentira: responde según la consulta."""
    def __init__(self, datos):
        self.d, self.ultima, self.params = datos, "", ()

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def execute(self, sql, params=None):
        self.ultima, self.params = " ".join(sql.split()), params or ()

    def fetchall(self):
        if "FROM user_settings s" in self.ultima:
            return self.d["settings"]
        if "FROM ml_credentials" in self.ultima:
            return [{"ml_nickname": n} for n in self.d["nicks"].get(self.params[0], [])]
        return []

    def fetchone(self):
        if "business_name" in self.ultima:
            return {"n": self.d["nombres"].get(self.params[0])}
        return None


class _ConnBase:
    def __init__(self, datos):
        self.d, self.cerrada = datos, False

    def cursor(self):
        return _CurBase(self.d)

    def close(self):
        self.cerrada = True


class TestCuentasPorDireccion(unittest.TestCase):
    DATOS = {
        "settings": [{"user_id": 45, "colecta_email": "ventasml@logax.com.ar"},
                     {"user_id": 47, "colecta_email": "VentasML@logax.com.ar, otra@logax.com.ar"},
                     {"user_id": 60, "colecta_email": "ventas@otro.com"}],
        "nicks": {45: ["MISTERNUT"], 47: ["MISTERNUT"], 60: ["OTROCLIENTE"]},
        "nombres": {45: "Guillermo", 47: "Guillermo", 60: "Otro SA"},
    }
    AGENDAS = {45: {"+5491100000001": HORARIO}, 47: {"+54 9 11 0000-0001": HORARIO, "+5491100000003": HORARIO},
               60: {"+5491100000002": HORARIO}}

    def _buscar(self, direcciones, datos=None):
        import alerts_engine
        import esquema
        conn = _ConnBase(datos or self.DATOS)
        with mock.patch.object(alerts_engine, "get_db", return_value=conn),              mock.patch.object(esquema, "tiene_columna", return_value=True),              mock.patch("aviso_limite_colecta._destinatarios", side_effect=lambda cn, uid, f, tipo: dict(self.AGENDAS[uid])) as dest:
            res = c.cuentas_por_direccion(direcciones)
        self.assertTrue(conn.cerrada)
        self.assertTrue(all(call.args[3] == pausa_avisos.MAIL_COLECTA for call in dest.call_args_list))
        return res

    def test_una_direccion_trae_solo_la_cuenta_que_la_configuro(self):
        res = dict(self._buscar({"ventas@otro.com"}))
        self.assertEqual(list(res), ["OTROCLIENTE"])
        self.assertEqual(list(res["OTROCLIENTE"]), ["+5491100000002"])

    def test_dos_usuarios_de_la_misma_cuenta_se_juntan_sin_repetir_telefonos(self):
        res = dict(self._buscar({"ventasml@logax.com.ar"}))
        self.assertEqual(list(res), ["MISTERNUT"])
        self.assertEqual(len(res["MISTERNUT"]), 2)   # el +54 9 11 0000-0001 es el mismo que el +5491100000001

    def test_una_direccion_desconocida_no_trae_a_nadie(self):
        self.assertEqual(self._buscar({"nadie@x.com"}), [])

    def test_sin_direcciones_ni_consulta(self):
        self.assertEqual(c.cuentas_por_direccion(set()), [])

    def test_sin_la_migracion_004_no_reparte_nada(self):
        import alerts_engine
        import esquema
        with mock.patch.object(alerts_engine, "get_db", return_value=_ConnBase(self.DATOS)),              mock.patch.object(esquema, "tiene_columna", return_value=False):
            self.assertEqual(c.cuentas_por_direccion({"ventasml@logax.com.ar"}), [])



class TestPausa(unittest.TestCase):
    def test_este_aviso_pasa_la_pausa_general_porque_lo_pidio_guillermo(self):
        with mock.patch.dict(os.environ, {"ENVIOBOT_AVISOS": "pausados"}):
            self.assertTrue(pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA))
            self.assertFalse(pausa_avisos.puede_enviar(pausa_avisos.ALERTA_STOCK))
            self.assertFalse(pausa_avisos.puede_enviar(pausa_avisos.AVISO_LIMITE_COLECTA))


if __name__ == "__main__":
    unittest.main()
