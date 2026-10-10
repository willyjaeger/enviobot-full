#!/usr/bin/env python3
"""
whatsapp_service.py - Servicio de Envío de Mensajes de WhatsApp
Soporta:
1. Evolution API (v1 / v2) auto-hospedada en DonWeb VPS o servidor dedicado.
2. Gateway HTTP genérico / UltraMsg / W-API.
3. Modo Simulación / Sandbox para pruebas locales seguras.
"""

import os
import re
import time
import json
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("whatsapp_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

# Configuración de Evolution API
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE_NAME", "enviobot_full")

# Configuración de Gateway Alternativo (UltraMsg / W-API / Custom)
WHATSAPP_GATEWAY_URL = os.getenv("WHATSAPP_GATEWAY_URL", "").rstrip("/")
WHATSAPP_GATEWAY_TOKEN = os.getenv("WHATSAPP_GATEWAY_TOKEN", "")

# Modo Sandbox / Simulación cuando no hay API configurada
WHATSAPP_SIMULATION_MODE = os.getenv("WHATSAPP_SIMULATION_MODE", "").lower() in ("true", "1", "yes") or (not EVOLUTION_API_URL and not WHATSAPP_GATEWAY_URL)


def normalizar_telefono(phone: str) -> str:
    """
    Normaliza el número de teléfono al formato internacional E.164 sin símbolos.
    Ejemplo Argentina: "+54 9 11 1234-5678" -> "5491112345678"
    """
    if not phone:
        return ""
    # Quitar cualquier carácter no numérico
    clean = re.sub(r"[^\d]", "", str(phone))
    
    # Ajustes comunes de Argentina (añadir código de país si falta)
    if len(clean) == 10 and not clean.startswith("54"):
        # Ej: 1112345678 -> 5491112345678
        clean = "549" + clean
    elif clean.startswith("54") and not clean.startswith("549") and len(clean) == 12:
        # 541112345678 -> 5491112345678
        clean = "549" + clean[2:]
        
    return clean


def enviar_mensaje_whatsapp(telefono: str, mensaje: str) -> dict:
    """
    Envía un mensaje de WhatsApp a un destinatario.
    Devuelve un diccionario con status, ok (bool), message_id (opcional) y detalle.
    """
    clean_phone = normalizar_telefono(telefono)
    if not clean_phone:
        return {"ok": False, "error": "Número de teléfono inválido o vacío."}

    # 1. Modo Simulación si no hay credenciales configuradas
    if WHATSAPP_SIMULATION_MODE:
        logger.info(f"[SIMULACIÓN WHATSAPP] Enviando a {clean_phone}:\n{mensaje}")
        return {
            "ok": True,
            "simulated": True,
            "to": clean_phone,
            "message": "Mensaje procesado en modo simulación (configurar EVOLUTION_API_URL para envíos reales)."
        }

    # 2. Envío a través de Evolution API (v1 / v2)
    if EVOLUTION_API_URL:
        url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
        headers = {
            "Content-Type": "application/json",
            "apikey": EVOLUTION_API_KEY
        }
        payload = {
            "number": clean_phone,
            "options": {
                "delay": 1200,
                "presence": "composing",
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
                logger.info(f"[Evolution API] Mensaje enviado con éxito a {clean_phone}")
                return {"ok": True, "provider": "evolution", "response": res_data}
            else:
                logger.error(f"[Evolution API Error] Status {r.status_code}: {r.text}")
                return {"ok": False, "provider": "evolution", "status_code": r.status_code, "error": r.text}
        except Exception as e:
            logger.error(f"[Evolution API Exception] Error conectando: {e}")
            return {"ok": False, "provider": "evolution", "error": str(e)}

    # 3. Envío a través de Gateway Genérico / UltraMsg
    if WHATSAPP_GATEWAY_URL:
        # Formato estándar UltraMsg / W-API
        payload = {
            "token": WHATSAPP_GATEWAY_TOKEN,
            "to": clean_phone,
            "body": mensaje
        }
        try:
            r = requests.post(WHATSAPP_GATEWAY_URL, json=payload, timeout=15)
            if r.status_code in (200, 201):
                logger.info(f"[Gateway HTTP] Mensaje enviado a {clean_phone}")
                return {"ok": True, "provider": "gateway_http", "response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}
            else:
                logger.error(f"[Gateway HTTP Error] Status {r.status_code}: {r.text}")
                return {"ok": False, "provider": "gateway_http", "status_code": r.status_code, "error": r.text}
        except Exception as e:
            logger.error(f"[Gateway HTTP Exception] Error conectando: {e}")
            return {"ok": False, "provider": "gateway_http", "error": str(e)}

    return {"ok": False, "error": "No hay ningún proveedor de WhatsApp configurado."}


def enviar_lote_con_demora(destinatarios: list, mensaje: str, delay_segundos: int = 3) -> list:
    """
    Envía el mensaje a una lista de teléfonos aplicando una pequeña pausa entre cada uno
    para evitar saturación de la cola y no encender alertas anti-spam de WhatsApp.
    """
    resultados = []
    for idx, phone in enumerate(destinatarios):
        res = enviar_mensaje_whatsapp(phone, mensaje)
        resultados.append({"phone": phone, "result": res})
        if idx < len(destinatarios) - 1:
            time.sleep(delay_segundos)
    return resultados


# ---------------------------------------------------------------------------
# PLANTILLAS DE MENSAJES PROGRESIVOS (CADENCIA DE 3 NIVELES)
# ---------------------------------------------------------------------------

def formatear_alerta_preventiva(nombre_usuario: str, deposito_nombre: str, items: list, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 1: Aviso Preventivo de Producción (3 a 5 días antes de la fecha límite).
    Permite al vendedor preparar mercadería en fábrica o taller.
    """
    texto = (
        f"📦 *EnvioBot Full — Planificación Semanal*\n"
        f"Hola {nombre_usuario}, tus ventas en MercadoLibre vienen a buen ritmo. Dentro de los próximos días vas a tener que pedir colecta para tu stock en *{deposito_nombre}*:\n\n"
    )
    for it in items[:6]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        dias = it.get('days_left', 0)
        sug = it.get('suggested_restock_units', 0)
        texto += f"• *{sku_str}{it.get('title')[:35]}*\n  ⏳ Quedan ~{dias}d de stock · Sugerido preparar: *{sug} un.*\n"

    if len(items) > 6:
        texto += f"\n_... y {len(items) - 6} artículos más._\n"

    texto += f"\n💡 *Acción recomendada:* Andá empaquetando o fabricando estas unidades para tenerlas listas en tu galpón.\n👉 Panel: {url_panel}"
    return texto


def formatear_alerta_colecta_hoy(nombre_usuario: str, deposito_nombre: str, items: list, total_bultos: int, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 2: Llamado a la Acción (Día límite óptimo: "HOY").
    El camión debe pedirse hoy en MeLi para no quebrar.
    """
    texto = (
        f"🚛 *EnvioBot Full — PEDIR COLECTA HOY EN MERCADOLIBRE*\n"
        f"Hola {nombre_usuario}, hoy es la fecha óptima para pedir turno a MeLi con destino a *{deposito_nombre}*.\n\n"
        f"📊 *Resumen a despachar:* {len(items)} publicaciones · *{total_bultos} bultos totales*\n\n"
    )
    for it in items[:6]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        sug = it.get('suggested_restock_units', 0)
        quiebre = it.get('stockout_date') or "Pronto"
        texto += f"• *{sku_str}{it.get('title')[:35]}*\n  Mandar: *{sug} un.* (Quiebra el: {quiebre})\n"

    if len(items) > 6:
        texto += f"\n_... y {len(items) - 6} artículos más en la lista._\n"

    texto += (
        f"\n⚠️ *Importante:* Si solicitás la colecta hoy en MeLi, el flete llega a tiempo antes de quebrar stock.\n"
        f"👉 *Descargar Remito / Copiar Lista:* {url_panel}"
    )
    return texto


def formatear_alerta_critica(nombre_usuario: str, deposito_nombre: str, items: list, url_panel: str = "https://enviobot.com.ar/full") -> str:
    """
    Nivel 3: Alarma Crítica de Quiebre Inminente (Último aviso de emergencia).
    El stock se terminará antes de que llegue cualquier camión habitual.
    """
    texto = (
        f"🚨 *EnvioBot Full — ALARMA DE QUIEBRE CRÍTICO*\n"
        f"¡Atención {nombre_usuario}! Registramos artículos con riesgo inminente de quiebre en *{deposito_nombre}*:\n\n"
    )
    for it in items[:5]:
        sku_str = f"[{it.get('sku')}] " if it.get("sku") else ""
        stock = it.get('current_stock_full', 0)
        dias = it.get('days_left', 0)
        texto += f"• ⚠️ *{sku_str}{it.get('title')[:35]}*\n  Stock actual: *{stock} un.* ({dias}d de cobertura)\n"

    if len(items) > 5:
        texto += f"\n_... y {len(items) - 5} artículos más en estado crítico._\n"

    texto += (
        f"\n🛑 *Peligro:* Tu publicación quedará pausada por MercadoLibre si no despachás mercadería de inmediato.\n"
        f"👉 Entrá urgente al panel: {url_panel}"
    )
    return texto
