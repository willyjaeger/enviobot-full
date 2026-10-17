#!/usr/bin/env python3
"""
whatsapp_service.py - Servicio de Envío de Mensajes de WhatsApp
Soporta:
1. Micro-Gateway Baileys Local (127.0.0.1:8085) auto-hospedado en DonWeb VPS (costo $0, sin límites).
2. Evolution API (v1 / v2) auto-hospedada o remota.
3. Gateway HTTP genérico / UltraMsg / W-API.
4. Modo Simulación / Sandbox para pruebas locales seguras.
Configuración dinámica sincronizada con admin.enviobot.com.ar (site_settings).
"""

import os
import re
import time
import json
import logging
from datetime import datetime
import requests
import pymysql
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("whatsapp_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

# Variables de entorno por defecto
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "enviobot")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "enviobot_web")
DB_PORT = int(os.getenv("DB_PORT", 3306))

# Caché en memoria para no saturar MySQL en cada mensaje
_CONFIG_CACHE = None
_CONFIG_CACHE_TIME = 0
CACHE_TTL_SECONDS = 15


def obtener_configuracion_whatsapp() -> dict:
    """
    Lee la configuración de WhatsApp guardada en site_settings desde el panel admin.
    Posee una caché en memoria de 15 segundos para máxima eficiencia.
    """
    global _CONFIG_CACHE, _CONFIG_CACHE_TIME
    now = time.time()
    if _CONFIG_CACHE and (now - _CONFIG_CACHE_TIME < CACHE_TTL_SECONDS):
        return _CONFIG_CACHE

    cfg = {
        "enabled": True,
        "provider": os.getenv("WHATSAPP_PROVIDER", "gateway_local"),
        "api_url": os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8085").rstrip("/"),
        "api_key": os.getenv("EVOLUTION_API_KEY", ""),
        "instance_name": os.getenv("EVOLUTION_INSTANCE_NAME", "enviobot_full"),
        "business_phone": "+54 9 11 2859 4631",
        "gateway_url": os.getenv("WHATSAPP_GATEWAY_URL", "").rstrip("/"),
        "gateway_token": os.getenv("WHATSAPP_GATEWAY_TOKEN", ""),
        "simulation_mode": os.getenv("WHATSAPP_SIMULATION_MODE", "").lower() in ("true", "1", "yes"),
        "templates": {},
        "send_vcard_on_welcome": True,
        "vcard_name": "EnvioBot Full",
        "vcard_org": "EnvioBot",
        "vcard_title": "Alertas de Stock Full",
        "cadence": {
            "schedule_hours": "08:00, 14:00, 20:00",
            "cooldown_hours": 20,
            "consolidate_daily": True,
            "max_items_per_msg": 6,
            "pacing_delay_seconds": 3,
            "simulate_typing": True,
            "typing_duration_ms": 1500
        }
    }

    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT setting_key, setting_value 
                FROM site_settings 
                WHERE setting_key LIKE 'whatsapp_%'
            """)
            rows = cur.fetchall()
            for r in rows:
                k = r["setting_key"]
                v = r["setting_value"]
                if not v:
                    continue
                if k == "whatsapp_enabled":
                    cfg["enabled"] = str(v).lower() in ("true", "1", "yes")
                elif k == "whatsapp_provider":
                    cfg["provider"] = str(v).strip()
                elif k == "whatsapp_api_url":
                    cfg["api_url"] = str(v).rstrip("/")
                elif k == "whatsapp_api_key":
                    cfg["api_key"] = str(v).strip()
                elif k == "whatsapp_instance_name":
                    cfg["instance_name"] = str(v).strip()
                elif k == "whatsapp_business_phone":
                    cfg["business_phone"] = str(v).strip()
                elif k == "whatsapp_templates":
                    try:
                        cfg["templates"] = json.loads(v)
                    except Exception:
                        pass
                elif k == "whatsapp_cadence":
                    try:
                        cad = json.loads(v)
                        cfg["cadence"].update(cad)
                    except Exception:
                        pass
                elif k == "whatsapp_send_vcard_on_welcome":
                    cfg["send_vcard_on_welcome"] = str(v).lower() in ("true", "1", "yes")
                elif k == "whatsapp_vcard_name":
                    cfg["vcard_name"] = str(v).strip()
                elif k == "whatsapp_vcard_org":
                    cfg["vcard_org"] = str(v).strip()
        conn.close()
    except Exception as e:
        logger.warning(f"[WhatsApp Config] No se pudo leer site_settings ({e}), usando defaults/.env")

    # Ajuste de simulación si el provider seleccionado es simulation
    if cfg["provider"] == "simulation":
        cfg["simulation_mode"] = True

    _CONFIG_CACHE = cfg
    _CONFIG_CACHE_TIME = now
    return cfg


def normalizar_telefono(phone: str) -> str:
    """
    Normaliza el número de teléfono al formato internacional E.164 sin símbolos.
    Ejemplo Argentina: "+54 9 11 2859-4631" -> "5491128594631"
    """
    if not phone:
        return ""
    clean = re.sub(r"[^\d]", "", str(phone))
    
    # Ajustes comunes de Argentina
    if len(clean) == 10 and not clean.startswith("54"):
        clean = "549" + clean
    elif clean.startswith("54") and not clean.startswith("549") and len(clean) == 12:
        clean = "549" + clean[2:]
        
    return clean


def enviar_mensaje_whatsapp(telefono: str, mensaje: str) -> dict:
    """
    Envía un mensaje de WhatsApp a un destinatario según el proveedor activo.
    """
    cfg = obtener_configuracion_whatsapp()

    if not cfg["enabled"]:
        logger.info(f"[WhatsApp] Envío omitido: WhatsApp desactivado en admin.")
        return {"ok": False, "error": "WhatsApp está desactivado globalmente en admin.enviobot.com.ar"}

    clean_phone = normalizar_telefono(telefono)
    if not clean_phone:
        return {"ok": False, "error": "Número de teléfono inválido o vacío."}

    # 1. Modo Simulación
    if cfg["simulation_mode"] or cfg["provider"] == "simulation":
        logger.info(f"[SIMULACIÓN WHATSAPP] Enviando a {clean_phone}:\n{mensaje}")
        return {
            "ok": True,
            "simulated": True,
            "to": clean_phone,
            "message": "Mensaje procesado en modo simulación (configurado en admin.enviobot.com.ar)."
        }

    # 2. Micro-Gateway Local o Evolution API
    provider = cfg["provider"]
    api_url = cfg["api_url"] or "http://127.0.0.1:8085"
    instance = cfg["instance_name"] or "enviobot_full"

    if provider in ("gateway_local", "evolution"):
        url = f"{api_url}/message/sendText/{instance}"
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["apikey"] = cfg["api_key"]

        payload = {
            "number": clean_phone,
            "options": {
                "delay": cfg["cadence"].get("typing_duration_ms", 1200) if cfg["cadence"].get("simulate_typing", True) else 0,
                "presence": "composing" if cfg["cadence"].get("simulate_typing", True) else "available",
                "linkPreview": True
            },
            "textMessage": {
                "text": mensaje
            }
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            if r.status_code in (200, 201):
                res_data = r.json()
                logger.info(f"[{provider}] Mensaje enviado con éxito a {clean_phone}")
                return {"ok": True, "provider": provider, "response": res_data}
            else:
                logger.error(f"[{provider} Error] Status {r.status_code}: {r.text}")
                return {"ok": False, "provider": provider, "status_code": r.status_code, "error": r.text}
        except Exception as e:
            logger.error(f"[{provider} Exception] Error conectando con {url}: {e}")
            return {"ok": False, "provider": provider, "error": str(e)}

    # 3. Gateway HTTP alternativo (UltraMsg / W-API)
    if provider == "gateway_http" and cfg.get("gateway_url"):
        payload = {
            "token": cfg.get("gateway_token", ""),
            "to": clean_phone,
            "body": mensaje
        }
        try:
            r = requests.post(cfg["gateway_url"], json=payload, timeout=15)
            if r.status_code in (200, 201):
                logger.info(f"[Gateway HTTP] Mensaje enviado a {clean_phone}")
                return {"ok": True, "provider": "gateway_http", "response": r.text}
            else:
                logger.error(f"[Gateway HTTP Error] Status {r.status_code}: {r.text}")
                return {"ok": False, "provider": "gateway_http", "status_code": r.status_code, "error": r.text}
        except Exception as e:
            logger.error(f"[Gateway HTTP Exception] Error conectando: {e}")
            return {"ok": False, "provider": "gateway_http", "error": str(e)}

    return {"ok": False, "error": f"Proveedor '{provider}' no configurado o URL inválida."}


def enviar_contacto_vcard(telefono: str, contact_name: str = None, contact_phone: str = None, org: str = None, title: str = None, note: str = None, url: str = None) -> dict:
    """
    Envía una tarjeta de contacto interactiva (vCard 3.0) para que el destinatario
    pueda guardar 'EnvioBot Full' en su agenda con un solo toque.
    Esto hace que:
    1. El chat muestre 'EnvioBot Full' en lugar del número.
    2. Se elimine el cartel de 'Bloquear / Añadir a contactos'.
    3. Los enlaces web del panel se vuelvan directamente cliqueables.
    """
    cfg = obtener_configuracion_whatsapp()

    if not cfg["enabled"]:
        return {"ok": False, "error": "WhatsApp está desactivado globalmente en admin.enviobot.com.ar"}

    clean_phone = normalizar_telefono(telefono)
    if not clean_phone:
        return {"ok": False, "error": "Número de teléfono inválido o vacío."}

    name = contact_name or cfg.get("vcard_name", "EnvioBot Full")
    b_phone = contact_phone or cfg.get("business_phone", "+54 9 11 2859 4631")
    c_org = org or cfg.get("vcard_org", "EnvioBot")
    c_title = title or cfg.get("vcard_title", "Alertas de Stock Full")
    c_note = note or "Asistente oficial de alertas de reposición y fecha límite de colecta en Mercado Envíos Full."
    c_url = url or "https://enviobot.com.ar"

    if cfg["simulation_mode"] or cfg["provider"] == "simulation":
        logger.info(f"[SIMULACIÓN WHATSAPP] Enviando vCard '{name}' a {clean_phone}")
        return {
            "ok": True,
            "simulated": True,
            "to": clean_phone,
            "displayName": name,
            "message": f"vCard de {name} simulada con éxito."
        }

    provider = cfg["provider"]
    api_url = cfg["api_url"] or "http://127.0.0.1:8085"
    instance = cfg["instance_name"] or "enviobot_full"

    if provider in ("gateway_local", "evolution"):
        endpoint_url = f"{api_url}/message/sendContact/{instance}"
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["apikey"] = cfg["api_key"]

        payload = {
            "number": clean_phone,
            "contact": {
                "name": name,
                "phone": normalizar_telefono(b_phone),
                "org": c_org,
                "title": c_title,
                "url": c_url,
                "note": c_note
            }
        }

        try:
            r = requests.post(endpoint_url, headers=headers, json=payload, timeout=15)
            if r.status_code in (200, 201):
                res_data = r.json()
                logger.info(f"[{provider}] vCard '{name}' enviada con éxito a {clean_phone}")
                return {"ok": True, "provider": provider, "response": res_data}
            else:
                logger.error(f"[{provider} Error] Status {r.status_code}: {r.text}")
                return {"ok": False, "provider": provider, "status_code": r.status_code, "error": r.text}
        except Exception as e:
            logger.error(f"[{provider} Exception] Error conectando con {endpoint_url}: {e}")
            return {"ok": False, "provider": provider, "error": str(e)}

    return {"ok": False, "error": f"El proveedor '{provider}' no soporta envío directo de vCard."}


def enviar_lote_con_demora(destinatarios: list, mensaje: str, delay_segundos: int = None) -> list:
    """
    Envía el mensaje a una lista de teléfonos aplicando la demora configurada
    para evitar saturación de la cola y no encender alertas anti-spam de WhatsApp.
    """
    cfg = obtener_configuracion_whatsapp()
    if delay_segundos is None:
        delay_segundos = cfg["cadence"].get("pacing_delay_seconds", 3)

    resultados = []
    for idx, phone in enumerate(destinatarios):
        res = enviar_mensaje_whatsapp(phone, mensaje)
        resultados.append({"phone": phone, "result": res})
        if idx < len(destinatarios) - 1 and delay_segundos > 0:
            time.sleep(delay_segundos)
    return resultados


# ---------------------------------------------------------------------------
# PLANTILLAS DE MENSAJES CONFIGURABLES (ADMIN.ENVIOBOT.COM.AR)
# ---------------------------------------------------------------------------

def _render_template(template_str: str, variables: dict) -> str:
    """Reemplaza placeholders {{var}} o {var} en la plantilla dada."""
    res = template_str
    for k, v in variables.items():
        res = res.replace(f"{{{{{k}}}}}", str(v))
        res = res.replace(f"{{{k}}}", str(v))
    return res


def formatear_alerta_preventiva(nombre_usuario: str, deposito_nombre: str, items: list, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 1: Aviso Preventivo de Producción.
    """
    cfg = obtener_configuracion_whatsapp()
    custom_template = cfg.get("templates", {}).get("preventiva")
    max_items = cfg["cadence"].get("max_items_per_msg", 6)

    # Armar lista formateada de items
    items_texto = ""
    for it in items[:max_items]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        dias = it.get('days_left', 0)
        sug = it.get('suggested_restock_units', 0)
        items_texto += f"• *{sku_str}{it.get('title')[:35]}*\n  Quedan ~{dias}d de stock · Sugerido preparar: *{sug} un.*\n"

    if len(items) > max_items:
        items_texto += f"\n_... y {len(items) - max_items} artículos más._\n"

    if custom_template:
        return _render_template(custom_template, {
            "nombre": nombre_usuario,
            "deposito": deposito_nombre,
            "items": items_texto.strip(),
            "cantidad": len(items),
            "link": url_panel,
            "hora": datetime.now().strftime("%H:%M")
        })

    # Mensaje por defecto
    texto = (
        f"*EnvioBot Full — Planificación Semanal*\n"
        f"Hola {nombre_usuario}, tus ventas en MercadoLibre vienen a buen ritmo. Dentro de los próximos días vas a tener que pedir colecta para tu stock en *{deposito_nombre}*:\n\n"
        f"{items_texto}\n"
        f"*Acción recomendada:* Andá empaquetando o fabricando estas unidades para tenerlas listas en tu galpón.\n"
        f"Panel: {url_panel}"
    )
    return texto


