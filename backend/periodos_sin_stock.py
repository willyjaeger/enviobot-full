"""Periodos sin stock de un producto: junta los dias seguidos en los que estuvo en cero en tramos (desde, hasta, cuantos dias).

Los dias vienen de la foto diaria del stock (stock_daily). Solo hay dato de los dias que la app registro.
"""
from datetime import date, datetime, timedelta


def agrupar(dias, hoy=None):
    """dias: fechas (date, datetime o AAAA-MM-DD). Devuelve [{"desde": iso, "hasta": iso, "dias": n, "en_curso": bool}] en orden."""
    limpios = set()
    for d in dias or []:
        if isinstance(d, datetime):
            d = d.date()
        elif isinstance(d, str):
            d = date.fromisoformat(d[:10])
        limpios.add(d)
    hoy_iso = hoy.isoformat() if isinstance(hoy, date) else None
    salida = []
    for d in sorted(limpios):
        if salida and salida[-1]["_fin"] + timedelta(days=1) == d:
            salida[-1]["_fin"] = d
            salida[-1]["dias"] += 1
        else:
            salida.append({"_ini": d, "_fin": d, "dias": 1})
    return [{"desde": t["_ini"].isoformat(), "hasta": t["_fin"].isoformat(), "dias": t["dias"],
             "en_curso": hoy_iso is not None and t["_fin"].isoformat() == hoy_iso} for t in salida]
