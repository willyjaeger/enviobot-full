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

_RE_FRANJA = re.compile(
    r"(?:entre(?:\s+las)?|de(?:\s+las)?)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(?:hs?\s*)?(?:y|a)(?:\s+las)?\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*hs|\b)",
    re.I,
)
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
_RE_ENVIO = re.compile(r"Env[ií]os?\s*(?:Full\s*)?(?:N\.?\s*[º°o]?\s*|#\s*)(\d{6,})", re.I)
_FRASES_RETIRADA = (
    "retiramos tu colecta",
    "retiramos la colecta",
    "retiramos tu envio",
    "retiramos tus productos",
    "ya retiramos",
    "colecta retirada",
    "fue retirada",
    "retiro realizado",
    "retiraron la colecta",
    "retiraron la mercaderia",
    "colectamos tus envios",
    "colectamos tu envio",
    "tu remito ya esta disponible",
    "pallets colectados",
    "bultos colectados",
    "bultos y/o pallets colectados",
    "en camino al centro de almacenamiento",
    "en camino a full",
)
_FRASES_NO_RETIRADA = (
    "no pudimos retirar",
    "no se pudo retirar",
    "no fueron colectados",
    "pasaremos a retirar",
    "vamos a retirar",
    "vamos a enviarte una nueva colecta",
    "vamos a enviarte una colecta extra",
    "reprogram",
)

_PROMPT_IA = """Analizá esta comunicación y determiná si es una notificación oficial de Mercado Libre / Mercado Envíos Full sobre una colecta (retiro en depósito del vendedor con destino a la bodega Full de Mercado Libre).
Devolvé ÚNICAMENTE un objeto JSON válido con estas claves (usá "" si un dato no aparece):
{
  "es_colecta_ml": true,
  "resumen": "Si es_colecta_ml es true: resumen claro y directo en español argentino (1 a 3 oraciones máximo, ideal para WhatsApp) explicando qué informa el mensaje (ej: horario de retiro confirmado, código de autorización, colecta ya retirada, reprogramación o demora), sin saludos genéricos ni texto legal. Si es_colecta_ml es false: dejá ''.",
  "evento": "Usá 'retirada' si el mensaje confirma que el camión YA retiró/colectó la mercadería (ej: 'Colectamos tus envíos Full', 'Tu remito ya está disponible'); 'programada' si informa fecha/horario futuro o en camino; 'reprogramada' o 'incidencia' si hubo un problema o colecta extra; o '' si es otro aviso o si es_colecta_ml es false.",
  "fecha": "Fecha de la colecta si la menciona (ej: '19 de octubre')",
  "desde": "Hora de inicio de la franja en formato HH:MM (ej: '16:00')",
  "hasta": "Hora de fin de la franja en formato HH:MM (ej: '18:00')",
  "codigo": "Código de autorización alfanumérico si aparece (ej: '9F769D2F')",
  "transportista": "Nombre del chofer o transportista si aparece",
  "patente": "Patente o dominio del vehículo si aparece (ej: 'AB304TX')",
  "transportadora": "Empresa transportadora si aparece (ej: 'Dos Haches')",
  "envio": "Número de envío de Mercado Libre (solo dígitos, ej: '78889570')"
}
REGLA ESTRICTA DE FILTRADO ("es_colecta_ml"):
- Poné `true` SOLO cuando el mensaje sea genuinamente una comunicación oficial de Mercado Libre / Mercado Envíos Full (o del transporte asignado a una colecta de Mercado Envíos Full) referida a una colecta de Full (programación de retiro, franja horaria, código de autorización, datos del transportista/patente, confirmación de bultos/pallets colectados, remito disponible, reprogramación o incidencia de colecta).
- Poné `false` en CUALQUIER otro caso: charlas con clientes o proveedores, pedidos mayoristas o minoristas, consultas de stock/cajas/envíos comunes, publicidad, promociones de Mercado Libre o Mercado Pago, preguntas o reclamos de compradores, ventas individuales, códigos de verificación (2FA) o cualquier conversación ajena a una colecta de Mercado Envíos Full."""


