#!/usr/bin/env python3
"""Reenvía por WhatsApp los mails de Mercado Libre que hablan de una colecta.

Mercado Libre manda por mail el código de autorización y otros avisos de la colecta (y la API no
los informa). Un filtro del buzón que los recibe los reenvía a una casilla de EnvioBot; este script
lee esa casilla, se queda con los mails que mencionan la colecta y le manda el resumen por WhatsApp
a quien corresponda (hoy, Dani).

Corre cada pocos minutos desde cron:
    */5 * * * * <venv>/bin/python <app>/backend/correo_colectas.py >> /var/log/enviobot_full.log 2>&1
Cargar esa línea es un cambio aparte, con OK de Guillermo.

Cómo funciona sin guardar nada en la base de datos: la casilla es solo de paso. Cada mail resuelto
(avisado, ajeno a la colecta o demasiado viejo) se BORRA de la casilla, así no se acumula nada. El mail
original sigue en el buzón de origen si el reenvío conserva una copia (conviene dejarlo así).
- Si WhatsApp está fuera de horario (lunes a viernes de 8:30 a 18:00), el mail queda sin leer y sale
  en la próxima corrida dentro del horario.
- Un mail de más de COLECTAS_MAX_HORAS horas ya no se manda: sería información vieja.
- Los mails que no hablan de colecta se marcan como leídos y no se tocan más.

Se configura en el .env del servidor (nada de claves en el código):
    COLECTAS_IMAP_USER, COLECTAS_IMAP_PASSWORD   casilla que recibe los mails reenviados
    COLECTAS_IMAP_HOST (opcional; por defecto el SMTP_HOST), COLECTAS_IMAP_PORT (opcional, 993)
    COLECTAS_WHATSAPP        teléfono(s) de quien recibe el aviso, separados por coma
    COLECTAS_MAX_HORAS       opcional, por defecto 36
    COLECTAS_BORRAR          opcional, "no" para dejar los mails como leídos en vez de borrarlos
Sin la casilla o sin el teléfono configurados, no hace nada.
"""
import email
import email.policy
import imaplib
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

try:  # cron no carga el .env: se lee el de esta carpeta (el mismo que usa la app)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:  # pragma: no cover
    pass

import pausa_avisos
import proyeccion
from horario_whatsapp import horario_defecto, whatsapp_permitido

logger = logging.getLogger("correo_colectas")

MAX_HORAS_DEFECTO = 36
LARGO_EXTRACTO = 450


# ── Lectura de un mail ───────────────────────────────────────────────────────────────

class _HtmlATexto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes = []
        self._saltar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._saltar += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._saltar:
            self._saltar -= 1
        elif tag in ("p", "div", "tr", "li", "td"):
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._saltar:
            self.partes.append(data)


def html_a_texto(html):
    p = _HtmlATexto()
    p.feed(html or "")
    return "".join(p.partes)


def limpiar(texto):
    """Espacios y renglones de más fuera."""
    texto = (texto or "").replace("\xa0", " ")
    renglones = [re.sub(r"[ \t]+", " ", r).strip() for r in texto.splitlines()]
    return "\n".join(r for r in renglones if r)


def texto_del_mail(msg):
    """Cuerpo del mail como texto plano (prefiere text/plain; si no hay, convierte el HTML)."""
    plano = msg.get_body(preferencelist=("plain",))
    if plano is not None:
        try:
            t = limpiar(plano.get_content())
            if t:
                return t
        except Exception:
            pass
    html = msg.get_body(preferencelist=("html",))
    if html is not None:
        try:
            return limpiar(html_a_texto(html.get_content()))
        except Exception:
            pass
    return ""


def _sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def es_de_colecta(asunto, cuerpo, remitente=""):
    """Habla de una colecta y viene de Mercado Libre (o lo nombra): evita reenviar cualquier mail suelto."""
    texto = _sin_acentos(f"{asunto}\n{cuerpo}")
    if "colecta" not in texto:
        return False
    origen = _sin_acentos(f"{remitente}\n{texto}")
    return any(x in origen for x in ("mercadolibre", "mercado libre", "mercadoenvios", "mercado envios"))


