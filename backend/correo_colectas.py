#!/usr/bin/env python3
"""Reenvía por WhatsApp los mails de Mercado Libre que hablan de una colecta, a cada cliente el suyo.

Mercado Libre manda por mail el código de autorización y otros avisos de la colecta (y la API no los
informa). Cada cliente indica en Configuración en qué mail le avisa Mercado Libre y lo reenvía a una casilla
común de EnvioBot. Este script lee esa casilla, reconoce de qué cuenta es cada mail por la dirección a la
que llegó, se queda con los que mencionan la colecta y manda el resumen por WhatsApp a la agenda de envíos
de ESA cuenta (cada destinatario según su menú de Avisos y su horario), diciendo de qué cuenta es.

Corre cada pocos minutos desde cron:
    */5 * * * * <venv>/bin/python <app>/backend/correo_colectas.py >> /var/log/enviobot_full.log 2>&1
Cargar esa línea es un cambio aparte, con OK de Guillermo.

Cómo funciona sin guardar nada en la base de datos: la casilla es solo de paso. Cada mail resuelto
(avisado, ajeno a la colecta o demasiado viejo) se BORRA de la casilla, así no se acumula nada. El mail
original sigue en el buzón de origen si el reenvío conserva una copia (conviene dejarlo así).
- Si WhatsApp está fuera del horario de todos los destinatarios, el mail queda y sale en la próxima corrida.
- Un mail de más de COLECTAS_MAX_HORAS horas ya no se manda: sería información vieja.
- Los mails que no hablan de colecta se borran. Los de colecta que no se pueden asignar a ninguna cuenta
  (nadie configuró esa dirección) se dejan y caducan solos; el log dice cuáles.

Se configura en el .env del servidor (nada de claves en el código):
    COLECTAS_IMAP_USER, COLECTAS_IMAP_PASSWORD   casilla común que recibe los mails reenviados
    COLECTAS_IMAP_HOST (opcional; por defecto el SMTP_HOST), COLECTAS_IMAP_PORT (opcional, 993)
    COLECTAS_MAX_HORAS       opcional, por defecto 36
    COLECTAS_BORRAR          opcional, "no" para dejar los mails como leídos en vez de borrarlos
    GEMINI_API_KEY           opcional (recomendado): analiza el mail con IA (Gemini 2.5 Flash) y arma el resumen
    GEMINI_MODEL             opcional, por defecto "gemini-2.5-flash"
Qué mail es de cada cliente se configura en el panel (Configuración, WhatsApp), no acá.
"""
import email
import email.policy
import imaplib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

try:  # cron no carga el .env: se lee el de esta carpeta (el mismo que usa la app)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:  # pragma: no cover
    pass

import pausa_avisos
import proyeccion
from horario_whatsapp import en_horario, horario_defecto

logger = logging.getLogger("correo_colectas")

MAX_HORAS_DEFECTO = 36
LARGO_EXTRACTO = 450
GEMINI_MODEL_DEFECTO = "gemini-2.5-flash"
IA_TIMEOUT_SEG = 12


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


# ── Datos del mail y análisis con IA (Gemini 2.5 Flash) ──────────────────────────────

_RE_FRANJA = re.compile(r"entre\s+las\s+(\d{1,2})[:.](\d{2})\s*(?:y|a)\s*las\s+(\d{1,2})[:.](\d{2})", re.I)
_RE_FECHA = re.compile(r"(?:el\s+)?(\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?)", re.I)
_RE_CODIGO = re.compile(r"c[oó]d(?:igo|\.)?\s*(?:de\s+)?autorizaci[oó]n\s*[:\-]?\s*([A-Z0-9]{5,12})\b", re.I)
_RE_PATENTE = re.compile(r"Patente\s*[:\-]?\s*([A-Z]{2}\s?\d{3}\s?[A-Z]{2}|[A-Z]{3}\s?\d{3})\b", re.I)
_RE_TRANSPORTISTA = re.compile(
    r"Transportista\s*[:\-]?\s*([^\n.]+?(?=\s+(?:Patente|Transportadora|Domicilio|C[oó]d)\b|[.\n]|$)"
    r"(?:\n(?!(?:Patente|Transportadora|Domicilio|C[oó]d|Env[ií]o|La colecta)\b)[A-ZÁÉÍÓÚÑa-záéíóúñ ]+)*)",
    re.I,
)
_RE_TRANSPORTADORA = re.compile(
    r"Transportadora\s*[:\-]?\s*([^\n.]+?)(?=\s+(?:Patente|Transportista|Domicilio|C[oó]d)\b|[.\n]|$)",
    re.I,
)
_RE_ENVIO = re.compile(r"Env[ií]o\s*(?:N\.?\s*[º°o]?\s*|#\s*)(\d{6,})", re.I)