def es_confirmacion_retiro(texto, datos=None):
    """True si el texto o el análisis de IA indican que la colecta ya fue retirada por el transporte."""
    limpio = _sin_acentos(texto or "")
    if any(f in limpio for f in _FRASES_NO_RETIRADA):
        return False
    if datos and str(datos.get("evento") or "").strip().lower() == "retirada":
        return True
    return any(f in limpio for f in _FRASES_RETIRADA)


def extraer_datos(texto):
    """Lo que se pueda sacar del texto; lo que no aparece queda afuera (el formato del mail puede cambiar)."""
    d = {}
    texto = texto or ""
    for f in _RE_FRANJA.finditer(texto):
        h1, m1, h2, m2 = int(f.group(1)), f.group(2), int(f.group(3)), f.group(4)
        # Evita confundir "19 de octubre ... y 2 bultos" con una franja horaria cuando no tiene :MM ni dice hs/las
        frag = f.group(0).lower()
        if not m1 and not m2 and "hs" not in frag and "las" not in frag:
            continue
        if 0 <= h1 <= 23 and 0 <= h2 <= 23:
            d["desde"] = "%02d:%s" % (h1, m1 or "00")
            d["hasta"] = "%02d:%s" % (h2, m2 or "00")
            antes = texto[max(0, f.start() - 80):f.start()]
            fechas = _RE_FECHA.findall(antes)
            if fechas:
                d["fecha"] = fechas[-1].strip()
            break
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
    if es_confirmacion_retiro(texto):
        d["evento"] = "retirada"
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
    es_ml = parsed.get("es_colecta_ml")
    if isinstance(es_ml, bool):
        resultado["es_colecta_ml"] = es_ml
    elif isinstance(es_ml, str) and es_ml.strip().lower() in ("true", "false", "si", "sí", "no"):
        resultado["es_colecta_ml"] = es_ml.strip().lower() in ("true", "si", "sí")

    for k in ("resumen", "evento", "fecha", "desde", "hasta", "codigo", "transportista", "patente", "transportadora", "envio"):
        val = parsed.get(k)
        if isinstance(val, str):
            val = re.sub(r"\s+", " ", val).strip()
            if val:
                if k in ("codigo", "patente"):
                    resultado[k] = val.upper()
                elif k == "evento":
                    resultado[k] = val.lower()
                else:
                    resultado[k] = val
    if resultado.get("envio"):
        solo_digitos = re.sub(r"\D+", "", resultado["envio"])
        if solo_digitos:
            resultado["envio"] = solo_digitos
    return resultado


def enriquecer_datos(asunto, cuerpo, env=None, post=None):
    """Combina los datos extraídos por expresiones regulares con el análisis de IA (si está activa)."""
    texto_completo = f"{asunto or ''}\n{cuerpo or ''}"
    datos = extraer_datos(texto_completo)
    ia = analizar_con_ia(asunto, cuerpo, env=env, post=post)
    if "es_colecta_ml" in ia:
        datos["es_colecta_ml"] = ia["es_colecta_ml"]
        if ia["es_colecta_ml"] is False:
            datos.pop("evento", None)
            datos.pop("resumen", None)
            return datos
    for k, v in ia.items():
        if k == "es_colecta_ml":
            continue
        if v and not datos.get(k):
            datos[k] = v
    if ia.get("resumen"):
        datos["resumen"] = ia["resumen"]
    if es_confirmacion_retiro(texto_completo, datos):
        datos["evento"] = "retirada"
    elif datos.get("evento") == "retirada":
        datos.pop("evento", None)
    return datos


