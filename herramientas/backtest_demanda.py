"""Solo lectura. Prueba con datos reales qué método de ritmo de venta pronostica mejor.

Para cada producto y cada fecha de corte, calcula el ritmo con los datos anteriores a esa fecha y lo compara con lo que
se vendió de verdad en los H días siguientes (H = lo que lleva reponer). Mide:
  - error: suma de |pronostico - real| / suma de real (menos es mejor);
  - sesgo: pronostico total / real total - 1 (negativo = se queda corto = riesgo de quiebre);
  - cobertura: en qué % de los casos el pronostico alcanzó (pronostico >= real); es lo que importa para no quebrar;
  - exceso: cuánto sobra en promedio cuando alcanza (pronostico - real, como % del real).
Lee ventas_diarias (migracion 006). No escribe nada.
Uso en el servidor:  PYTHONPATH=/var/www/enviobot-full/backend python backtest_demanda.py <user_id> [H]
"""
import os
import sys
from datetime import timedelta

import pymysql
from dotenv import load_dotenv

import demanda
import ventas_historial

load_dotenv("/var/www/enviobot-full/backend/.env")
user_id = int(sys.argv[1])
H = int(sys.argv[2]) if len(sys.argv) > 2 else 14
MIN_HISTORIA = 35      # días de datos antes de la primera fecha de corte
MIN_VENTA_DIA = 1.0    # productos que venden menos que esto por día son ruido para este análisis

c = pymysql.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
                    database=os.getenv("DB_NAME"), cursorclass=pymysql.cursors.DictCursor)
cur = c.cursor()
cur.execute("SELECT item_id, variation_id, day, unidades FROM ventas_diarias WHERE user_id=%s", (user_id,))
series = {}
for f in cur.fetchall():
    series.setdefault((f["item_id"], f["variation_id"] or ""), {})[f["day"]] = int(f["unidades"])
hoy = ventas_historial.hoy_ba()


def media(vals):
    return sum(vals) / len(vals) if vals else 0.0


def ventana(serie, corte, n):
    """Unidades por día de los n días anteriores al corte (sin incluirlo)."""
    return media([serie.get(corte - timedelta(days=k), 0) for k in range(1, n + 1)])


def metodos(serie, corte):
    r7, r14, r28 = ventana(serie, corte, 7), ventana(serie, corte, 14), ventana(serie, corte, 28)
    v15, v30 = ventana(serie, corte, 15), ventana(serie, corte, 30)
    est = demanda.estimar({d: u for d, u in serie.items() if d < corte}, corte)
    out = {
        "A viejo (0,5/0,35/0,15)": 0.5 * r7 + 0.35 * v15 + 0.15 * v30,
        "B promedio 28d": r28,
        "C promedio 14d": r14,
        "D promedio 7d": r7,
        "E limpio actual": est["base"],
        "F mezcla 0,5/0,3/0,2": 0.5 * r7 + 0.3 * r14 + 0.2 * r28,
        "G maximo(7d,14d,28d)": max(r7, r14, r28),
        "H mediana de 28d": demanda._mediana([serie.get(corte - timedelta(days=k), 0) for k in range(1, 29)]),
    }
    # Con margen de seguridad: el promedio de 28 días multiplicado, o más un desvío de las ventas diarias.
    diarias = [serie.get(corte - timedelta(days=k), 0) for k in range(1, 29)]
    media28 = media(diarias)
    desvio = (sum((x - media28) ** 2 for x in diarias) / len(diarias)) ** 0.5
    for m in (1.25, 1.5, 1.75, 2.0):
        out[f"B x {m}"] = r28 * m
    for k in (0.5, 1.0):
        out[f"B + {k} desvio diario"] = r28 + k * desvio
    return out


acum = {}
casos = 0
for clave, serie in series.items():
    dias = sorted(serie)
    if not dias:
        continue
    primero = dias[0]
    corte = primero + timedelta(days=MIN_HISTORIA)
    while corte + timedelta(days=H) <= hoy:
        real = media([serie.get(corte + timedelta(days=k), 0) for k in range(H)])
        previo = ventana(serie, corte, 28)
        if previo >= MIN_VENTA_DIA or real >= MIN_VENTA_DIA:
            casos += 1
            for nombre, f in metodos(serie, corte).items():
                a = acum.setdefault(nombre, {"err": 0.0, "real": 0.0, "fc": 0.0, "ok": 0, "n": 0, "exc": 0.0, "okreal": 0.0})
                a["err"] += abs(f - real)
                a["real"] += real
                a["fc"] += f
                a["n"] += 1
                if f >= real:
                    a["ok"] += 1
                    a["exc"] += f - real
                    a["okreal"] += real
        corte += timedelta(days=3)

print(f"Horizonte {H} días. {len(series)} publicaciones, {casos} pronósticos comparados.\n")
print(f"{'Método':<26}{'Error':>8}{'Sesgo':>9}{'Alcanzó':>9}{'Sobra si alcanza':>18}")
for nombre, a in sorted(acum.items(), key=lambda kv: kv[1]["err"] / max(kv[1]["real"], 1e-9)):
    print(f"{nombre:<26}{a['err'] / a['real']:>8.0%}{a['fc'] / a['real'] - 1:>+9.0%}{a['ok'] / a['n']:>9.0%}"
          f"{(a['exc'] / a['okreal'] if a['okreal'] else 0):>18.0%}")