_PROMPT_IA = """Analizá este mensaje de Mercado Libre sobre una colecta de Mercado Envíos Full.
Devolvé ÚNICAMENTE un objeto JSON válido con estas claves (usá "" si un dato no aparece):
{
  "resumen": "Resumen claro y directo en español argentino (1 a 3 oraciones máximo, ideal para WhatsApp) explicando qué informa el mensaje (ej: horario de retiro confirmado, código de autorización, reprogramación, demora o confirmación de colecta). No incluyas saludos genéricos ni texto legal.",
  "fecha": "Fecha de la colecta si la menciona (ej: '19 de octubre')",
  "desde": "Hora de inicio de la franja en formato HH:MM (ej: '16:00')",
  "hasta": "Hora de fin de la franja en formato HH:MM (ej: '18:00')",
  "codigo": "Código de autorización alfanumérico si aparece (ej: '9F769D2F')",
  "transportista": "Nombre del chofer o transportista si aparece",
  "patente": "Patente o dominio del vehículo si aparece (ej: 'AB304TX')",
  "transportadora": "Empresa transportadora si aparece (ej: 'Dos Haches')",
  "envio": "Número de envío de Mercado Libre (solo dígitos, ej: '78889570')"
}"""


def extraer_datos(texto):
    """Lo que se pueda sacar del texto; lo que no aparece queda afuera (el formato del mail puede cambiar)."""
    d = {}
    texto = texto or ""
    f = _RE_FRANJA.search(texto)
    if f:
        d["desde"] = "%02d:%s" % (int(f.group(1)), f.group(2))
        d["hasta"] = "%02d:%s" % (int(f.group(3)), f.group(4))
        antes = texto[max(0, f.start() - 80):f.start()]
        fechas = _RE_FECHA.findall(antes)
        if fechas:
            d["fecha"] = fechas[-1].strip()
    for clave, rx in (
        ("codigo", _RE_CODIGO),
        ("patente", _RE_PATENTE),
        ("transportista", _RE_TRANSPORTISTA),
        ("transportadora", _RE_TRANSPORTADORA),
        ("envio", _RE_ENVIO),
    ):
        m = rx.search(texto)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            d[clave] = val.upper() if clave in ("codigo", "patente") else val
    return d


def _limpiar_json_ia(texto):
    """Extrae el diccionario JSON de la respuesta del modelo aunque venga envuelto en ```json ... ```."""
    if not texto:
        return {}
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio, flags=re.I | re.S).strip()
    try:
        obj = json.loads(limpio)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", limpio, flags=re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except Exception:
                pass
    return {}