def marcar_colecta_retirada(user_ids, datos, ahora=None, conn=None):
    """Si `datos` confirma que la colecta fue retirada, pasa el envío correspondiente de `scheduled`
    a `in_transit` y deja registrado `updated_at` para medir tiempos reales de tránsito a Full."""
    if not datos or datos.get("evento") != "retirada" or not user_ids:
        return None
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    cerrar = False
    if conn is None:
        import alerts_engine
        conn = alerts_engine.get_db()
        cerrar = True
    try:
        uids = tuple({int(u) for u in user_ids if u})
        if not uids:
            return None
        placeholders = ",".join(["%s"] * len(uids))
        envio_num = (datos.get("envio") or "").strip()
        hoy = ahora.date()
        hace_7_dias = hoy - timedelta(days=7)
        with conn.cursor() as cur:
            fila = None
            if envio_num:
                cur.execute(
                    f"SELECT id, shipment_code, status FROM inbound_shipments "
                    f"WHERE user_id IN ({placeholders}) AND (shipment_code=%s OR meli_inbound_id=%s) "
                    f"ORDER BY id DESC LIMIT 1",
                    uids + (f"ML-{envio_num}", envio_num),
                )
                fila = cur.fetchone()
            if not fila:
                cur.execute(
                    f"SELECT id, shipment_code, status FROM inbound_shipments "
                    f"WHERE user_id IN ({placeholders}) AND status IN ('scheduled', 'in_transit') "
                    f"AND pickup_date BETWEEN %s AND %s "
                    f"ORDER BY (CASE WHEN status='scheduled' THEN 0 ELSE 1 END), pickup_date DESC, id DESC LIMIT 1",
                    uids + (hace_7_dias, hoy),
                )
                fila = cur.fetchone()
            if not fila:
                return None
            if fila.get("status") == "scheduled":
                cur.execute(
                    "UPDATE inbound_shipments SET status='in_transit', meli_inbound_status='picked_up', updated_at=%s WHERE id=%s",
                    (ahora.replace(tzinfo=None), fila["id"]),
                )
                logger.info(
                    f"[Colecta retiro] Envío {fila['shipment_code']} (id={fila['id']}) pasó de scheduled a in_transit"
                )
            datos["colecta_en_transito"] = fila["shipment_code"]
            return fila["shipment_code"]
    except Exception as e:
        logger.warning(f"[Colecta retiro] No se pudo actualizar estado a in_transit: {e}")
        return None
    finally:
        if cerrar and conn is not None:
            conn.close()


def armar_mensaje(asunto, cuerpo, datos, cuenta=None):
    """Texto de WhatsApp: de qué cuenta es, los datos que se pudieron leer y el resumen de IA (o extracto)."""
    de = f" de *{cuenta}*" if cuenta else ""
    if datos.get("evento") == "retirada":
        lineas = [f"Mercado Libre confirmó que retiraron la colecta{de}"]
    elif datos.get("desde") and datos.get("hasta"):
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
    if datos.get("colecta_en_transito"):
        lineas.append(f"Estado en EnvioBot: *{datos['colecta_en_transito']}* pasó a *En tránsito a Full*")
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

_WA_MARCA_ML = (
    "mercadolibre",
    "mercado libre",
    "mercadoenvios",
    "mercado envios",
    "envios full",
    "meli",
)
_WA_TERMINOS_COLECTA = (
    "colecta",
    "colectamos",
    "colectado",
    "colectados",
    "transportista",
    "transportadora",
    "codigo de autorizacion",
    "cod. autorizacion",
    "cod autorizacion",
    "remito",
    "centro de almacenamiento",
)
_WA_LOGISTICA_COLECTA = (
    "retiro",
    "retirar",
    "retiramos",
    "camion",
    "chofer",
    "bulto",
    "bultos",
    "pallet",
    "pallets",
    "reprogram",
    "patente",
)


