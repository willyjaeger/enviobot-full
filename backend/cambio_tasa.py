#!/usr/bin/env python3
"""Aviso de cambio notorio en el ritmo de venta de un producto que tiene stock.

Compara las ventas por día de la última semana contra las de los 23 días anteriores (descontando
los días en que el producto estuvo sin stock). Si bajó o subió de forma notoria avisa:
  - en el panel (ventana "Avisos"), siempre, apenas se detecta;
  - por WhatsApp, solo dentro del horario de cada destinatario: si se detecta fuera de horario no se
    manda ni se anota como enviado, y la próxima corrida dentro del horario lo manda.

Usa solo tablas que ya existen (forecasts, full_items, stock_daily si está, alert_logs): no hay migración.
El historial de aviso se guarda en alert_logs con alert_type 'cambio_tasa' (channel 'panel' o 'whatsapp').

Lo llama el motor de alertas después de cada sincronización. Para que el WhatsApp salga ni bien se
abre el horario conviene además correrlo cada 10 minutos desde cron (no llama a MercadoLibre, solo lee
lo que ya sincronizó el worker); cargar esa línea en el servidor es un cambio aparte, con OK de Guillermo:
    */10 * * * * <venv>/bin/python <app>/backend/cambio_tasa.py >> /var/log/enviobot_full.log 2>&1
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta

import alerts_engine
import esquema
import proyeccion
from horario_whatsapp import whatsapp_permitido
from whatsapp_service import enviar_lote_con_demora, normalizar_telefono, obtener_configuracion_whatsapp

logger = logging.getLogger("cambio_tasa")

TIPO_ALERTA = "cambio_tasa"
DIAS_RECIENTE = 7
DIAS_BASE = 23            # los 30 días menos la última semana
MIN_DIAS_RECIENTE = 4     # días con stock en la última semana para confiar en el ritmo reciente
MIN_DIAS_BASE = 10        # idem para el período de comparación
UMBRAL_BAJA = 0.40        # cae 40 % o más
UMBRAL_SUBA = 0.50        # sube 50 % o más
MIN_UNIDADES = 5          # menos que esto en una semana es ruido, no tendencia
REPETIR_DIAS = 7          # no se vuelve a avisar del mismo producto y sentido antes de una semana
MAX_PRODUCTOS_WA = 8


def evaluar(v7, v30, sin7=0, sin30=0, stock=1):
    """Devuelve None si el ritmo es normal, o un dict con sentido ('baja'/'suba'), ritmo de antes
    ('antes'), ritmo actual ('ahora', unidades por día) y variación en % ('pct', None si antes era 0)."""
    if (stock or 0) <= 0:
        return None  # sin stock la venta cae por falta de producto, no por la demanda
    dias_recientes = DIAS_RECIENTE - sin7
    dias_base = DIAS_BASE - max(0, sin30 - sin7)
    if dias_recientes < MIN_DIAS_RECIENTE or dias_base < MIN_DIAS_BASE:
        return None
    ahora = v7 / float(dias_recientes)
    antes = max(0, v30 - v7) / float(dias_base)

    if antes <= 0:
        if v7 >= MIN_UNIDADES:
            return {"sentido": "suba", "antes": 0.0, "ahora": round(ahora, 1), "pct": None}
        return None
    cambio = ahora / antes - 1
    if cambio <= -UMBRAL_BAJA and antes * DIAS_RECIENTE >= MIN_UNIDADES:
        sentido = "baja"
    elif cambio >= UMBRAL_SUBA and v7 >= MIN_UNIDADES:
        sentido = "suba"
    else:
        return None
    return {"sentido": sentido, "antes": round(antes, 1), "ahora": round(ahora, 1), "pct": int(round(cambio * 100))}


def _clave_producto(f):
    return (f.get("inventory_id") or "").strip() or (f.get("sku") or "").strip().upper() \
        or f"{f['item_id']}_{f.get('variation_id') or ''}"


def detectar(conn, user_id, hoy=None):
    """Lista de cambios notorios del usuario. Agrupa por producto físico (inventory_id o SKU) porque
    la misma mercadería puede estar en varias publicaciones y el stock es uno solo."""
    hoy = hoy or datetime.utcnow().date()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.item_id, i.variation_id, i.sku, i.inventory_id, i.title, i.current_stock_full,
                   f.sales_last_7d, f.sales_last_30d
            FROM full_items i
            JOIN forecasts f ON f.user_id = i.user_id AND f.item_id = i.item_id
                 AND ( (i.variation_id IS NULL AND f.variation_id IS NULL) OR (f.variation_id = i.variation_id) )
            WHERE i.user_id = %s AND i.is_monitored = 1
        """, (user_id,))
        filas = cur.fetchall()
        sin = {}
        if filas and esquema.tiene_tabla(cur, "stock_daily"):
            cur.execute("""
                SELECT item_id, variation_id,
                       SUM(stock_max = 0 AND day > %s) AS sin7, SUM(stock_max = 0) AS sin30
                FROM stock_daily WHERE user_id = %s AND day > %s
                GROUP BY item_id, variation_id
            """, (hoy - timedelta(days=7), user_id, hoy - timedelta(days=30)))
            for r in cur.fetchall():
                sin[(r["item_id"], r["variation_id"] or "")] = (int(r["sin7"] or 0), int(r["sin30"] or 0))

    grupos = {}
    for f in filas:
        g = grupos.setdefault(_clave_producto(f), {"v7": 0, "v30": 0, "stock": 0, "principal": f, "ventas": -1, "sin": (0, 0)})
        v7, v30 = int(f.get("sales_last_7d") or 0), int(f.get("sales_last_30d") or 0)
        g["v7"] += v7
        g["v30"] += v30
        if v30 > g["ventas"]:  # el título y la publicación que se muestran son los del que más vende
            g["ventas"], g["principal"] = v30, f
            g["sin"] = sin.get((f["item_id"], f.get("variation_id") or ""), (0, 0))
        g["stock"] = max(g["stock"], int(f.get("current_stock_full") or 0))  # mismo inventario, mismo stock

    cambios = []
    for g in grupos.values():
        ev = evaluar(g["v7"], g["v30"], g["sin"][0], g["sin"][1], g["stock"])
        if not ev:
            continue
        p = g["principal"]
        ev.update({
            "item_id": p["item_id"], "variation_id": p.get("variation_id") or "",
            "sku": (p.get("sku") or "").strip(), "titulo": (p.get("title") or "").strip(), "stock": g["stock"],
        })
        cambios.append(ev)
    # primero las bajas (lo que más hay que mirar) y, dentro de cada sentido, las más fuertes
    cambios.sort(key=lambda c: (c["sentido"] != "baja", -abs(c["pct"] if c["pct"] is not None else 999)))
    return cambios


