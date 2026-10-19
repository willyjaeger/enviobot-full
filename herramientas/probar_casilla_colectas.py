"""Corre EN EL SERVIDOR (se manda por ssh). Solo lectura: prueba la casilla de colectas y dice que falla.
Nunca muestra la clave: solo su largo y si tiene algun caracter que complique.
"""
import imaplib
import os
import socket

from dotenv import dotenv_values

ENV = "/var/www/enviobot-full/backend/.env"
e = dotenv_values(ENV)
usuario = e.get("COLECTAS_IMAP_USER") or ""
clave = e.get("COLECTAS_IMAP_PASSWORD") or ""
host = e.get("COLECTAS_IMAP_HOST") or ""

print("usuario cargado :", repr(usuario))
print("host cargado    :", repr(host))
print("largo de clave  :", len(clave), "(0 = no se cargo)")
raros = [n for n, c in (("espacio", " "), ("numeral #", "#"), ("dolar $", "$"), ("comilla", '"'), ("comilla simple", "'"), ("retorno \\r", "\r")) if c in clave]
print("caracteres raros:", raros or "ninguno")
print("whatsapp cargado:", "si" if (e.get("COLECTAS_WHATSAPP") or "").strip() else "NO")
print()

candidatos = []
for h in (host, "po000380.ferozo.com", "mail.enviobot.com.ar", "imap.enviobot.com.ar", "imap.donweb.com"):
    if h and h not in candidatos:
        candidatos.append(h)

for h in candidatos:
    try:
        socket.gethostbyname(h)
    except OSError:
        print(f"{h:28} no existe (DNS)")
        continue
    try:
        m = imaplib.IMAP4_SSL(h, 993, timeout=15)
    except Exception as ex:
        print(f"{h:28} no se pudo conectar: {ex}")
        continue
    try:
        m.login(usuario, clave)
        _, n = m.select("INBOX")
        print(f"{h:28} FUNCIONA: entro, {int(n[0])} mails en la bandeja")
        m.logout()
    except imaplib.IMAP4.error as ex:
        print(f"{h:28} conecta, pero rechaza usuario/clave: {ex}")
