"""Qué avisos recibe cada destinatario de la agenda de envíos.

Cada destinatario (alert_recipients) puede elegir de qué tipos de aviso se entera. La columna `avisos`
guarda las claves separadas por coma:
  - NULL  -> recibe TODOS (es lo que pasaba antes de este menú, y lo que queda hasta que alguien lo cambie)
  - ''    -> no recibe ninguno
  - 'a,b' -> solo esos
Sin la columna (migración 003 sin aplicar) todos reciben todo, como siempre.

Las claves son las mismas que usa pausa_avisos.py. Para agregar un aviso nuevo: sumarlo acá y que quien
lo envíe pregunte avisos_tipos.recibe(fila, clave) a cada destinatario.
"""

TIPOS = (
    {"clave": "alerta_stock", "corto": "Stock", "titulo": "Alertas de stock",
     "descripcion": "Stock crítico, conviene preparar colecta, colecta del día y resumen diario."},
    {"clave": "colecta_limite", "corto": "Cierre de colecta", "titulo": "Cierre del cambio de la colecta",
     "descripcion": "Una hora antes de que ya no se pueda modificar la colecta."},
    {"clave": "colecta_mail", "corto": "Mails de ML", "titulo": "Mails de Mercado Libre sobre la colecta",
     "descripcion": "Código de autorización, horario de retiro y avisos que manda Mercado Libre por mail."},
    {"clave": "cambio_tasa_venta", "corto": "Ritmo de venta", "titulo": "Cambios en el ritmo de venta",
     "descripcion": "Cuando un producto empieza a venderse bastante más o menos que antes."},
)
CLAVES = tuple(t["clave"] for t in TIPOS)


def parsear(texto):
    """None -> None (todos). '' -> conjunto vacío (ninguno). 'a,b' -> {'a','b'} (se ignoran claves desconocidas)."""
    if texto is None:
        return None
    return frozenset(x.strip() for x in str(texto).split(",") if x.strip() in CLAVES)


def recibe(fila, tipo):
    """¿Este destinatario (fila de alert_recipients) quiere este tipo de aviso?"""
    elegidos = parsear((fila or {}).get("avisos"))
    return True if elegidos is None else tipo in elegidos


def a_texto(claves):
    """Lista de claves -> texto para guardar, en el orden del catálogo. Devuelve (texto, error)."""
    claves = list(claves or [])
    desconocidas = [c for c in claves if c not in CLAVES]
    if desconocidas:
        return None, "Hay avisos que no existen."
    return ",".join(c for c in CLAVES if c in claves), None


def resumen(texto):
    """Para mostrar: 'Todos', 'Ninguno' o los nombres cortos."""
    elegidos = parsear(texto)
    if elegidos is None or len(elegidos) == len(CLAVES):
        return "Todos"
    if not elegidos:
        return "Ninguno"
    return ", ".join(t["corto"] for t in TIPOS if t["clave"] in elegidos)