def analizar_con_ia(asunto, cuerpo, env=None, post=None):
    """Analiza el asunto y cuerpo con Gemini 2.5 Flash (o OpenAI/Anthropic si están configurados).

    Si no hay clave configurada o falla la red, devuelve `{}` sin interrumpir el envío por WhatsApp.
    """
    env = os.environ if env is None else env
    post = (_requests.post if _requests else None) if post is None else post
    if post is None:
        return {}

    gemini_key = (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip()
    openai_key = (env.get("OPENAI_API_KEY") or "").strip()
    anthropic_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if not (gemini_key or openai_key or anthropic_key):
        return {}

    contenido = f"Asunto: {(asunto or '').strip()}\n\nContenido:\n{(cuerpo or '').strip()[:6000]}"
    raw_text = ""
    try:
        if gemini_key:
            modelo = (env.get("GEMINI_MODEL") or GEMINI_MODEL_DEFECTO).strip()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{_PROMPT_IA}\n\n---\n{contenido}"}]}],
                "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
            }
            resp = post(url, json=payload, timeout=IA_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json() or {}
                cands = data.get("candidates") or []
                if cands:
                    parts = ((cands[0].get("content") or {}).get("parts")) or []
                    if parts:
                        raw_text = parts[0].get("text") or ""
            else:
                logger.warning(f"[Mail colecta IA] Gemini devolvió HTTP {resp.status_code}")
        elif openai_key:
            modelo = (env.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
            resp = post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": modelo,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _PROMPT_IA},
                        {"role": "user", "content": contenido},
                    ],
                },
                timeout=IA_TIMEOUT_SEG,
            )
            if resp.status_code == 200:
                choices = (resp.json() or {}).get("choices") or []
                if choices:
                    raw_text = ((choices[0].get("message") or {}).get("content")) or ""
        elif anthropic_key:
            modelo = (env.get("ANTHROPIC_MODEL") or "claude-haiku-4-5").strip()
            resp = post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": modelo,
                    "max_tokens": 500,
                    "temperature": 0.1,
                    "system": _PROMPT_IA,
                    "messages": [{"role": "user", "content": contenido}],
                },
                timeout=IA_TIMEOUT_SEG,
            )
            if resp.status_code == 200:
                bloques = (resp.json() or {}).get("content") or []
                if bloques:
                    raw_text = bloques[0].get("text") or ""
    except Exception as e:
        logger.warning(f"[Mail colecta IA] Falló consulta a IA, se usa extracción clásica: {e}")
        return {}

    parsed = _limpiar_json_ia(raw_text)
    if not parsed:
        return {}

    resultado = {}
    for k in ("resumen", "fecha", "desde", "hasta", "codigo", "transportista", "patente", "transportadora", "envio"):
        val = parsed.get(k)
        if isinstance(val, str):
            val = re.sub(r"\s+", " ", val).strip()
            if val:
                resultado[k] = val.upper() if k in ("codigo", "patente") else val
    if resultado.get("envio"):
        solo_digitos = re.sub(r"\D+", "", resultado["envio"])
        if solo_digitos:
            resultado["envio"] = solo_digitos
    return resultado


def enriquecer_datos(asunto, cuerpo, env=None, post=None):
    """Combina los datos extraídos por expresiones regulares con el análisis de IA (si está activa)."""
    datos = extraer_datos(cuerpo)
    ia = analizar_con_ia(asunto, cuerpo, env=env, post=post)
    for k, v in ia.items():
        if v and not datos.get(k):
            datos[k] = v
    if ia.get("resumen"):
        datos["resumen"] = ia["resumen"]
    return datos


def armar_mensaje(asunto, cuerpo, datos, cuenta=None):
    """Texto de WhatsApp: de qué cuenta es, los datos que se pudieron leer y el resumen de IA (o extracto)."""
    de = f" de *{cuenta}*" if cuenta else ""
    if datos.get("desde") and datos.get("hasta"):
        cuando = f"el {datos['fecha']}, " if datos.get("fecha") else ""
        lineas = [f"La colecta{de} está programada para {cuando}entre las {datos['desde']} y las {datos['hasta']} hs"]
    else:
        lineas = [f"Mercado Libre avisó por mail sobre la colecta{de}"]
    if asunto:
        lineas.append(f"Asunto: {asunto.strip()}")
    if datos.get("envio"):
        lineas.append(f"Envío N.º {datos['envio']}")
    if datos.get("codigo"):
        lineas.append(f"Código de autorización: *{datos['codigo']}*")
    quien = " · ".join(
        x for x in (
            datos.get("transportista"),
            ("Patente " + datos["patente"]) if datos.get("patente") else None,
            ("Transportadora " + datos["transportadora"]) if datos.get("transportadora") else None,
        ) if x
    )
    if quien:
        lineas.append(quien)
    resumen_ia = (datos.get("resumen") or "").strip()
    if resumen_ia:
        if datos.get("codigo"):
            cod = datos["codigo"]
            resumen_ia = re.sub(rf"(?<!\*)\b{re.escape(cod)}\b(?!\*)", f"*{cod}*", resumen_ia)
        if cuenta:
            resumen_ia = re.sub(rf"(?<!\*)\b{re.escape(cuenta)}\b(?!\*)", f"*{cuenta}*", resumen_ia, flags=re.I)
        lineas.append("")
        lineas.append(f"Resumen IA: {resumen_ia}")
    else:
        extracto = (cuerpo or "").strip().replace("\n", " ")
        if len(extracto) > LARGO_EXTRACTO:
            extracto = extracto[:LARGO_EXTRACTO].rsplit(" ", 1)[0] + "…"
        if extracto:
            lineas.append("")
            lineas.append(extracto)
    return "\n".join(lineas)


# ── Mensajes de WhatsApp que Mercado Libre / transporte mandan al teléfono del vendedor ──