def es_wa_de_colecta(texto, remitente=""):
    """True si un WhatsApp entrante al teléfono vinculado es una comunicación de Mercado Libre sobre una colecta."""
    if len((texto or "").strip()) < 10:
        return False
    limpio = _sin_acentos(f"{remitente}\n{texto}")
    # Si trae datos estructurados inequívocos de colecta de ML (código de autorización o patente + chofer/envío)
    datos_rx = extraer_datos(texto or "")
    if datos_rx.get("codigo") or (datos_rx.get("patente") and (datos_rx.get("transportista") or datos_rx.get("transportadora"))):
        return True
    nombra_ml = any(re.search(rf"\b{re.escape(p)}\b", limpio) for p in _WA_MARCA_ML)
    if not nombra_ml:
        return False
    if any(p in limpio for p in _WA_TERMINOS_COLECTA):
        return True
    coincidencias = sum(1 for p in _WA_LOGISTICA_COLECTA if re.search(rf"\b{re.escape(p)}", limpio))
    return coincidencias >= 2


def armar_mensaje_wa_colecta(texto, datos, cuenta=None, telefono_receptor=None, remitente=None):
    """Arma el aviso de WhatsApp cuando Mercado Libre o el transporte escriben al WhatsApp vinculado."""
    de = f" de *{cuenta}*" if cuenta else ""
    tel_txt = f" ({telefono_receptor})" if telefono_receptor else ""
    lineas = [f"Mercado Libre / Colecta escribió al WhatsApp{de}{tel_txt}"]
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
    if datos.get("colecta_en_transito"):
        lineas.append(f"Estado en EnvioBot: *{datos['colecta_en_transito']}* pasó a *En tránsito a Full*")
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


