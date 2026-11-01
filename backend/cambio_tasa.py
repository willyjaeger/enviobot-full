#!/usr/bin/env python3
"""Aviso de que la venta de un producto bajó de forma sostenida y te puede sobrar stock.

Solo avisa si se cumplen las dos cosas:
  1. el ritmo de venta limpio de hoy (sin días sin stock, rebote ni picos; ver demanda.py) es 30 % o más
     menor que el de las buenas semanas recientes (la referencia con la que se planificó la compra);
  2. con ese ritmo, lo que hay en Full más lo que viene en camino alcanza para más del umbral de sobrestock
     (objetivo de cobertura x 1,5) y con el ritmo de referencia no pasaba: es el stock que quedó de más por la baja.
Una suba de ventas no se avisa (las alertas de stock de siempre cubren el riesgo de quedarse sin stock).
Si hay una colecta en preparación, el aviso lo dice: todavía se puede achicar.
Avisa:
  - en el panel (ventana "Avisos"), siempre, apenas se detecta;
  - por WhatsApp, solo dentro del horario de cada destinatario: si se detecta fuera de horario no se
    manda ni se anota como enviado. Cuando llega el horario se VUELVE A CONTROLAR antes de mandar:
    si la situación sigue (o cambió) se manda con los números de ese momento; si volvió a lo normal no
    se manda nada y en el panel queda anotado que se revirtió.

Usa las ventas por día (ventas_diarias, migración 006), full_items, stock_daily y alert_logs.
El historial se guarda en alert_logs con alert_type 'cambio_tasa' (channel 'panel' o 'whatsapp').
Un aviso del panel tiene clave '<producto>:<sentido>'; su reversión, '<producto>:rev-<sentido>'.

Lo llama el motor de alertas después de cada sincronización (cada 4 horas) y el cron de las 8:30.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta

import alerts_engine
import demanda
import esquema
import proyeccion
import ventas_historial
from horario_whatsapp import whatsapp_permitido
from whatsapp_service import enviar_lote_con_demora, normalizar_telefono, obtener_configuracion_whatsapp

logger = logging.getLogger("cambio_tasa")

TIPO_ALERTA = "cambio_tasa"
TIPO_REGISTRO = "cambio_tasa_wa"  # lo que se habría mandado por WhatsApp (modo prueba) y cuándo se frenó
TOPE_DIA = 1              # a cada persona, como mucho un WhatsApp de este tipo por día...
TOPE_SEMANA = 3           # ...y en tres días distintos por semana; si hay más, esperan al día siguiente
REGISTRO_DIAS = 30        # cuánto se guarda el registro del modo prueba
UMBRAL_BAJA = 0.70        # hoy vende 70 % o menos de la referencia (baja de 30 % o más)
MIN_EXCESO_UNIDADES = 20  # menos unidades de más que esto no vale un aviso
MIN_EXCESO_DIAS = 10      # ...ni un sobrante de menos de 10 días de venta
RESUELTO = 0.80           # el exceso se da por resuelto cuando la cobertura baja de 80 % del umbral (evita ir y venir)
REPETIR_DIAS = 60         # cuánto tiempo se sigue un aviso: mientras siga abierto no se repite ni en el panel ni por WhatsApp
MAX_PRODUCTOS_WA = 8
VISIBLE_DIAS = 7          # la ventana de Avisos muestra la última semana; lo cerrado más viejo se borra
ESPERA_MAX_DIAS = 5       # un aviso que no pudo salir en 5 días (fin de semana largo incluido) ya es viejo


def evaluar_baja(est, stock, entrante, objetivo, factor=None):
    """Decide si hay que avisar de una baja de ventas que deja stock de más.

    est: resultado de demanda.estimar. Devuelve (aviso, medible): `aviso` es None o un dict con antes (referencia),
    ahora, pct, dias_stock (cobertura con el ritmo de hoy) y exceso (unidades por encima del objetivo);
    `medible` es False si no hay datos para decidir o si la situación está justo en el límite (no se
    da por revertido un aviso abierto en la zona gris)."""
    ref, ahora = est.get("referencia"), est.get("base") or 0.0
    total = (stock or 0) + (entrante or 0)
    if (stock or 0) <= 0 or not ref or est.get("confianza") == "baja" or est.get("ultimos7") is None:
        return None, False
    ahora = max(ahora, 0.01)
    umbral = proyeccion.umbral_sobrestock(objetivo, factor)
    dias_ahora = min(total / ahora, 999.0)
    dias_antes = total / ref
    exceso = total - ahora * objetivo
    baja = ahora <= ref * UMBRAL_BAJA
    if (baja and dias_ahora > umbral and dias_antes <= umbral
            and exceso >= MIN_EXCESO_UNIDADES and exceso / ahora >= MIN_EXCESO_DIAS):
        return {"sentido": "baja", "antes": round(ref, 1), "ahora": round(ahora, 1),
                "pct": int(round((ahora / ref - 1) * 100)), "dias_stock": round(dias_ahora, 1),
                "exceso": int(exceso)}, True
    zona_gris = baja and dias_ahora > umbral * RESUELTO and dias_antes <= umbral
    return None, not zona_gris


def _clave_producto(f):
    return (f.get("inventory_id") or "").strip() or (f.get("sku") or "").strip().upper() \
        or f"{f['item_id']}_{f.get('variation_id') or ''}"


def _gk(clave_producto):
    return hashlib.sha1(clave_producto.encode("utf-8")).hexdigest()[:12]


def detectar(conn, user_id, hoy=None):
    """(cambios, medibles). `cambios`: bajas de venta que dejan stock de más. `medibles`: {producto: ritmo actual}
    de los productos que se pudieron medir (sirve para saber si uno ya volvió a lo normal).
    Agrupa por producto físico (inventory_id o SKU) porque la misma mercadería puede estar en varias
    publicaciones y el stock es uno solo."""
    hoy = hoy or ventas_historial.hoy_ba()
    with conn.cursor() as cur:
        if not esquema.tiene_tabla(cur, "ventas_diarias"):
            return [], {}
        cur.execute("""
            SELECT i.item_id, i.variation_id, i.sku, i.inventory_id, i.title, i.current_stock_full,
                   i.not_available_stock_full
            FROM full_items i
            WHERE i.user_id = %s AND i.is_monitored = 1
        """, (user_id,))
        filas = cur.fetchall()
        # Objetivo de cobertura y umbral de sobrestock (mismos valores que usa el panel)
        cur.execute("SELECT * FROM user_settings WHERE user_id=%s", (user_id,))
        ajustes = cur.fetchone() or {}
        cur.execute("SELECT target_stock_days FROM warehouses WHERE user_id=%s AND is_active=1 ORDER BY id ASC LIMIT 1", (user_id,))
        wh = cur.fetchone()
        objetivo = wh["target_stock_days"] if wh and wh.get("target_stock_days") is not None else (ajustes.get("target_coverage_days") or 30)
        factor = ajustes.get("sobrestock_factor")
        # Lo que viene en camino: colectas en preparación y despachadas
        cur.execute("""
            SELECT s.status, isi.item_id, isi.inventory_id, isi.sku, SUM(isi.units_to_send) AS unidades
            FROM inbound_shipment_items isi JOIN inbound_shipments s ON s.id = isi.shipment_id
            WHERE s.user_id = %s AND s.status IN ('scheduled', 'in_transit')
            GROUP BY s.status, isi.item_id, isi.inventory_id, isi.sku
        """, (user_id,))
        envios = cur.fetchall()
        ventas = {}
        cur.execute("SELECT item_id, variation_id, day, unidades FROM ventas_diarias WHERE user_id=%s AND day >= %s",
                    (user_id, hoy - timedelta(days=130)))
        for r in cur.fetchall():
            ventas.setdefault((r["item_id"], r["variation_id"] or ""), {})[r["day"]] = int(r["unidades"])
        quiebres = {}
        if esquema.tiene_tabla(cur, "stock_daily"):
            cur.execute("SELECT item_id, variation_id, day FROM stock_daily WHERE user_id=%s AND stock_max=0 AND day >= %s",
                        (user_id, hoy - timedelta(days=130)))
            for r in cur.fetchall():
                quiebres.setdefault((r["item_id"], r["variation_id"] or ""), set()).add(r["day"])

    grupos = {}
    for f in filas:
        clave_v = (f["item_id"], f.get("variation_id") or "")
        g = grupos.setdefault(_clave_producto(f), {"serie": {}, "sin": set(), "stock": 0, "principal": f, "ventas": -1})
        total_pub = sum(ventas.get(clave_v, {}).values())
        for dia, u in ventas.get(clave_v, {}).items():
            g["serie"][dia] = g["serie"].get(dia, 0) + u
        g["sin"] |= quiebres.get(clave_v, set())
        if total_pub > g["ventas"]:  # el título y la publicación que se muestran son los del que más vende
            g["ventas"], g["principal"] = total_pub, f
        g["stock"] = max(g["stock"], int(f.get("current_stock_full") or 0))  # mismo inventario, mismo stock

    # Lo que hay en camino de cada producto, por inventory_id, SKU o publicación (como en el panel)
    prep, transito_u = {}, {}
    for e in envios:
        u = int(e.get("unidades") or 0)
        destino = prep if e["status"] == "scheduled" else transito_u
        for k in ((e.get("inventory_id") or "").strip(), (e.get("sku") or "").strip().upper(), (e.get("item_id") or "").strip()):
            if k:
                destino[k] = destino.get(k, 0) + u

    cambios, medibles = [], {}
    for clave_prod, g in grupos.items():
        if not g["serie"]:
            continue
        est = demanda.estimar(g["serie"], hoy, g["sin"])
        p = g["principal"]
        claves = ((p.get("inventory_id") or "").strip(), (p.get("sku") or "").strip().upper(), (p.get("item_id") or "").strip())
        en_prep = next((prep[k] for k in claves if k and prep.get(k)), 0)
        en_transito = next((transito_u[k] for k in claves if k and transito_u.get(k)), 0)
        en_muelle = int(p.get("not_available_stock_full") or 0)
        entrante = en_muelle + en_prep + (max(0, en_transito - en_muelle) if en_transito else 0)
        ev, medible = evaluar_baja(est, g["stock"], entrante, objetivo, factor)
        if not medible:
            continue
        gk = _gk(clave_prod)
        medibles[gk] = round(est["base"], 1)
        if not ev:
            continue
        ev.update({
            "causa": "exceso", "dias_ingreso": 0, "entrante": entrante, "objetivo": int(objetivo), "en_prep": en_prep,
            "gk": gk, "item_id": p["item_id"], "variation_id": p.get("variation_id") or "",
            "sku": (p.get("sku") or "").strip(), "titulo": (p.get("title") or "").strip(), "stock": g["stock"],
        })
        cambios.append(ev)
    # primero lo que más sobra
    cambios.sort(key=lambda c: -c["exceso"])
    return cambios, medibles


def whatsapp_real_activo():
    """El WhatsApp de este aviso está en modo prueba (solo se anota lo que se habría mandado) hasta que
    se ponga ENVIOBOT_CAMBIO_TASA_WA=activo en el .env del servidor y se reinicie (decisión de Guillermo, 2026-11-01)."""
    return os.getenv("ENVIOBOT_CAMBIO_TASA_WA", "prueba").strip().lower() == "activo"


def reglas():
    """Cuándo se manda y cuándo se frena, en palabras, para mostrarlo en la ventana de Avisos."""
    return [
        "Solo se avisa una baja sostenida de la venta (30 % o más contra las buenas semanas recientes) que deja stock "
        f"de más: sobran al menos {MIN_EXCESO_UNIDADES} unidades y {MIN_EXCESO_DIAS} días de venta por encima del umbral de sobrestock.",
        "Un aviso por producto y por situación: mientras siga abierto no se repite, ni por el panel ni por WhatsApp "
        f"(se sigue hasta {REPETIR_DIAS} días). Nunca un mensaje diario por lo mismo.",
        f"Como mucho {TOPE_DIA} WhatsApp por día y {TOPE_SEMANA} por semana a cada persona; si hay más, esperan al día siguiente.",
        "Solo dentro del horario permitido de cada destinatario (lunes a viernes, sin feriados).",
        "Antes de mandar se vuelve a controlar: si la situación se revirtió no se manda nada y queda anotado.",
    ]


def _registro_prueba(c, tel_n):
    """Lo que se anota cuando el WhatsApp está en modo prueba (alert_logs.message es corto)."""
    return json.dumps({"t": c["titulo"][:60], "a": c["antes"], "n": c["ahora"], "d": c["dias_stock"],
                       "x": c.get("exceso", 0), "w": tel_n[-4:], "p": c.get("en_prep", 0)},
                      ensure_ascii=False, separators=(",", ":"))


def texto_registro(registro, item_id):
    """Una línea del registro de modo prueba a partir de lo guardado. None si no sirve."""
    try:
        d = json.loads(registro)
        if item_id.startswith("wacap:"):
            return {"tipo": "frenado", "producto": "",
                    "detalle": f"No se mandaría a ...{d['w']}: ya hubo {d['m']}. Esperan al día siguiente ({d['n']} aviso(s) pendientes)."}
        return {"tipo": "habria", "producto": d["t"],
                "detalle": (f"Se habría mandado a ...{d['w']}: vende {_ritmo(d['n'])} por día (antes {_ritmo(d['a'])}); "
                            f"con lo que hay alcanza para {int(round(d['d']))} días, sobran unas {d['x']} unidades."
                            + (f" Había una colecta en preparación de {d['p']} unidades para achicar." if d.get("p") else ""))}
    except (ValueError, KeyError, TypeError):
        return None


def registro_prueba_visible(conn, user_id):
    """Lo que el WhatsApp en modo prueba habría mandado (o frenado), lo más nuevo primero."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT item_id, message, sent_at FROM alert_logs
            WHERE user_id=%s AND alert_type=%s AND sent_at >= %s ORDER BY id DESC
        """, (user_id, TIPO_REGISTRO, datetime.utcnow() - timedelta(days=REGISTRO_DIAS)))
        return cur.fetchall()


def _tope_alcanzado(conn, user_id, tel_n, hoy=None):
    """'dia' o 'semana' si a esa persona ya le llegó (o le habría llegado) lo máximo; None si puede recibir."""
    hoy = hoy or datetime.utcnow().date()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DATE(sent_at) AS d FROM alert_logs
            WHERE user_id=%s AND alert_type IN (%s, %s) AND (item_id LIKE %s OR item_id LIKE %s) AND sent_at >= %s
            GROUP BY DATE(sent_at)
        """, (user_id, TIPO_ALERTA, TIPO_REGISTRO, f"wa:{tel_n}:%", f"wasim:{tel_n}:%", datetime.utcnow() - timedelta(days=7)))
        dias = {f["d"] for f in cur.fetchall()}
    if sum(1 for d in dias if d == hoy) >= TOPE_DIA:
        return "dia"
    if len(dias) >= TOPE_SEMANA:
        return "semana"
    return None