_WA_DIRECTAS = (
    "mercadolibre",
    "mercado libre",
    "mercadoenvios",
    "mercado envios",
    "colecta",
    "transportista",
    "transportadora",
    "autorizacion",
)
_WA_LOGISTICA = (
    "retiro",
    "retirar",
    "camion",
    "chofer",
    "flete",
    "bulto",
    "bultos",
    "pallet",
    "pallets",
    "cajas",
    "reprogram",
    "envio",
    "full",
    "meli",
    "planta",
    "deposito",
)


def es_wa_de_colecta(texto, remitente=""):
    """True si un WhatsApp entrante al teléfono vinculado habla de una colecta / Mercado Libre / camión."""
    limpio = _sin_acentos(f"{remitente}\n{texto}")
    if len((texto or "").strip()) < 6:
        return False
    if any(p in limpio for p in _WA_DIRECTAS):
        return True
    coincidencias = sum(1 for p in _WA_LOGISTICA if re.search(rf"\b{re.escape(p)}", limpio))
    return coincidencias >= 2


def armar_mensaje_wa_colecta(texto, datos, cuenta=None, telefono_receptor=None, remitente=None):
    """Arma el aviso de WhatsApp cuando Mercado Libre o el transporte escriben al WhatsApp vinculado."""
    de = f" de *{cuenta}*" if cuenta else ""
    tel_txt = f" ({telefono_receptor})" if telefono_receptor else ""
    lineas = [f"📲 Mercado Libre / Colecta escribió al WhatsApp{de}{tel_txt}"]
    if remitente and remitente.strip():
        lineas.append(f"Remitente: {remitente.strip()}")
    if datos.get("desde") and datos.get("hasta"):
        cuando = f"el {datos['fecha']}, " if datos.get("fecha") else ""
        lineas.append(f"Franja informada: {cuando}entre las {datos['desde']} y las {datos['hasta']} hs")
    if datos.get("envio"):
        lineas.append(f"Envío N.º {datos['envio']}")
    if datos.get("codigo"):
        lineas.append(f"Código de autorización: *{datos['codigo']}*")
    quien = " · ".join(
        x for x in (
            datos.get("transportista"),
            ("Patente " + datos["patente"]) if datos.get("patente") else None,
            ("Transportadora " + datos["transportadora"]) if datos.get("transportadora") else None,
        ) if x
    )
    if quien:
        lineas.append(quien)
    resumen_ia = (datos.get("resumen") or "").strip()
    if resumen_ia:
        if datos.get("codigo"):
            cod = datos["codigo"]
            resumen_ia = re.sub(rf"(?<!\*)\b{re.escape(cod)}\b(?!\*)", f"*{cod}*", resumen_ia)
        if cuenta:
            resumen_ia = re.sub(rf"(?<!\*)\b{re.escape(cuenta)}\b(?!\*)", f"*{cuenta}*", resumen_ia, flags=re.I)
        lineas.append("")
        lineas.append(f"Resumen IA: {resumen_ia}")
    original = limpiar(texto or "")
    if original:
        if len(original) > 600:
            original = original[:600].rsplit(" ", 1)[0] + "…"
        lineas.append("")
        lineas.append(f"Mensaje original:\n{original}")
    return "\n".join(lineas)