# ── Datos del mail ───────────────────────────────────────────────────────────────

_RE_FRANJA = re.compile(r"entre\s+las\s+(\d{1,2})[:.](\d{2})\s*(?:y|a)\s*las\s+(\d{1,2})[:.](\d{2})", re.I)
_RE_FECHA = re.compile(r"(?:el\s+)?(\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?)", re.I)
_RE_CODIGO = re.compile(r"c[oó]d(?:igo|\.)?\s*(?:de\s+)?autorizaci[oó]n\s*[:\-]?\s*([A-Z0-9]{5,12})\b", re.I)
_RE_PATENTE = re.compile(r"Patente\s*[:\-]?\s*([A-Z]{2}\s?\d{3}\s?[A-Z]{2}|[A-Z]{3}\s?\d{3})\b", re.I)
_RE_TRANSPORTISTA = re.compile(r"Transportista\s*[:\-]?\s*(.+?)(?=\s+(?:Patente|Transportadora|Domicilio|C[oó]d)\b|\n|$)", re.I)
_RE_ENVIO = re.compile(r"Env[ií]o\s*(?:N\.?\s*[º°o]?\s*|#\s*)(\d{6,})", re.I)


def extraer_datos(texto):
    """Lo que se pueda sacar del texto; lo que no aparece queda afuera (el formato del mail puede cambiar)."""
    d = {}
    f = _RE_FRANJA.search(texto)
    if f:
        d["desde"] = "%02d:%s" % (int(f.group(1)), f.group(2))
        d["hasta"] = "%02d:%s" % (int(f.group(3)), f.group(4))
        antes = texto[max(0, f.start() - 80):f.start()]
        fechas = _RE_FECHA.findall(antes)
        if fechas:
            d["fecha"] = fechas[-1].strip()
    for clave, rx in (("codigo", _RE_CODIGO), ("patente", _RE_PATENTE), ("transportista", _RE_TRANSPORTISTA), ("envio", _RE_ENVIO)):
        m = rx.search(texto)
        if m:
            d[clave] = re.sub(r"\s+", " ", m.group(1)).strip().upper() if clave in ("codigo", "patente") else re.sub(r"\s+", " ", m.group(1)).strip()
    return d


def armar_mensaje(asunto, cuerpo, datos):
    """Texto de WhatsApp: los datos que se pudieron leer y un extracto del mail por si falta algo."""
    lineas = ["Mercado Libre avisó por mail sobre la colecta"]
    if asunto:
        lineas.append(f"Asunto: {asunto.strip()}")
    if datos.get("envio"):
        lineas.append(f"Envío N.º {datos['envio']}")
    if datos.get("desde"):
        cuando = f"{datos['fecha']}, " if datos.get("fecha") else ""
        lineas.append(f"Pasa {cuando}entre las {datos['desde']} y las {datos['hasta']} hs")
    if datos.get("codigo"):
        lineas.append(f"Código de autorización: {datos['codigo']}")
    quien = " · ".join(x for x in (datos.get("transportista"), ("Patente " + datos["patente"]) if datos.get("patente") else None) if x)
    if quien:
        lineas.append(quien)
    extracto = (cuerpo or "").strip().replace("\n", " ")
    if len(extracto) > LARGO_EXTRACTO:
        extracto = extracto[:LARGO_EXTRACTO].rsplit(" ", 1)[0] + "…"
    if extracto:
        lineas.append("")
        lineas.append(extracto)
    return "\n".join(lineas)


# ── Casilla y envío ───────────────────────────────────────────────────────────────

