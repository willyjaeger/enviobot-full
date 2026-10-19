"""Corre EN EL SERVIDOR (se manda por ssh). Solo mira: no borra, no marca, no manda WhatsApp.
Muestra los ultimos mails de la casilla de colectas y que haria correo_colectas.py con cada uno.
"""
import email
import email.policy
import imaplib
import sys

sys.path.insert(0, "/var/www/enviobot-full/backend")
import correo_colectas as c  # noqa: E402

cfg = c.leer_configuracion()
if not cfg:
    print("Falta configuracion en el .env")
    raise SystemExit
m = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
m.login(cfg["user"], cfg["password"])
m.select("INBOX", readonly=True)
_, d = m.search(None, "ALL")
ids = d[0].split()
print(f"Mails en la casilla: {len(ids)}\n")
for num in ids[-10:]:
    _, partes = m.fetch(num, "(BODY.PEEK[])")
    msg = email.message_from_bytes(partes[0][1], policy=email.policy.default)
    asunto, de, fecha = str(msg.get("Subject") or ""), str(msg.get("From") or ""), str(msg.get("Date") or "")
    cuerpo = c.texto_del_mail(msg)
    print("-" * 70)
    print("De     :", de)
    print("Fecha  :", fecha)
    print("Asunto :", asunto)
    print("Decide :", "AVISAR por WhatsApp" if c.es_de_colecta(asunto, cuerpo, de) else "IGNORAR (no es de colecta de Mercado Libre)")
    print("Datos  :", c.extraer_datos(cuerpo) or "ninguno leido")
    print("Texto  :", (cuerpo[:300] or "(vacio)").replace("\n", " | "))
m.logout()