def procesar_wa_entrante(
    user_id,
    texto,
    remitente_nombre="",
    remitente_telefono="",
    telefono_receptor="",
    ahora=None,
    enviar=None,
):
    """Recibe un WhatsApp entrante del teléfono vinculado de la cuenta `user_id` y, si es de colecta,
    lo resume con IA y lo reenvía a los destinatarios de la agenda."""
    if not pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA):
        return {"ok": True, "pausado": True}
    if not es_wa_de_colecta(texto, remitente_nombre):
        return {"ok": True, "ignorado": True, "motivo": "no_es_colecta"}

    import alerts_engine
    from aviso_limite_colecta import _destinatarios
    from whatsapp_service import normalizar_telefono

    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    enviar = enviar or _enviar_whatsapp

    conn = alerts_engine.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
            fila_settings = cur.fetchone() or {"user_id": user_id}
            cur.execute(
                "SELECT ml_nickname FROM ml_credentials WHERE user_id=%s AND ml_nickname IS NOT NULL ORDER BY id",
                (user_id,),
            )
            nombres = [r["ml_nickname"] for r in cur.fetchall()]
            cur.execute("SELECT COALESCE(business_name, full_name) AS n FROM users WHERE id=%s", (user_id,))
            u = cur.fetchone() or {}
            nombre_cuenta = " / ".join(nombres) or u.get("n") or "tu cuenta"
            destinos = _destinatarios(conn, user_id, fila_settings, pausa_avisos.MAIL_COLECTA)
    finally:
        conn.close()

    excluir = {
        normalizar_telefono(t)
        for t in (telefono_receptor, remitente_telefono)
        if t and normalizar_telefono(t)
    }
    a_enviar = [
        t for t in destinos
        if normalizar_telefono(t) not in excluir
    ]
    if not a_enviar:
        return {"ok": True, "enviados": 0, "motivo": "sin_destinatarios"}

    datos = enriquecer_datos(f"WhatsApp {remitente_nombre or 'Mercado Libre'}", texto)
    mensaje = armar_mensaje_wa_colecta(
        texto,
        datos,
        cuenta=nombre_cuenta,
        telefono_receptor=telefono_receptor,
        remitente=remitente_nombre,
    )
    resultados = enviar(a_enviar, mensaje)
    ok_count = sum(1 for r in (resultados or []) if (r.get("result") or {}).get("ok"))
    logger.info(
        f"[WA colecta] Reenviado WhatsApp de colecta ({nombre_cuenta}) a {ok_count}/{len(a_enviar)} destinatarios"
    )
    return {"ok": True, "enviados": ok_count, "destinatarios": a_enviar, "mensaje": mensaje}


# ── Casilla y envío ───────────────────────────────────────────────────────────────

def leer_configuracion(env=None):
    env = os.environ if env is None else env
    usuario, clave = (env.get("COLECTAS_IMAP_USER") or "").strip(), env.get("COLECTAS_IMAP_PASSWORD") or ""
    if not (usuario and clave):
        return None
    try:
        max_horas = float(env.get("COLECTAS_MAX_HORAS") or MAX_HORAS_DEFECTO)
    except ValueError:
        max_horas = MAX_HORAS_DEFECTO
    return {
        "host": (env.get("COLECTAS_IMAP_HOST") or env.get("SMTP_HOST") or "").strip(),
        "port": int(env.get("COLECTAS_IMAP_PORT") or 993),
        "user": usuario, "password": clave, "max_horas": max_horas,
        "borrar": (env.get("COLECTAS_BORRAR") or "si").strip().lower() not in ("no", "0", "false"),
    }


def _conectar(cfg):
    imap = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    imap.login(cfg["user"], cfg["password"])
    imap.select("INBOX")
    return imap


def direcciones_del_mail(msg, propias=()):
    """Direcciones a las que llegó el mail (en minúscula), sin las de la casilla común de EnvioBot.

    El reenvío del servidor de correo deja intacto el "Para" original, que es la dirección donde
    Mercado Libre le escribe al cliente; y si el cliente lo reenvía manualmente o con filtro, su
    dirección viene en From / Reply-To / Return-Path."""
    valores = []
    for h in (
        "To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To", "Resent-To",
        "From", "Reply-To", "Return-Path", "Sender", "Resent-From",
    ):
        valores += [str(v) for v in msg.get_all(h, [])]
    direcciones = {
        a.strip().lower()
        for _n, a in getaddresses(valores)
        if a and not any(x in a.lower() for x in ("mercadolibre.", "mercadoenvios."))
    }
    return direcciones - {p.lower() for p in propias}