def _clave(c):
    return f"{c['gk']}:{c['sentido']}"


def _clave_rev(gk, sentido):
    return f"{gk}:rev-{sentido}"


def _etiqueta(c):
    sku = f", SKU {c['sku']}" if c["sku"] else ""
    return f"{c['titulo'][:60]} (publicación {c['item_id']}{sku})"


def _ritmo(x):
    return f"{x:.1f}".replace(".", ",")


def _frase_exceso(dias_stock, total, objetivo, en_prep):
    frase = (f"Con ese ritmo, lo que hay en Full y lo que viene en camino ({int(total)} unidades) alcanza para "
             f"{int(round(dias_stock))} días y tu objetivo es {int(objetivo)}.")
    if en_prep:
        return frase + f" Todavía podés achicar la colecta en preparación ({int(en_prep)} unidades)."
    return frase + " Conviene no mandar más por ahora y revisar precio, publicidad y competencia para recuperar la venta."


def _frase_riesgo(causa, dias_stock, dias_ingreso, entrante):
    ds, di = _ritmo(dias_stock), int(dias_ingreso)
    if causa == "colecta_corta":
        return (f"Las {entrante} unidades que vienen en camino te alcanzan para {ds} días desde que entren, "
                f"menos de lo que lleva reponer.")
    if entrante > 0:
        return f"Con ese ritmo el stock en Full dura {ds} días y la colecta en camino ({entrante} unidades) llega en {di}: te quedás sin stock antes."
    return f"Con ese ritmo el stock en Full dura {ds} días y reponer lleva unos {di}: te quedás sin stock antes."