def leer_configuracion(env=None):
    env = os.environ if env is None else env
    telefonos = [t.strip() for t in (env.get("COLECTAS_WHATSAPP") or "").split(",") if t.strip()]
    usuario, clave = (env.get("COLECTAS_IMAP_USER") or "").strip(), env.get("COLECTAS_IMAP_PASSWORD") or ""
    if not (usuario and clave and telefonos):
        return None
    try:
        max_horas = float(env.get("COLECTAS_MAX_HORAS") or MAX_HORAS_DEFECTO)
    except ValueError:
        max_horas = MAX_HORAS_DEFECTO
    return {
        "host": (env.get("COLECTAS_IMAP_HOST") or env.get("SMTP_HOST") or "").strip(),
        "port": int(env.get("COLECTAS_IMAP_PORT") or 993),
        "user": usuario, "password": clave, "telefonos": telefonos, "max_horas": max_horas,
        "borrar": (env.get("COLECTAS_BORRAR") or "si").strip().lower() not in ("no", "0", "false"),
    }


def _conectar(cfg):
    imap = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    imap.login(cfg["user"], cfg["password"])
    imap.select("INBOX")
    return imap


def _descartar(imap, num, cfg):
    """Mail ya resuelto: se borra de la casilla (que solo es de paso) o, si se prefiere guardarlo, queda como leído."""
    imap.store(num, "+FLAGS", "\\Deleted" if cfg.get("borrar", True) else "\\Seen")


def _enviar_whatsapp(telefonos, texto):
    from whatsapp_service import enviar_lote_con_demora
    return enviar_lote_con_demora(telefonos, texto)


def ejecutar(ahora=None, config=None, conectar=None, enviar=None):
    """Una pasada por la casilla. `conectar` y `enviar` se pueden reemplazar (tests)."""
    res = {"leidos": 0, "avisados": 0, "ignorados": 0, "viejos": 0, "pendientes": 0}
    if not pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA):
        logger.info("[Mail colecta] Avisos pausados (ENVIOBOT_AVISOS): no se envía nada.")
        res["pausado"] = True
        return res
    cfg = config or leer_configuracion()
    if not cfg:
        logger.info("[Mail colecta] Sin casilla o sin teléfono configurados: no se hace nada.")
        res["sin_configurar"] = True
        return res
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    enviar = enviar or _enviar_whatsapp
    imap = (conectar or _conectar)(cfg)
    try:
        tipo, datos = imap.search(None, "UNSEEN")
        ids = datos[0].split() if tipo == "OK" and datos and datos[0] else []
        for num in ids:
            tipo, partes = imap.fetch(num, "(BODY.PEEK[])")
            if tipo != "OK" or not partes or not partes[0]:
                continue
            msg = email.message_from_bytes(partes[0][1], policy=email.policy.default)
            res["leidos"] += 1
            asunto = str(msg.get("Subject") or "")
            cuerpo = texto_del_mail(msg)
            if not es_de_colecta(asunto, cuerpo, str(msg.get("From") or "")):
                _descartar(imap, num, cfg)
                res["ignorados"] += 1
                continue
            try:
                fecha_mail = parsedate_to_datetime(str(msg.get("Date")))
                if fecha_mail.tzinfo is None:
                    fecha_mail = fecha_mail.replace(tzinfo=ahora.tzinfo)
                if ahora - fecha_mail > timedelta(hours=cfg["max_horas"]):
                    _descartar(imap, num, cfg)
                    res["viejos"] += 1
                    continue
            except (TypeError, ValueError):
                pass  # sin fecha legible se trata como reciente
            if not whatsapp_permitido(ahora, horario_defecto()):
                res["pendientes"] += 1  # queda sin leer: sale en la próxima corrida dentro del horario
                continue
            texto = armar_mensaje(asunto, cuerpo, extraer_datos(cuerpo))
            resultados = enviar(cfg["telefonos"], texto)
            if any((r.get("result") or {}).get("ok") for r in (resultados or [])):
                _descartar(imap, num, cfg)
                res["avisados"] += 1
                logger.info(f"[Mail colecta] Avisado por WhatsApp: {asunto[:80]}")
            else:
                res["pendientes"] += 1
                logger.error(f"[Mail colecta] No se pudo enviar el WhatsApp ({asunto[:80]}); se reintenta.")
        if cfg.get("borrar", True) and (res["avisados"] or res["ignorados"] or res["viejos"]):
            imap.expunge()   # saca de verdad los mails marcados: la casilla no acumula nada
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(ejecutar())