def _clave(c):
    return f"{c['item_id']}:{c['variation_id']}:{c['sentido']}"[:48]


def _etiqueta(c):
    sku = f", SKU {c['sku']}" if c["sku"] else ""
    return f"{c['titulo'][:60]} (publicación {c['item_id']}{sku})"


def _ritmo(x):
    return f"{x:.1f}".replace(".", ",")


def texto_whatsapp(cambios, app_url=""):
    n = len(cambios)
    lineas = [f"EnvioBot Full: detectamos un cambio notorio en el ritmo de venta de {n} producto{'s' if n != 1 else ''} que tienen stock."]
    for c in cambios[:MAX_PRODUCTOS_WA]:
        verbo = "bajó" if c["sentido"] == "baja" else "subió"
        pct = f" ({c['pct']:+d} %)" if c["pct"] is not None else ""
        lineas.append(f"- {_etiqueta(c)}: {verbo} de {_ritmo(c['antes'])} a {_ritmo(c['ahora'])} unidades por día{pct}.")
    if n > MAX_PRODUCTOS_WA:
        lineas.append(f"- y {n - MAX_PRODUCTOS_WA} más, en el panel.")
    lineas.append("Te recomendamos verificar qué sucede y si tenés stock suficiente para la próxima colecta"
                  + (f": {app_url}" if app_url else "."))
    return "\n".join(lineas)