def _frase(c):
    """La explicación de un aviso, a partir de los datos de la detección o de lo guardado."""
    if c["causa"] == "exceso":
        return _frase_exceso(c["dias_stock"], (c.get("stock") or 0) + (c.get("entrante") or 0), c.get("objetivo", 30), c.get("en_prep", 0))
    return _frase_riesgo(c["causa"], c["dias_stock"], c["dias_ingreso"], c["entrante"])


def texto_whatsapp(cambios, app_url=""):
    n = len(cambios)
    lineas = [f"EnvioBot Full: bajó la venta de {n} producto{'s' if n != 1 else ''} y te puede quedar stock de más."]
    for c in cambios[:MAX_PRODUCTOS_WA]:
        lineas.append(f"- {_etiqueta(c)}: ahora vende {_ritmo(c['ahora'])} por día (antes {_ritmo(c['antes'])}). " + _frase(c))
    if n > MAX_PRODUCTOS_WA:
        lineas.append(f"- y {n - MAX_PRODUCTOS_WA} más, en el panel.")
    lineas.append("Te recomendamos verificar qué sucede (precio, competencia, publicación) y ajustar la próxima colecta"
                  + (f": {app_url}" if app_url else "."))
    return "\n".join(lineas)


def _registro_panel(c, revertido=False):
    """Lo que se guarda para la ventana de Avisos (alert_logs.message es corto, por eso va compacto)."""
    d = {"s": c["sentido"], "a": c["antes"], "n": c["ahora"], "p": c["pct"], "sku": c["sku"],
         "st": c["stock"], "t": c["titulo"][:70], "i": c["item_id"],
         "c": c.get("causa", ""), "ds": c.get("dias_stock", 0), "di": c.get("dias_ingreso", 0), "u": c.get("entrante", 0),
         "o": c.get("objetivo", 0), "pr": c.get("en_prep", 0)}
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
            base["detalle"] = ("La situación se revirtió: con el ritmo actual ya no te sobra stock. No hace falta hacer nada."
                               if d["s"] == "baja" else
                               "La situación se revirtió: ya no hay riesgo de quedarte sin stock antes de reponer. No hace falta hacer nada.")
        elif d.get("c"):
            pct = f" ({d['p']:+d} %)" if d.get("p") is not None else ""
            c = _desde_registro(f"x:{d['s']}", registro)
            base["detalle"] = f"Ahora vende {_ritmo(d['n'])} por día (antes {_ritmo(d['a'])}{pct}). " + _frase(c)
        else:  # avisos del primer formato (cambio de ritmo sin evaluar riesgo)
            verbo = "bajó" if d["s"] == "baja" else "subió"
            base["detalle"] = f"El ritmo de venta {verbo} de {_ritmo(d['a'])} a {_ritmo(d['n'])} unidades por día."
        return base
    except (ValueError, KeyError, TypeError):
        return None