def autorizado_webhook_interno(remote_addr, headers, env=None):
    """Valida que el llamado al webhook interno venga directo de localhost (no vía proxy nginx)
    y traiga el token compartido propio WA_INTERNAL_SECRET en X-Internal-Token."""
    import hmac
    env = os.environ if env is None else env
    headers = headers or {}
    if remote_addr not in ("127.0.0.1", "::1", "localhost"):
        return False
    # Detrás de nginx, cualquier petición externa trae X-Forwarded-For / X-Real-IP
    if headers.get("X-Forwarded-For") or headers.get("X-Real-IP"):
        return False
    secreto = (env.get("WA_INTERNAL_SECRET") or "").strip()
    token = str(headers.get("X-Internal-Token") or "").strip()
    if not secreto or not token:
        return False
    return hmac.compare_digest(token.encode("utf-8"), secreto.encode("utf-8"))


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
    lo resume con IA y lo reenvía a los destinatarios de la agenda que estén en su horario."""
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

    datos = enriquecer_datos(f"WhatsApp {remitente_nombre or ''}".strip(), texto)
    if datos.get("es_colecta_ml") is False:
        logger.info(f"[WA colecta] Descartado por filtro IA (no es colecta de Mercado Libre): {texto[:80]!r}")
        return {"ok": True, "ignorado": True, "motivo": "descartado_por_ia"}
    colecta_actualizada = marcar_colecta_retirada([user_id], datos, ahora=ahora)

    excluir = {
        normalizar_telefono(t)
        for t in (telefono_receptor, remitente_telefono)
        if t and normalizar_telefono(t)
    }
    a_enviar = [
        t for t, h in destinos.items()
        if normalizar_telefono(t) not in excluir and en_horario(h, ahora)
    ]
    if not a_enviar:
        return {
            "ok": True,
            "enviados": 0,
            "motivo": "sin_destinatarios_en_horario",
            "colecta_en_transito": colecta_actualizada,
        }

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
    return {
        "ok": True,
        "enviados": ok_count,
        "destinatarios": a_enviar,
        "mensaje": mensaje,
        "colecta_en_transito": colecta_actualizada,
    }


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


_RE_DOMINIO_ML = re.compile(r"^(?:[a-z0-9.-]+\.)?mercado(?:libre|envios)\.com(?:\.[a-z]{2,3})?$", re.I)


def direcciones_del_mail(msg, propias=()):
    """Direcciones a las que llegó el mail (en minúscula), sin las de la casilla común de EnvioBot.

    El reenvío del servidor de correo deja intacto el "Para" original, que es la dirección donde
    Mercado Libre le escribe al cliente: con eso se sabe de qué cuenta es."""
    valores = []
    for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To", "Resent-To"):
        valores += [str(v) for v in msg.get_all(h, [])]
    direcciones = {a.strip().lower() for _n, a in getaddresses(valores) if a}
    return direcciones - {p.lower() for p in propias}


def es_remitente_confiable(msg, propias=()):
    """Evita que un tercero mande un mail falso con Cc al colecta_email del cliente:
    - Si hay cabeceras Authentication-Results con dkim=fail (y sin dkim=pass), se rechaza.
      (En un reenvío automático es normal que spf dé fail porque reenvía otro servidor, pero dkim se mantiene).
    - Si el From tiene dirección de correo, su dominio debe ser de Mercado Libre o coincidir
      con alguno de los dominios destinatarios del propio cliente."""
    auth_headers = " ".join(
        str(v).lower()
        for h in ("Authentication-Results", "ARC-Authentication-Results")
        for v in msg.get_all(h, [])
    )
    if "dkim=fail" in auth_headers and "dkim=pass" not in auth_headers:
        return False
    remitentes = [a.strip().lower() for _n, a in getaddresses([str(v) for v in msg.get_all("From", [])]) if a and "@" in a]
    if not remitentes:
        return True
    dom_from = remitentes[0].rsplit("@", 1)[-1]
    if _RE_DOMINIO_ML.match(dom_from):
        return True
    destinos = direcciones_del_mail(msg, propias=propias)
    dominios_destino = {d.rsplit("@", 1)[-1] for d in destinos if "@" in d}
    return dom_from in dominios_destino


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


def user_ids_por_direccion(direcciones):
    """Lista de user_id activos que configuraron alguna de esas direcciones en colecta_email."""
    import alerts_engine
    import esquema
    if not direcciones:
        return []
    try:
        conn = alerts_engine.get_db()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            if not esquema.tiene_columna(cur, "user_settings", "colecta_email"):
                return []
            cur.execute("""SELECT s.user_id, s.colecta_email FROM user_settings s JOIN users u ON u.id = s.user_id
                           WHERE s.colecta_email IS NOT NULL AND s.colecta_email <> ''
                             AND COALESCE(u.active, 1) = 1 AND COALESCE(u.is_blocked, 0) = 0""")
            return [
                f["user_id"] for f in cur.fetchall()
                if direcciones & {d.strip().lower() for d in str(f["colecta_email"]).split(",") if d.strip()}
            ]
    except Exception:
        return []
    finally:
        conn.close()


def _descartar(imap, num, cfg):
    """Mail ya resuelto: se borra de la casilla (que solo es de paso) o, si se prefiere guardarlo, queda como leído."""
    imap.store(num, "+FLAGS", "\\Deleted" if cfg.get("borrar", True) else "\\Seen")


def _enviar_whatsapp(telefonos, texto):
    from whatsapp_service import enviar_lote_con_demora
    return enviar_lote_con_demora(telefonos, texto)


def ejecutar(ahora=None, config=None, conectar=None, enviar=None, resolver=None, actualizar_retiro=None):
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
            if not es_de_colecta(asunto, cuerpo, str(msg.get("From") or "")) or not es_remitente_confiable(msg, propias=(cfg["user"],)):
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
            dirs_mail = direcciones_del_mail(msg, propias=(cfg["user"],))
            cuentas = resolver(dirs_mail)
            if not cuentas:
                res["sin_cuenta"] += 1   # nadie configuró esa dirección: se deja, y caduca solo
                logger.info(f"[Mail colecta] Mail de colecta sin cuenta asignada (¿falta cargar el mail en Configuración?): {asunto[:80]}")
                continue
            datos_mail = enriquecer_datos(asunto, cuerpo)
            if datos_mail.get("es_colecta_ml") is False:
                logger.info(f"[Mail colecta] Descartado por filtro IA (no es colecta de Mercado Libre): {asunto[:80]}")
                _descartar(imap, num, cfg)
                res["ignorados"] += 1
                continue
            if datos_mail.get("evento") == "retirada":
                if actualizar_retiro is not None:
                    actualizar_retiro(dirs_mail, datos_mail, ahora)
                else:
                    uids = user_ids_por_direccion(dirs_mail)
                    if uids:
                        marcar_colecta_retirada(uids, datos_mail, ahora=ahora)
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


# ── Lectura directa en modo SOLO LECTURA de la casilla del cliente (sin reenvíos) ──

_PROVEEDORES_IMAP = {
    "gmail.com": ["imap.gmail.com"],
    "googlemail.com": ["imap.gmail.com"],
    "outlook.com": ["outlook.office365.com"],
    "hotmail.com": ["outlook.office365.com"],
    "live.com": ["outlook.office365.com"],
    "live.com.ar": ["outlook.office365.com"],
    "msn.com": ["outlook.office365.com"],
    "yahoo.com": ["imap.mail.yahoo.com"],
    "yahoo.com.ar": ["imap.mail.yahoo.com"],
    "icloud.com": ["imap.mail.me.com"],
}


def asegurar_columnas_mail_directo(cur):
    """Asegura las columnas en user_settings para conexión directa IMAP de solo lectura."""
    import esquema
    definiciones = (
        ("colecta_email_password", "VARCHAR(255) NULL"),
        ("colecta_imap_host", "VARCHAR(255) NULL"),
        ("colecta_mail_vistos", "TEXT NULL"),
    )
    for col, tipo in definiciones:
        if not esquema.tiene_columna(cur, "user_settings", col):
            try:
                cur.execute(f"ALTER TABLE user_settings ADD COLUMN {col} {tipo}")
                esquema.olvidar()
            except Exception as e:
                logger.warning(f"[Mail colecta directo] No se pudo agregar columna {col}: {e}")


def candidatos_imap(email_addr, host_preferido=None):
    """Devuelve la lista ordenada de servidores IMAP SSL (puerto 993) posibles para un mail."""
    email_addr = (email_addr or "").strip().lower()
    if "@" not in email_addr:
        return []
    dom = email_addr.rsplit("@", 1)[-1]
    lista = []
    if host_preferido and host_preferido.strip():
        lista.append(host_preferido.strip().lower())
    for h in _PROVEEDORES_IMAP.get(dom, []):
        if h not in lista:
            lista.append(h)
    for h in (f"mail.{dom}", f"imap.{dom}", dom):
        if h not in lista:
            lista.append(h)
    return lista


def _conectar_imap_ssl(host, port=993, timeout=6):
    return imaplib.IMAP4_SSL(host, port, timeout=timeout)


def verificar_conexion_imap(email_addr, password, host_preferido=None, conectar_ssl=None):
    """Prueba conectarse en modo SOLO LECTURA (`readonly=True`) a la casilla del cliente.
    Devuelve `(ok, host_detectado, error_msg)`."""
    email_addr = (email_addr or "").strip().lower()
    password = (password or "").strip()
    if not email_addr or not password:
        return False, None, "Completá el mail y la contraseña."
    conectar_fn = conectar_ssl or _conectar_imap_ssl
    candidatos = candidatos_imap(email_addr, host_preferido=host_preferido)
    if not candidatos:
        return False, None, "El mail no es válido."

    ultimo_error = ""
    error_credenciales = False
    for host in candidatos:
        imap = None
        try:
            imap = conectar_fn(host, 993, 6)
            imap.login(email_addr, password)
            tipo, _ = imap.select("INBOX", readonly=True)
            if tipo == "OK":
                return True, host, None
        except imaplib.IMAP4.error as e:
            error_credenciales = True
            ultimo_error = str(e)
        except Exception as e:
            ultimo_error = str(e)
        finally:
            if imap is not None:
                try:
                    imap.logout()
                except Exception:
                    pass
    if error_credenciales:
        if "gmail.com" in email_addr:
            return False, None, "Contraseña rechazada por Gmail. Si tenés verificación en 2 pasos, usá una Contraseña de Aplicación de Google."
        return False, None, "El servidor de correo rechazó la contraseña. Revisá que sea la clave con la que entrás a tu Webmail."
    return False, None, f"No pudimos conectar con el servidor de correo ({ultimo_error or 'sin respuesta'})."


def _id_unico_mail(msg, num_bytes):
    mid = str(msg.get("Message-ID") or "").strip()
    if mid:
        return mid[:180]
    fecha = str(msg.get("Date") or "").strip()
    asunto = str(msg.get("Subject") or "").strip()[:60]
    num_str = num_bytes.decode("utf-8", errors="ignore") if isinstance(num_bytes, bytes) else str(num_bytes)
    return f"uid:{num_str}:{fecha}:{asunto}"[:180]


def ejecutar_casillas_directas(ahora=None, enviar=None, conectar_ssl=None, max_horas=MAX_HORAS_DEFECTO):
    """Lee en modo SOLO LECTURA (`readonly=True`) las casillas de los clientes que guardaron su contraseña.
    No borra, no marca como leído ni descarga nada a disco; guarda solo los Message-ID ya avisados."""
    res = {"cuentas": 0, "leidos": 0, "avisados": 0, "pendientes": 0, "errores": 0}
    if not pausa_avisos.puede_enviar(pausa_avisos.MAIL_COLECTA):
        res["pausado"] = True
        return res

    import alerts_engine
    from aviso_limite_colecta import _destinatarios

    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    enviar = enviar or _enviar_whatsapp
    conectar_fn = conectar_ssl or _conectar_imap_ssl

    try:
        conn = alerts_engine.get_db()
    except Exception:
        return res

    try:
        with conn.cursor() as cur:
            asegurar_columnas_mail_directo(cur)
            cur.execute("""
                SELECT s.*
                FROM user_settings s
                JOIN users u ON u.id = s.user_id
                WHERE s.colecta_email IS NOT NULL AND s.colecta_email <> ''
                  AND s.colecta_email_password IS NOT NULL AND s.colecta_email_password <> ''
                  AND COALESCE(u.active, 1) = 1 AND COALESCE(u.is_blocked, 0) = 0
            """)
            filas = cur.fetchall() or []
    finally:
        conn.close()

    for f in filas:
        user_id = f["user_id"]
        email_principal = str(f["colecta_email"]).split(",")[0].strip().lower()
        password = str(f.get("colecta_email_password") or "").strip()
        host_guardado = (f.get("colecta_imap_host") or "").strip()
        if not email_principal or not password:
            continue

        res["cuentas"] += 1
        try:
            vistos = json.loads(f.get("colecta_mail_vistos") or "[]")
            if not isinstance(vistos, list):
                vistos = []
        except Exception:
            vistos = []
        vistos_set = set(vistos)
        vistos_modificado = False

        hosts = candidatos_imap(email_principal, host_preferido=host_guardado)
        imap = None
        host_ok = None
        for h in hosts:
            try:
                imap = conectar_fn(h, 993, 8)
                imap.login(email_principal, password)
                tipo, _ = imap.select("INBOX", readonly=True)
                if tipo == "OK":
                    host_ok = h
                    break
            except Exception:
                if imap is not None:
                    try:
                        imap.logout()
                    except Exception:
                        pass
                    imap = None

        if not imap or not host_ok:
            res["errores"] += 1
            logger.warning(f"[Mail colecta directo] No se pudo conectar a {email_principal} (user_id={user_id})")
            continue

        try:
            tipo, datos = imap.search(None, "ALL")
            todos_ids = datos[0].split() if tipo == "OK" and datos and datos[0] else []
            ultimos_ids = todos_ids[-25:]  # solo los últimos 25 correos de la bandeja

            conn_u = alerts_engine.get_db()
            try:
                with conn_u.cursor() as cur:
                    if host_ok != host_guardado:
                        cur.execute("UPDATE user_settings SET colecta_imap_host=%s WHERE user_id=%s", (host_ok, user_id))
                    cur.execute("SELECT ml_nickname FROM ml_credentials WHERE user_id=%s AND ml_nickname IS NOT NULL ORDER BY id", (user_id,))
                    nombres = [r["ml_nickname"] for r in cur.fetchall()]
                    cur.execute("SELECT COALESCE(business_name, full_name) AS n FROM users WHERE id=%s", (user_id,))
                    u = cur.fetchone() or {}
                    nombre_cuenta = " / ".join(nombres) or u.get("n") or "tu cuenta"
                    destinos = _destinatarios(conn_u, user_id, f, pausa_avisos.MAIL_COLECTA)
            finally:
                conn_u.close()

            for num in ultimos_ids:
                tipo_f, partes = imap.fetch(num, "(BODY.PEEK[])")
                if tipo_f != "OK" or not partes or not partes[0]:
                    continue
                msg = email.message_from_bytes(partes[0][1], policy=email.policy.default)
                mid = _id_unico_mail(msg, num)
                if mid in vistos_set:
                    continue

                try:
                    fecha_mail = parsedate_to_datetime(str(msg.get("Date")))
                    if fecha_mail.tzinfo is None:
                        fecha_mail = fecha_mail.replace(tzinfo=ahora.tzinfo)
                    if ahora - fecha_mail > timedelta(hours=max_horas):
                        continue
                except (TypeError, ValueError):
                    pass

                asunto = str(msg.get("Subject") or "")
                cuerpo = texto_del_mail(msg)
                if not es_de_colecta(asunto, cuerpo, str(msg.get("From") or "")) or not es_remitente_confiable(msg):
                    continue

                res["leidos"] += 1
                datos_mail = enriquecer_datos(asunto, cuerpo)
                if datos_mail.get("es_colecta_ml") is False:
                    logger.info(f"[Mail colecta directo] Descartado por filtro IA (no es colecta de ML): {asunto[:80]}")
                    vistos.append(mid)
                    vistos_set.add(mid)
                    vistos_modificado = True
                    continue
                if datos_mail.get("evento") == "retirada":
                    marcar_colecta_retirada([user_id], datos_mail, ahora=ahora)

                a_enviar = [t for t, h in destinos.items() if en_horario(h, ahora)]
                if not a_enviar:
                    res["pendientes"] += 1
                    continue

                resultados = enviar(a_enviar, armar_mensaje(asunto, cuerpo, datos_mail, nombre_cuenta))
                if any((r.get("result") or {}).get("ok") for r in (resultados or [])):
                    res["avisados"] += 1
                    vistos.append(mid)
                    vistos_set.add(mid)
                    vistos_modificado = True
                    logger.info(f"[Mail colecta directo] Avisado por WhatsApp ({nombre_cuenta}): {asunto[:80]}")

            if vistos_modificado:
                vistos_recortados = vistos[-80:]
                conn_v = alerts_engine.get_db()
                try:
                    with conn_v.cursor() as cur:
                        cur.execute(
                            "UPDATE user_settings SET colecta_mail_vistos=%s WHERE user_id=%s",
                            (json.dumps(vistos_recortados), user_id),
                        )
                finally:
                    conn_v.close()
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r_buzon = ejecutar()
    r_directo = ejecutar_casillas_directas()
    print({"buzon": r_buzon, "directas": r_directo})

