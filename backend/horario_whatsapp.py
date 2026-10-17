"""Horario en el que se pueden mandar WhatsApp, hora de Buenos Aires.

Regla de Guillermo (2026-10-16): los WhatsApp nunca salen fuera de horario. Si una alerta toca
fuera de horario, NO se manda ni se anota como enviada: la próxima corrida dentro del horario la
manda. Los mails no tienen esta restricción. Los feriados nacionales (feriados_ar.py) tampoco: ese día no sale ningún WhatsApp.

Quién decide el horario (2026-10-17):
  1. Por defecto, lunes a viernes de 8:30 a 18:00.
  2. El dueño de la cuenta puede cambiar ese horario (columnas wa_days / wa_from / wa_to de user_settings).
  3. Cada destinatario hereda el del dueño, salvo que tenga el suyo (mismas columnas en alert_recipients).
     Una columna vacía (NULL) significa "usar el del dueño".

Formato guardado: días como "0,1,2,3,4" (lunes=0 ... domingo=6) y horas como "08:30".
"""
from datetime import datetime

import proyeccion
from feriados_ar import es_feriado

DESDE = (8, 30)
HASTA = (18, 0)
DIAS_DEFECTO = (0, 1, 2, 3, 4)


def horario_defecto():
    return {"dias": DIAS_DEFECTO, "desde": DESDE, "hasta": HASTA}


def parsear_dias(texto):
    """'0,1,2' -> (0, 1, 2). None si está vacío o no es válido."""
    if texto is None or str(texto).strip() == "":
        return None
    try:
        dias = sorted({int(x) for x in str(texto).split(",") if x.strip() != ""})
    except ValueError:
        return None
    if not dias or any(d < 0 or d > 6 for d in dias):
        return None
    return tuple(dias)


def parsear_hora(texto):
    """'08:30' o '8:30' -> (8, 30). None si no es válida."""
    if texto is None:
        return None
    partes = str(texto).strip().split(":")
    if len(partes) < 2:
        return None
    try:
        h, m = int(partes[0]), int(partes[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


def horario_de(fila, base=None):
    """Horario efectivo de una fila (user_settings o alert_recipients) con campos wa_days/wa_from/wa_to.
    Lo que la fila no define lo toma de `base` (el del dueño); si tampoco hay base, del defecto."""
    base = base or horario_defecto()
    if not fila:
        return base
    return {
        "dias": parsear_dias(fila.get("wa_days")) or base["dias"],
        "desde": parsear_hora(fila.get("wa_from")) or base["desde"],
        "hasta": parsear_hora(fila.get("wa_to")) or base["hasta"],
    }


def en_horario(horario, ahora=None):
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    if es_feriado(ahora.date()):
        return False  # feriados nacionales: nunca, aunque el horario propio incluya ese día
    if ahora.weekday() not in horario["dias"]:
        return False
    return horario["desde"] <= (ahora.hour, ahora.minute) <= horario["hasta"]


def whatsapp_permitido(ahora=None, horario=None):
    return en_horario(horario or horario_defecto(), ahora)


def a_texto(horario):
    """Para guardar/mostrar: {'dias': '0,1,2,3,4', 'desde': '08:30', 'hasta': '18:00'}."""
    return {
        "dias": ",".join(str(d) for d in horario["dias"]),
        "desde": "%02d:%02d" % horario["desde"],
        "hasta": "%02d:%02d" % horario["hasta"],
    }


def validar(dias, desde, hasta):
    """Devuelve (horario, None) si es válido o (None, mensaje de error)."""
    d = parsear_dias(dias if not isinstance(dias, (list, tuple)) else ",".join(str(x) for x in dias))
    if not d:
        return None, "Elegí al menos un día."
    a, b = parsear_hora(desde), parsear_hora(hasta)
    if not a or not b:
        return None, "Las horas no son válidas (formato 08:30)."
    if a >= b:
        return None, "La hora de inicio tiene que ser anterior a la de fin."
    return {"dias": d, "desde": a, "hasta": b}, None