def _desde_registro(clave, registro):
    """Reconstruye el cambio a partir de lo guardado en el panel (clave 'producto:sentido')."""
    try:
        d = json.loads(registro)
        return {"sentido": d["s"], "antes": d["a"], "ahora": d["n"], "pct": d.get("p"), "item_id": d.get("i", ""),
                "variation_id": "", "gk": clave.split(":", 1)[0], "sku": d.get("sku", ""),
                "titulo": d.get("t", ""), "stock": d.get("st"), "causa": d.get("c", ""),
                "dias_stock": d.get("ds", 0), "dias_ingreso": d.get("di", 0), "entrante": d.get("u", 0),
                "objetivo": d.get("o", 0), "en_prep": d.get("pr", 0)}
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


def avisos_visibles(conn, user_id):
    """Lo que muestra la ventana de Avisos, lo más nuevo primero: los últimos VISIBLE_DIAS días, más los
    avisos que siguen abiertos aunque sean más viejos (son un problema que todavía existe)."""
    filas = _filas_panel(conn, user_id)
    abiertos = {f["id"] for f in _activos(filas).values()}
    limite = datetime.utcnow() - timedelta(days=VISIBLE_DIAS)
    return [f for f in reversed(filas) if f["id"] in abiertos or f["sent_at"] >= limite]


