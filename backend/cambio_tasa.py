#!/usr/bin/env python3
"""Aviso de cambio notorio en el ritmo de venta de un producto que tiene stock.

Compara las ventas por día de la última semana contra las de los 23 días anteriores (descontando
los días en que el producto estuvo sin stock). Si bajó o subió de forma notoria avisa:
  - en el panel (ventana "Avisos"), siempre, apenas se detecta;
  - por WhatsApp, solo dentro del horario de cada destinatario: si se detecta fuera de horario no se
    manda ni se anota como enviado. Cuando llega el horario se VUELVE A CONTROLAR antes de mandar:
    si la situación sigue (o cambió) se manda con los números de ese momento; si volvió a lo normal no
    se manda nada y en el panel queda anotado que se revirtió.

Usa solo tablas que ya existen (forecasts, full_items, stock_daily si está, alert_logs): no hay migración.
El historial se guarda en alert_logs con alert_type 'cambio_tasa' (channel 'panel' o 'whatsapp').
Un aviso del panel tiene clave '<producto>:<sentido>'; su reversión, '<producto>:rev-<sentido>'.

Lo llama el motor de alertas después de cada sincronización (cada 4 horas). Para que el WhatsApp
pendiente salga en cuanto se abre el horario conviene además correrlo cada 30 minutos desde cron (no
llama a MercadoLibre, solo vuelve a leer lo que ya sincronizó el worker); cargar esa línea en el
servidor es un cambio aparte, con OK de Guillermo:
    */30 * * * * <venv>/bin/python <app>/backend/cambio_tasa.py >> /var/log/enviobot_full.log 2>&1
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
REPETIR_DIAS = 7          # cuánto tiempo se sigue un aviso en el panel
MAX_PRODUCTOS_WA = 8
ESPERA_MAX_DIAS = 5       # un aviso que no pudo salir en 5 días (fin de semana largo incluido) ya es viejo


def ritmos(v7, v30, sin7=0, sin30=0, stock=1):
    """(antes, ahora) en unidades por día, o None si no hay datos suficientes para medir
    (sin stock, o demasiados días sin stock en la semana o en el período de comparación)."""
    if (stock or 0) <= 0:
        return None  # sin stock la venta cae por falta de producto, no por la demanda
    dias_recientes = DIAS_RECIENTE - sin7
    dias_base = DIAS_BASE - max(0, sin30 - sin7)
    if dias_recientes < MIN_DIAS_RECIENTE or dias_base < MIN_DIAS_BASE:
        return None
    return max(0, v30 - v7) / float(dias_base), v7 / float(dias_recientes)


def evaluar(v7, v30, sin7=0, sin30=0, stock=1):
    """Devuelve None si el ritmo es normal, o un dict con sentido ('baja'/'suba'), ritmo de antes
    ('antes'), ritmo actual ('ahora', unidades por día) y variación en % ('pct', None si antes era 0)."""
    r = ritmos(v7, v30, sin7, sin30, stock)
    if not r:
        return None
    antes, ahora = r
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


def _gk(clave_producto):
    return hashlib.sha1(clave_producto.encode("utf-8")).hexdigest()[:12]


def detectar(conn, user_id, hoy=None):
    """(cambios, medibles). `cambios`: cambios notorios del usuario. `medibles`: {producto: ritmo actual}
    de los productos que se pudieron medir (sirve para saber si uno ya volvió a lo normal).
    Agrupa por producto físico (inventory_id o SKU) porque la misma mercadería puede estar en varias
    publicaciones y el stock es uno solo."""
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

    cambios, medibles = [], {}
    for clave_prod, g in grupos.items():
        r = ritmos(g["v7"], g["v30"], g["sin"][0], g["sin"][1], g["stock"])
        if not r:
            continue
        gk = _gk(clave_prod)
        medibles[gk] = round(r[1], 1)
        ev = evaluar(g["v7"], g["v30"], g["sin"][0], g["sin"][1], g["stock"])
        if not ev:
            continue
        p = g["principal"]
        ev.update({
            "gk": gk, "item_id": p["item_id"], "variation_id": p.get("variation_id") or "",
            "sku": (p.get("sku") or "").strip(), "titulo": (p.get("title") or "").strip(), "stock": g["stock"],
        })
        cambios.append(ev)
    # primero las bajas (lo que más hay que mirar) y, dentro de cada sentido, las más fuertes
    cambios.sort(key=lambda c: (c["sentido"] != "baja", -abs(c["pct"] if c["pct"] is not None else 999)))
    return cambios, medibles


def _clave(c):
    return f"{c['gk']}:{c['sentido']}"


def _clave_rev(gk, sentido):
    return f"{gk}:rev-{sentido}"


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


def _registro_panel(c, revertido=False):
    """Lo que se guarda para la ventana de Avisos (alert_logs.message es corto, por eso va compacto)."""
    d = {"s": c["sentido"], "a": c["antes"], "n": c["ahora"], "p": c["pct"], "sku": c["sku"],
         "st": c["stock"], "t": c["titulo"][:70], "i": c["item_id"]}
    if revertido:
        d["r"] = 1
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def texto_panel(registro):
    """Lo que muestra la ventana de Avisos a partir de lo guardado. None si el registro no sirve."""
    try:
        d = json.loads(registro)
        base = {"sentido": d["s"], "producto": d.get("t", ""), "sku": d.get("sku", ""), "stock": d.get("st"),
                "item_id": d.get("i", ""), "revertido": bool(d.get("r"))}
        if d.get("r"):
            base["detalle"] = (f"La situación se revirtió: el ritmo de venta volvió a la normalidad "
                               f"({_ritmo(d['n'])} unidades por día; antes del aviso era {_ritmo(d['a'])}). No hace falta hacer nada.")
        else:
            verbo = "bajó" if d["s"] == "baja" else "subió"
            pct = f" ({d['p']:+d} %)" if d.get("p") is not None else ""
            base["detalle"] = f"El ritmo de venta {verbo} de {_ritmo(d['a'])} a {_ritmo(d['n'])} unidades por día{pct}."
        return base
    except (ValueError, KeyError, TypeError):
        return None


def _desde_registro(clave, registro):
    """Reconstruye el cambio a partir de lo guardado en el panel (clave 'producto:sentido')."""
    try:
        d = json.loads(registro)
        return {"sentido": d["s"], "antes": d["a"], "ahora": d["n"], "pct": d.get("p"), "item_id": d.get("i", ""),
                "variation_id": "", "gk": clave.split(":", 1)[0], "sku": d.get("sku", ""),
                "titulo": d.get("t", ""), "stock": d.get("st")}
    except (ValueError, KeyError, TypeError):
        return None


def _hash_corto(texto):
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]


def _filas_panel(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, item_id, message, sent_at FROM alert_logs
            WHERE user_id=%s AND alert_type=%s AND channel='panel' AND sent_at >= %s
            ORDER BY id ASC
        """, (user_id, TIPO_ALERTA, datetime.utcnow() - timedelta(days=REPETIR_DIAS)))
        return cur.fetchall()


