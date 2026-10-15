"""Corre EN EL SERVIDOR. Solo toca EnvioBot Full (no toca Pedidos).

1) Copia a /var/www/enviobot-full/backend/.env (la caja REAL que lee la app)
   las claves que le faltan y estan en /var/www/enviobot-full/.env.
   No pisa ninguna clave que ya exista.
2) Deja las dos cajas de Full legibles solo por root (chmod 600).
3) Reinicia Full y verifica. Si falla, vuelve atras.
Nunca muestra valores, solo nombres.
"""
import os
import shutil
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
REAL = RAIZ + "/backend/.env"
OTRA = RAIZ + "/.env"
SERVICIO = "enviobot-full"
# Solo estas claves se pasan de una caja a la otra (nada de claves de login ni de base).
PASAR = ["WELCOME_SMTP_PASSWORD", "ALERT_SMTP_PASSWORD", "ALERT_SENDER_EMAIL"]


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def leer(ruta):
    d = {}
    for l in open(ruta, encoding="utf-8").read().splitlines():
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.split("=", 1)
            d[k.strip()] = v
    return d


def ok():
    if sh(["systemctl", "is-active", "--quiet", SERVICIO]).returncode != 0:
        return False
    r = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:5001/"])
    return r.stdout.strip() in ("200", "301", "302", "404")


def main():
    print("=== Ordenando las cajas de claves de EnvioBot Full ===")
    sello = time.strftime("%Y%m%d_%H%M%S")
    respaldo = REAL + ".antes_" + sello
    shutil.copy2(REAL, respaldo)
    os.chmod(respaldo, 0o600)
    print("[1/4] Respaldo de la caja real listo.")

    real, otra = leer(REAL), leer(OTRA)
    agregar = []
    for k in PASAR:
        if k in real:
            print("      %s: ya estaba, no se toca" % k)
        elif k in otra and otra[k]:
            agregar.append("%s=%s" % (k, otra[k]))
            print("      %s: se agrega" % k)
        else:
            print("      %s: no esta en ninguna caja (revisar a mano)" % k)
    if agregar:
        txt = open(REAL, encoding="utf-8").read()
        sep = "" if txt.endswith("\n") else "\n"
        with open(REAL, "a", encoding="utf-8") as f:
            f.write(sep + "\n".join(agregar) + "\n")

    print("[2/4] Cerrando permisos (solo root)...")
    os.chmod(REAL, 0o600)
    os.chmod(OTRA, 0o600)

    print("[3/4] Reiniciando Full...")
    sh(["systemctl", "restart", SERVICIO])
    time.sleep(6)

    print("[4/4] Verificando...")
    if not ok():
        print("\n[ATENCION] Full no respondio. Volviendo atras...")
        shutil.copy2(respaldo, REAL)
        os.chmod(REAL, 0o600)
        sh(["systemctl", "restart", SERVICIO])
        time.sleep(5)
        print("Volvi atras y Full esta %s." % ("activo" if ok() else "CAIDO: revisar YA"))
        sys.exit(1)
    print("\n=== LISTO: Full responde y las cajas quedaron protegidas. ===")
    print("Respaldo: " + respaldo)


if __name__ == "__main__":
    main()