def cuentas_por_direccion(direcciones):
    """[(nombre de la cuenta, {teléfono: horario})] de las cuentas que configuraron alguna de esas direcciones.

    El nombre es el de la cuenta de Mercado Libre (MISTERNUT). Los destinatarios son los de la agenda de
    envíos de esa cuenta que pidieron este aviso, cada uno con su horario."""
    import alerts_engine
    import esquema
    from aviso_limite_colecta import _destinatarios
    from whatsapp_service import normalizar_telefono
    if not direcciones:
        return []
    conn = alerts_engine.get_db()
    try:
        with conn.cursor() as cur:
            if not esquema.tiene_columna(cur, "user_settings", "colecta_email"):   # migración 004
                return []
            cur.execute("""SELECT s.* FROM user_settings s JOIN users u ON u.id = s.user_id
                           WHERE s.colecta_email IS NOT NULL AND s.colecta_email <> ''
                             AND COALESCE(u.active, 1) = 1 AND COALESCE(u.is_blocked, 0) = 0""")
            filas = [f for f in cur.fetchall()
                     if direcciones & {d.strip().lower() for d in str(f["colecta_email"]).split(",") if d.strip()}]
            cuentas = {}
            for f in filas:
                cur.execute("SELECT ml_nickname FROM ml_credentials WHERE user_id=%s AND ml_nickname IS NOT NULL ORDER BY id", (f["user_id"],))
                nombres = [r["ml_nickname"] for r in cur.fetchall()]
                cur.execute("SELECT COALESCE(business_name, full_name) AS n FROM users WHERE id=%s", (f["user_id"],))
                u = cur.fetchone() or {}
                nombre = " / ".join(nombres) or u.get("n") or "tu cuenta"
                destinos = _destinatarios(conn, f["user_id"], f, pausa_avisos.MAIL_COLECTA)
                # varios usuarios de una misma cuenta comparten nombre: se junta y no se repite a nadie
                actual = cuentas.setdefault(nombre, {})
                vistos = {normalizar_telefono(t) for t in actual}
                for t, h in destinos.items():
                    if normalizar_telefono(t) not in vistos:
                        actual[t] = h
                        vistos.add(normalizar_telefono(t))
        return list(cuentas.items())
    finally:
        conn.close()


def _descartar(imap, num, cfg):
    """Mail ya resuelto: se borra de la casilla (que solo es de paso) o, si se prefiere guardarlo, queda como leído."""
    imap.store(num, "+FLAGS", "\\Deleted" if cfg.get("borrar", True) else "\\Seen")


def _enviar_whatsapp(telefonos, texto):
    from whatsapp_service import enviar_lote_con_demora
    return enviar_lote_con_demora(telefonos, texto)


def ejecutar(ahora=None, config=None, conectar=None, enviar=None, resolver=None):
    """Una pasada por la casilla. `conectar`, `enviar` y `resolver` se pueden reemplazar (tests).

    `resolver(direcciones)` devuelve [(nombre de la cuenta, {teléfono: horario})]."""
    res = {"leidos": 0, "avisados": 0, "ignorados": 0, "viejos": 0, "pendientes": 0, "sin_cuenta": 0}
    if not pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA):
        logger.info("[Mail colecta] Avisos pausados (ENVIOBOT_AVISOS): no se envía nada.")
        res["pausado"] = True
        return res
    cfg = config or leer_configuracion()
    if not cfg:
        logger.info("[Mail colecta] Sin casilla configurada: no se hace nada.")
        res["sin_configurar"] = True
        return res
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    enviar = enviar or _enviar_whatsapp
    resolver = resolver or cuentas_por_direccion
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
            cuentas = resolver(direcciones_del_mail(msg, propias=(cfg["user"],)))
            if not cuentas:
                res["sin_cuenta"] += 1   # nadie configuró esa dirección: se deja, y caduca solo
                logger.info(f"[Mail colecta] Mail de colecta sin cuenta asignada (¿falta cargar el mail en Configuración?): {asunto[:80]}")
                continue
            datos_mail = enriquecer_datos(asunto, cuerpo)
            enviado = False
            hay_alguien = False
            for nombre, destinos in cuentas:
                a_enviar = [t for t, h in destinos.items() if en_horario(h, ahora)]
                hay_alguien = hay_alguien or bool(destinos)
                if not a_enviar:
                    continue
                resultados = enviar(a_enviar, armar_mensaje(asunto, cuerpo, datos_mail, nombre))
                if any((r.get("result") or {}).get("ok") for r in (resultados or [])):
                    enviado = True
                    logger.info(f"[Mail colecta] Avisado por WhatsApp ({nombre}): {asunto[:80]}")
                else:
                    logger.error(f"[Mail colecta] No se pudo enviar el WhatsApp ({nombre}, {asunto[:80]}); se reintenta.")
            if enviado:
                _descartar(imap, num, cfg)
                res["avisados"] += 1
            elif not hay_alguien:
                res["sin_destinatarios"] = res.get("sin_destinatarios", 0) + 1   # nadie pidió este aviso: se deja y caduca
                logger.info("[Mail colecta] Nadie de la agenda recibe este aviso (ver el menú Avisos de Configuración).")
            else:
                res["pendientes"] += 1   # fuera de horario o falló: sale en la próxima corrida
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