def limpiar(conn, user_id):
    """Borra los avisos viejos: más de VISIBLE_DIAS días y ya cerrados (revertidos o reemplazados).
    Los que siguen abiertos se conservan, porque con ellos se sabe que ya se avisó y no se repite.
    Los registros de WhatsApp se borran pasado el período de seguimiento."""
    filas = _filas_panel(conn, user_id)
    abiertos = {f["id"] for f in _activos(filas).values()}
    limite = datetime.utcnow() - timedelta(days=VISIBLE_DIAS)
    viejos = [f["id"] for f in filas if f["id"] not in abiertos and f["sent_at"] < limite]
    with conn.cursor() as cur:
        if viejos:
            cur.execute("DELETE FROM alert_logs WHERE user_id=%s AND id IN (" + ",".join(["%s"] * len(viejos)) + ")",
                        [user_id] + viejos)
        cur.execute("DELETE FROM alert_logs WHERE user_id=%s AND alert_type=%s AND sent_at < %s",
                    (user_id, TIPO_ALERTA, datetime.utcnow() - timedelta(days=REPETIR_DIAS + 1)))
        cur.execute("DELETE FROM alert_logs WHERE user_id=%s AND alert_type=%s AND sent_at < %s",
                    (user_id, TIPO_REGISTRO, datetime.utcnow() - timedelta(days=REGISTRO_DIAS)))
    return len(viejos)


