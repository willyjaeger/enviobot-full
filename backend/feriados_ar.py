"""Feriados nacionales de Argentina (incluye los puentes turísticos no laborables).

Fuente: https://api.argentinadatos.com/v1/feriados/<año> (consultada el 2026-10-17).
Los WhatsApp NO salen en estas fechas (ver horario_whatsapp.py). Los mails sí.

HAY QUE CARGAR EL AÑO SIGUIENTE cada diciembre: si un año no está acá, no se frena nada ese año
y queda un aviso en el log. No incluye feriados provinciales ni días no laborables optativos.
"""
import logging

logger = logging.getLogger("feriados_ar")

FERIADOS = {
    "2026-01-01": "Año nuevo",
    "2026-02-16": "Carnaval",
    "2026-02-17": "Carnaval",
    "2026-03-23": "Puente turístico no laborable",
    "2026-03-24": "Día Nacional de la Memoria por la Verdad y la Justicia",
    "2026-04-02": "Día del Veterano y de los Caídos en la Guerra de Malvinas",
    "2026-04-03": "Viernes Santo",
    "2026-05-01": "Día del Trabajador",
    "2026-05-25": "Día de la Revolución de Mayo",
    "2026-06-15": "Paso a la Inmortalidad del General Martín Güemes (17/6)",
    "2026-06-20": "Paso a la Inmortalidad del General Manuel Belgrano",
    "2026-07-09": "Día de la Independencia",
    "2026-07-10": "Puente turístico no laborable",
    "2026-08-17": "Paso a la Inmortalidad del Gral. José de San Martín",
    "2026-10-12": "Día del Respeto a la Diversidad Cultural",
    "2026-11-09": "Visita del papa León XIV",
    "2026-11-23": "Día de la Soberanía Nacional (20/11)",
    "2026-12-07": "Puente turístico no laborable",
    "2026-12-08": "Día de la Inmaculada Concepción de María",
    "2026-12-25": "Navidad",
    "2027-01-01": "Año nuevo",
    "2027-02-08": "Carnaval",
    "2027-02-09": "Carnaval",
    "2027-03-24": "Día Nacional de la Memoria por la Verdad y la Justicia",
    "2027-03-26": "Viernes Santo",
    "2027-04-02": "Día del Veterano y de los Caídos en la Guerra de Malvinas",
    "2027-05-01": "Día del Trabajador",
    "2027-05-25": "Día de la Revolución de Mayo",
    "2027-06-17": "Paso a la Inmortalidad del General Martín Güemes",
    "2027-06-20": "Paso a la Inmortalidad del General Manuel Belgrano",
    "2027-07-09": "Día de la Independencia",
    "2027-08-17": "Paso a la Inmortalidad del Gral. José de San Martín",
    "2027-10-12": "Día del Respeto a la Diversidad Cultural",
    "2027-11-20": "Día de la Soberanía Nacional",
    "2027-12-08": "Día de la Inmaculada Concepción de María",
    "2027-12-25": "Navidad",
}

ANIOS_CARGADOS = sorted({int(f[:4]) for f in FERIADOS})
_avisados = set()


def es_feriado(dia):
    """dia: datetime.date. True si es feriado nacional."""
    if dia.year not in ANIOS_CARGADOS and dia.year not in _avisados:
        _avisados.add(dia.year)
        logger.warning(f"[Feriados] No hay feriados cargados para {dia.year}: cargarlos en backend/feriados_ar.py")
    return dia.isoformat() in FERIADOS


def nombre_feriado(dia):
    return FERIADOS.get(dia.isoformat())
