"""Horario en el que se pueden mandar WhatsApp: lunes a viernes, de 8:30 a 18:00, hora de Buenos Aires.

Regla de Guillermo (2026-10-16): los WhatsApp nunca salen fuera de ese horario. Si una alerta
toca fuera de horario, NO se manda ni se anota como enviada: la próxima corrida dentro del
horario la manda. Los mails no tienen esta restricción.
No contempla feriados.
"""
from datetime import datetime

import proyeccion

DESDE = (8, 30)
HASTA = (18, 0)


def whatsapp_permitido(ahora=None):
    ahora = ahora or datetime.now(proyeccion.HORA_BA)
    if ahora.weekday() >= 5:
        return False
    return DESDE <= (ahora.hour, ahora.minute) <= HASTA