def _registro_panel(c):
    """Lo que se guarda para la ventana de Avisos (alert_logs.message es corto, por eso va compacto)."""
    return json.dumps({"s": c["sentido"], "a": c["antes"], "n": c["ahora"], "p": c["pct"], "sku": c["sku"],
                       "st": c["stock"], "t": c["titulo"][:70]}, ensure_ascii=False, separators=(",", ":"))


def texto_panel(registro):
    """Frase para mostrar en el panel a partir de lo guardado. Devuelve (titulo, detalle) o None."""
    try:
        d = json.loads(registro)
        verbo = "bajó" if d["s"] == "baja" else "subió"
        pct = f" ({d['p']:+d} %)" if d.get("p") is not None else ""
        return {
            "sentido": d["s"], "producto": d.get("t", ""), "sku": d.get("sku", ""), "stock": d.get("st"),
            "detalle": f"El ritmo de venta {verbo} de {_ritmo(d['a'])} a {_ritmo(d['n'])} unidades por día{pct}.",
        }
    except (ValueError, KeyError, TypeError):
        return None


def _hash_corto(clave):
    return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:10]


def procesar_usuario(conn, user_id, ahora=None):
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    res = {"user_id": user_id, "detectados": 0, "avisos_panel": 0, "mensajes_whatsapp": 0}
    cambios = detectar(conn, user_id)
    res["detectados"] = len(cambios)
    if not cambios:
        return res
    horas = REPETIR_DIAS * 24

    # 1) Ventana de avisos del panel: se anota apenas se detecta, no depende del horario.
    for c in cambios:
        if not alerts_engine.ya_se_envio_alerta_hoy(conn, user_id, TIPO_ALERTA, _clave(c), horas_cooldown=horas, channel="panel"):
            alerts_engine.registrar_alerta_en_log(conn, user_id, _clave(c), TIPO_ALERTA, _registro_panel(c), channel="panel")
            res["avisos_panel"] += 1

    # 2) WhatsApp: solo a quien está dentro de su horario; lo que no sale hoy sale en la próxima corrida habilitada.
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone() or {"notify_whatsapp": True}
    if not settings.get("notify_whatsapp", True) or not obtener_configuracion_whatsapp().get("enabled", True):
        return res
    from aviso_limite_colecta import _destinatarios
    destinos = _destinatarios(conn, user_id, settings)
    for tel, horario in destinos.items():
        if not whatsapp_permitido(ahora, horario):
            continue
        pendientes = [c for c in cambios if not alerts_engine.ya_se_envio_alerta_hoy(
            conn, user_id, TIPO_ALERTA, f"wa:{normalizar_telefono(tel)}:{_hash_corto(_clave(c))}", horas_cooldown=horas, channel="whatsapp")]
        if not pendientes:
            continue
        texto = texto_whatsapp(pendientes, alerts_engine.APP_URL)
        enviar_lote_con_demora([tel], texto)
        for c in pendientes:
            alerts_engine.registrar_alerta_en_log(
                conn, user_id, f"wa:{normalizar_telefono(tel)}:{_hash_corto(_clave(c))}", TIPO_ALERTA, texto, channel="whatsapp")
        res["mensajes_whatsapp"] += 1
        logger.info(f"[Cambio de ritmo] user_id={user_id}: aviso de {len(pendientes)} producto(s) enviado")
    return res


def ejecutar_global(ahora=None):
    conn = alerts_engine.get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE active=1 AND is_blocked=0")
            usuarios = [f["id"] for f in cur.fetchall()]
        total = 0
        for uid in usuarios:
            try:
                total += procesar_usuario(conn, uid, ahora)["mensajes_whatsapp"]
            except Exception as e:  # un usuario con problemas no frena a los demás
                logger.error(f"[Cambio de ritmo] user_id={uid}: {e}")
        return total
    finally:
        conn.close()


if __name__ == "__main__":
    ejecutar_global()