def _activos(filas):
    """{clave 'producto:sentido': fila} de los avisos que siguen abiertos: el último de cada clave
    que no tiene después un aviso de reversión."""
    abiertos = {}
    for f in filas:
        gk, _, resto = f["item_id"].partition(":")
        if resto.startswith("rev-"):
            abiertos.pop(f"{gk}:{resto[4:]}", None)
        else:
            abiertos[f["item_id"]] = f
    return abiertos


def procesar_usuario(conn, user_id, ahora=None):
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    res = {"user_id": user_id, "detectados": 0, "avisos_panel": 0, "revertidos": 0, "mensajes_whatsapp": 0}
    cambios, medibles = detectar(conn, user_id)
    res["detectados"] = len(cambios)
    actuales = {_clave(c): c for c in cambios}
    activos = _activos(_filas_panel(conn, user_id))
    if not cambios and not activos:
        return res

    # 1) Ventana de avisos: lo nuevo se anota apenas se detecta (no depende del horario)...
    for clave, c in actuales.items():
        if clave not in activos:
            alerts_engine.registrar_alerta_en_log(conn, user_id, clave, TIPO_ALERTA, _registro_panel(c), channel="panel")
            res["avisos_panel"] += 1
    # ...y lo que ya no se cumple se anota como revertido (una sola vez).
    for clave, fila in activos.items():
        gk, sentido = clave.split(":", 1)
        if clave in actuales or gk not in medibles:
            continue  # sigue igual, o no se puede medir (sin stock): no se dice nada
        previo = _desde_registro(clave, fila["message"])
        if previo:
            previo["ahora"] = medibles[gk]
            alerts_engine.registrar_alerta_en_log(conn, user_id, _clave_rev(gk, sentido), TIPO_ALERTA,
                                                  _registro_panel(previo, revertido=True), channel="panel")
            res["revertidos"] += 1

    # 2) WhatsApp. Se manda recién cuando el destinatario está en horario, y para entonces ya se volvió a
    # controlar (arriba): solo van los avisos que SIGUEN abiertos, con los números de este momento.
    # Un aviso que no pudo salir en ESPERA_MAX_DIAS (fin de semana largo incluido) ya es viejo.
    activos = _activos(_filas_panel(conn, user_id))
    limite = datetime.utcnow() - timedelta(days=ESPERA_MAX_DIAS)
    vigentes = [(c, activos[k]) for k, c in actuales.items() if k in activos and activos[k]["sent_at"] >= limite]
    if not vigentes:
        return res
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        settings = cur.fetchone() or {"notify_whatsapp": True}
    if not settings.get("notify_whatsapp", True) or not obtener_configuracion_whatsapp().get("enabled", True):
        return res
    from aviso_limite_colecta import _destinatarios
    horas = REPETIR_DIAS * 24
    for tel, horario in _destinatarios(conn, user_id, settings).items():
        if not whatsapp_permitido(ahora, horario):
            continue
        marcas = {_clave(c): f"wa:{normalizar_telefono(tel)}:{_hash_corto(_clave(c) + ':' + str(fila['id']))}" for c, fila in vigentes}
        pendientes = [c for c, _ in vigentes if not alerts_engine.ya_se_envio_alerta_hoy(
            conn, user_id, TIPO_ALERTA, marcas[_clave(c)], horas_cooldown=horas, channel="whatsapp")]
        if not pendientes:
            continue
        texto = texto_whatsapp(pendientes, alerts_engine.APP_URL)
        enviar_lote_con_demora([tel], texto)
        for c in pendientes:
            alerts_engine.registrar_alerta_en_log(conn, user_id, marcas[_clave(c)], TIPO_ALERTA, texto, channel="whatsapp")
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