def procesar_usuario(conn, user_id, ahora=None):
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    res = {"user_id": user_id, "detectados": 0, "avisos_panel": 0, "revertidos": 0, "mensajes_whatsapp": 0}
    try:
        limpiar(conn, user_id)
    except Exception as e:  # limpiar es secundario: no debe frenar los avisos
        logger.warning(f"[Cambio de ritmo] user_id={user_id}: no se pudieron borrar avisos viejos: {e}")
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
    real = whatsapp_real_activo()
    # En modo prueba no se manda nada: se anota en alert_logs (tipo TIPO_REGISTRO) lo que se habría mandado.
    tipo_marca, canal, prefijo = (TIPO_ALERTA, "whatsapp", "wa") if real else (TIPO_REGISTRO, "panel", "wasim")
    for tel, horario in _destinatarios(conn, user_id, settings, "cambio_tasa_venta").items():
        if not whatsapp_permitido(ahora, horario):
            continue
        tel_n = normalizar_telefono(tel)
        marcas = {_clave(c): f"{prefijo}:{tel_n}:{_hash_corto(_clave(c) + ':' + str(fila['id']))}" for c, fila in vigentes}
        pendientes = [c for c, _ in vigentes if not alerts_engine.ya_se_envio_alerta_hoy(
            conn, user_id, tipo_marca, marcas[_clave(c)], horas_cooldown=horas, channel=canal)]
        if not pendientes:
            continue
        tope = _tope_alcanzado(conn, user_id, tel_n)
        if tope:
            marca_tope = f"wacap:{tel_n}:{ahora.strftime('%y%m%d')}"
            if not alerts_engine.ya_se_envio_alerta_hoy(conn, user_id, TIPO_REGISTRO, marca_tope, horas_cooldown=20, channel="panel"):
                motivo = "un aviso hoy" if tope == "dia" else f"{TOPE_SEMANA} avisos esta semana"
                alerts_engine.registrar_alerta_en_log(conn, user_id, marca_tope, TIPO_REGISTRO,
                                                      json.dumps({"w": tel_n[-4:], "m": motivo, "n": len(pendientes)}, separators=(",", ":")),
                                                      channel="panel")
            continue
        if real:
            texto = texto_whatsapp(pendientes, alerts_engine.APP_URL)
            enviar_lote_con_demora([tel], texto)
            for c in pendientes:
                alerts_engine.registrar_alerta_en_log(conn, user_id, marcas[_clave(c)], tipo_marca, texto, channel=canal)
            logger.info(f"[Cambio de ritmo] user_id={user_id}: aviso de {len(pendientes)} producto(s) enviado")
        else:
            for c in pendientes:
                alerts_engine.registrar_alerta_en_log(conn, user_id, marcas[_clave(c)], tipo_marca, _registro_prueba(c, tel_n), channel=canal)
            logger.info(f"[Cambio de ritmo] user_id={user_id}: modo prueba, se habrían mandado {len(pendientes)} producto(s)")
        res["mensajes_whatsapp"] += 1
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