def formatear_alerta_colecta_hoy(nombre_usuario: str, deposito_nombre: str, items: list, total_bultos: int, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 2: Llamado a la Acción (Día límite óptimo: "HOY").
    """
    cfg = obtener_configuracion_whatsapp()
    custom_template = cfg.get("templates", {}).get("colecta")
    max_items = cfg["cadence"].get("max_items_per_msg", 6)

    items_texto = ""
    for it in items[:max_items]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        sug = it.get('suggested_restock_units', 0)
        quiebre = it.get('stockout_date') or "Pronto"
        items_texto += f"• *{sku_str}{it.get('title')[:35]}*\n  Mandar: *{sug} un.* (Quiebra el: {quiebre})\n"

    if len(items) > max_items:
        items_texto += f"\n_... y {len(items) - max_items} artículos más en la lista._\n"

    if custom_template:
        return _render_template(custom_template, {
            "nombre": nombre_usuario,
            "deposito": deposito_nombre,
            "items": items_texto.strip(),
            "cantidad": len(items),
            "bultos": total_bultos,
            "link": url_panel,
            "hora": datetime.now().strftime("%H:%M")
        })

    texto = (
        f"*EnvioBot Full — PEDIR COLECTA HOY EN MERCADOLIBRE*\n"
        f"Hola {nombre_usuario}, hoy es la fecha límite para pedir turno a MeLi con destino a *{deposito_nombre}*.\n\n"
        f"*Resumen a despachar:* {len(items)} publicaciones · *{total_bultos} bultos totales*\n\n"
        f"{items_texto}\n"
        f"*Importante:* Si solicitás la colecta hoy en MeLi, el flete llega a tiempo antes de quebrar stock.\n"
        f"*Descargar Remito / Copiar Lista:* {url_panel}"
    )
    return texto


def formatear_alerta_critica(nombre_usuario: str, deposito_nombre: str, items: list, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 3: Alarma Crítica de Quiebre Inminente.
    """
    cfg = obtener_configuracion_whatsapp()
    custom_template = cfg.get("templates", {}).get("critica")
    max_items = cfg["cadence"].get("max_items_per_msg", 5)

    items_texto = ""
    for it in items[:max_items]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        stock = it.get('current_stock_full', 0)
        dias = it.get('days_left', 0)
        items_texto += f"• *{sku_str}{it.get('title')[:35]}*\n  Stock actual: *{stock} un.* ({dias}d de cobertura)\n"

    if len(items) > max_items:
        items_texto += f"\n_... y {len(items) - max_items} artículos más en estado crítico._\n"

    if custom_template:
        return _render_template(custom_template, {
            "nombre": nombre_usuario,
            "deposito": deposito_nombre,
            "items": items_texto.strip(),
            "cantidad": len(items),
            "link": url_panel,
            "hora": datetime.now().strftime("%H:%M")
        })

    texto = (
        f"*EnvioBot Full — ALARMA DE QUIEBRE CRÍTICO*\n"
        f"¡Atención {nombre_usuario}! Registramos artículos con riesgo inminente de quiebre en *{deposito_nombre}*:\n\n"
        f"{items_texto}\n"
        f"*Aviso urgente:* Tu publicación puede quedar pausada por MercadoLibre si no despachás mercadería cuanto antes.\n"
        f"Accedé al panel: {url_panel}"
    )
    return texto


def formatear_alerta_resumen_diario(nombre_usuario: str, deposito_nombre: str, items: list, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Resumen Matutino Consolidado de Cobertura.
    """
    cfg = obtener_configuracion_whatsapp()
    custom_template = cfg.get("templates", {}).get("resumen_diario")
    max_items = cfg["cadence"].get("max_items_per_msg", 8)

    items_texto = ""
    for it in items[:max_items]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        dias = it.get('days_left', 0)
        sug = it.get('suggested_restock_units', 0)
        items_texto += f"• *{sku_str}{it.get('title')[:30]}* (~{dias}d) → Reponer: *{sug}*\n"

    if len(items) > max_items:
        items_texto += f"\n_... y {len(items) - max_items} publicaciones más._\n"

    if custom_template:
        return _render_template(custom_template, {
            "nombre": nombre_usuario,
            "deposito": deposito_nombre,
            "items": items_texto.strip(),
            "cantidad": len(items),
            "link": url_panel,
            "hora": datetime.now().strftime("%H:%M")
        })

    return (
        f"*EnvioBot Full — Resumen Matutino de Cobertura*\n"
        f"Hola {nombre_usuario}, acá tenés el estado de tu stock en *{deposito_nombre}* para hoy:\n\n"
        f"{items_texto}\n"
        f"*Total de alertas activas:* {len(items)} artículos.\n"
        f"Revisar sugerencias y armar envío: {url_panel}"
    )


def formatear_alerta_verificacion_whatsapp(nombre_usuario: str, link_verificacion: str) -> str:
    """
    Mensaje de verificación del número de WhatsApp: corto, con un único link.
    """
    # No se usa la plantilla "verificacion" del admin: es la vieja (código + vCard adjunta)
    # y hablaría de cosas que ya no se mandan.
    return (
        f"*EnvioBot Full*\n"
        f"Hola {nombre_usuario}, este número fue registrado para recibir las alertas de stock y de colecta en Mercado Envíos Full.\n\n"
        f"Tocá acá para verificar tu número:\n{link_verificacion}"
    )


def enviar_verificacion_whatsapp(telefono: str, nombre_usuario: str, link_verificacion: str) -> dict:
    """
    Envía un único mensaje con el link de verificación. Al tocar el botón de esa
    página el número queda verificado y se descarga el contacto de EnvioBot Full
    para la agenda (ya no se manda la tarjeta vCard por el chat).
    """
    msg = formatear_alerta_verificacion_whatsapp(nombre_usuario, link_verificacion)
    imagen = link_verificacion.split("/v/")[0] + "/img/verificar-whatsapp.png"
    res = enviar_imagen_whatsapp(telefono, imagen, link_verificacion)
    if res.get("ok"):
        return res
    logger.warning(f"[WhatsApp] No se pudo mandar la imagen ({res.get('error')}); va solo el texto.")
    return enviar_mensaje_whatsapp(telefono, msg)


def enviar_imagen_whatsapp(telefono: str, url_imagen: str, texto: str) -> dict:
    """Envía una imagen (por URL pública) con el texto de pie. Solo Evolution/gateway local."""
    cfg = obtener_configuracion_whatsapp()
    if not cfg["enabled"]:
        return {"ok": False, "error": "WhatsApp está desactivado globalmente en admin.enviobot.com.ar"}
    clean_phone = normalizar_telefono(telefono)
    if not clean_phone:
        return {"ok": False, "error": "Número de teléfono inválido o vacío."}
    if cfg["simulation_mode"] or cfg["provider"] == "simulation":
        logger.info(f"[SIMULACIÓN WHATSAPP] Imagen {url_imagen} a {clean_phone}:\n{texto}")
        return {"ok": True, "simulated": True, "to": clean_phone}
    if cfg["provider"] not in ("gateway_local", "evolution"):
        return {"ok": False, "error": "El proveedor no soporta imágenes."}

    api_url = cfg["api_url"] or "http://127.0.0.1:8085"
    instance = cfg["instance_name"] or "enviobot_full"
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["apikey"] = cfg["api_key"]
    payload = {
        "number": clean_phone,
        "options": {"delay": 1200, "presence": "composing"},
        "mediaMessage": {"mediatype": "image", "caption": texto, "media": url_imagen}
    }
    try:
        r = requests.post(f"{api_url}/message/sendMedia/{instance}", headers=headers, json=payload, timeout=20)
        if r.status_code in (200, 201):
            return {"ok": True, "provider": cfg["provider"], "response": r.json()}
        return {"ok": False, "status_code": r.status_code, "error": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generar_vcard_contacto() -> str:
    """Contenido .vcf de EnvioBot Full para guardar en la agenda del teléfono."""
    cfg = obtener_configuracion_whatsapp()
    nombre = cfg.get("vcard_name", "EnvioBot Full")
    org = cfg.get("vcard_org", "EnvioBot")
    titulo = cfg.get("vcard_title", "Alertas de Stock Full")
    tel = normalizar_telefono(cfg.get("business_phone", "+54 9 11 2859 4631"))
    foto = ""
    try:
        import base64
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "contacto_logo.jpg"), "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        lineas = ["PHOTO;ENCODING=b;TYPE=JPEG:" + b64[:40]] + [" " + b64[i:i + 72] for i in range(40, len(b64), 72)]
        foto = "\r\n".join(lineas) + "\r\n"
    except Exception as e:
        logger.warning(f"[WhatsApp] vCard sin logo: {e}")
    return (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        f"FN:{nombre}\r\n"
        f"N:;{nombre};;;\r\n"
        f"ORG:{org}\r\n"
        f"TITLE:{titulo}\r\n"
        f"{foto}"
        f"TEL;TYPE=CELL,VOICE:+{tel}\r\n"
        "URL:https://enviobot.com.ar\r\n"
        "NOTE:Alertas de reposición y fecha límite de colecta en Mercado Envíos Full.\r\n"
        "END:VCARD\r\n"
    )


# Compatibilidad hacia atrás
WHATSAPP_SIMULATION_MODE = os.getenv("WHATSAPP_SIMULATION_MODE", "").lower() in ("true", "1", "yes")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8085")
WHATSAPP_GATEWAY_URL = os.getenv("WHATSAPP_GATEWAY_URL", "")
