"""Corre EN EL SERVIDOR (lo manda el .bat del escritorio por ssh).

Cambia la contraseña del usuario de base de datos `enviobot` por una nueva
generada al azar, la guarda en el .env de Full y reinicia Full.

Seguridad:
  - Antes de tocar nada, busca si OTRA app (Pedidos, n8n, etc.) usa ese usuario
    o esa contraseña. Si la encuentra, FRENA sin cambiar nada.
  - Hace respaldo del .env.
  - Si despues del cambio algo no responde, VUELVE A LA CLAVE ANTERIOR.
  - Nunca muestra ninguna contraseña.
"""
import os
import re
import secrets
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
ENV = RAIZ + "/.env"
SERVICIO = "enviobot-full"
USUARIO = "enviobot"
BASE = "enviobot_web"


def sh(cmd, entrada=None, env=None, timeout=120):
    return subprocess.run(cmd, input=entrada, capture_output=True, text=True,
                          env=env, timeout=timeout)


def frenar(msg):
    print("\n[FRENADO] " + msg)
    print("No se cambió nada.")
    sys.exit(1)


def leer_env(ruta):
    datos = {}
    for linea in open(ruta, encoding="utf-8").read().splitlines():
        if "=" in linea and not linea.lstrip().startswith("#"):
            k, v = linea.split("=", 1)
            datos[k.strip()] = v.strip().strip("'\"")
    return datos


def servicio_ok():
    if sh(["systemctl", "is-active", "--quiet", SERVICIO]).returncode != 0:
        return False
    r = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:5001/"])
    return r.stdout.strip() in ("200", "301", "302", "404")


def escribir_env(texto):
    with open(ENV, "w", encoding="utf-8") as f:
        f.write(texto)


def cambiar_clave_mysql(nueva):
    sql = f"ALTER USER '{USUARIO}'@'localhost' IDENTIFIED BY '{nueva}'; FLUSH PRIVILEGES;"
    return sh(["mysql"], entrada=sql)


def main():
    print("=== Rotando la clave de la base de datos (usuario %s) ===" % USUARIO)

    env_full = leer_env(ENV)
    vieja = env_full.get("DB_PASSWORD")
    if not vieja or env_full.get("DB_USER") != USUARIO:
        frenar("El .env de Full no tiene DB_USER=%s y DB_PASSWORD. Revisar antes." % USUARIO)

    # 1) ¿Alguien más usa este usuario o esta clave?
    print("[1/6] Buscando otras apps que usen el mismo usuario o clave...")
    r = sh(["find", "/opt", "/var/www", "/root", "/etc", "-maxdepth", "6", "-type", "f",
            "(", "-name", ".env", "-o", "-name", ".env.*", "-o", "-name", "*.service",
            "-o", "-name", "*.conf", "-o", "-name", "*.cfg", "-o", "-name", "*.yml",
            "-o", "-name", "*.yaml", "-o", "-name", "*.json", ")"], timeout=180)
    otros = []
    for ruta in r.stdout.splitlines():
        if ruta == ENV or ruta.startswith(RAIZ + "/.env.antes") or "/backups/" in ruta \
                or "/node_modules/" in ruta or ruta.startswith("/etc/ssl") or ruta.startswith("/etc/letsencrypt"):
            continue
        try:
            txt = open(ruta, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if vieja in txt or re.search(r"(?mi)^\s*(DB_USER|MYSQL_USER)\s*=\s*['\"]?%s\b" % USUARIO, txt):
            otros.append(ruta)
    if otros:
        frenar("Otras partes del servidor usan este usuario o esta clave:\n  - "
               + "\n  - ".join(otros)
               + "\nHay que cambiarlas juntas. Avisale a Claude con esta lista.")
    print("      Nadie más lo usa.")

    # 2) respaldo
    sello = time.strftime("%Y%m%d_%H%M%S")
    respaldo = f"{ENV}.antes_rotacion_{sello}"
    original = open(ENV, encoding="utf-8").read()
    with open(respaldo, "w", encoding="utf-8") as f:
        f.write(original)
    os.chmod(respaldo, 0o600)
    print("[2/6] Respaldo del .env listo.")

    # 3) clave nueva en la base
    nueva = secrets.token_hex(24)
    print("[3/6] Cambiando la clave en la base de datos...")
    r = cambiar_clave_mysql(nueva)
    if r.returncode != 0:
        frenar("MySQL no aceptó el cambio: " + r.stderr.strip()[:200])

    def deshacer(motivo):
        print("\n[ATENCION] %s. Volviendo a la clave anterior..." % motivo)
        escribir_env(original)
        r2 = cambiar_clave_mysql(vieja)
        sh(["systemctl", "restart", SERVICIO])
        time.sleep(4)
        if r2.returncode == 0 and servicio_ok():
            print("Volví a la clave anterior y Full está activo.")
        else:
            print("NO pude confirmar la vuelta atrás. Respaldo del .env: " + respaldo)
        sys.exit(1)

    # 4) guardar en el .env
    print("[4/6] Guardando la clave nueva en el .env de Full...")
    if re.search(r"(?m)^DB_PASSWORD=.*$", original):
        nuevo_txt = re.sub(r"(?m)^DB_PASSWORD=.*$", "DB_PASSWORD=" + nueva, original)
    else:
        nuevo_txt = original.rstrip("\n") + "\nDB_PASSWORD=" + nueva + "\n"
    escribir_env(nuevo_txt)

    # 5) probar la clave nueva y reiniciar
    print("[5/6] Probando la clave nueva y reiniciando Full...")
    entorno = dict(os.environ, MYSQL_PWD=nueva)
    t = sh(["mysql", "-h", "127.0.0.1", "-u", USUARIO, BASE, "-e", "SELECT 1"], env=entorno)
    if t.returncode != 0:
        return deshacer("La clave nueva no entra a la base")
    sh(["systemctl", "restart", SERVICIO])
    time.sleep(6)

    # 6) verificar
    print("[6/6] Verificando que Full responda...")
    if not servicio_ok():
        return deshacer("Full no respondió")

    print("\n=== LISTO: la clave de la base cambió y Full responde. ===")
    print("Respaldo del .env anterior (por si hace falta): " + respaldo)


if __name__ == "__main__":
    main()
