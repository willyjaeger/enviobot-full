"""Corre EN EL SERVIDOR (se manda por ssh). Aplica la migracion 006 de EnvioBot Full: tablas nuevas ventas_diarias y ventas_semanales.
Solo crea tablas nuevas de Full: no toca ninguna tabla existente ni Pedidos, asi que no hay nada que respaldar de ellas.
1) Apaga enviobot-full, aplica el SQL, vuelve a prender.  2) Verifica las tablas y que el servicio responda. Nunca muestra claves.
"""
import os
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
SERVICIO = "enviobot-full"
SQL = RAIZ + "/backend/migration_006_ventas_diarias.sql"
TABLAS = ("ventas_diarias", "ventas_semanales")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def leer_env():
    d = {}
    for l in open(RAIZ + "/backend/.env", encoding="utf-8").read().splitlines():
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def servicio_ok():
    if sh(["systemctl", "is-active", "--quiet", SERVICIO]).returncode != 0:
        return False
    r = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:5001/"])
    return r.stdout.strip() in ("200", "301", "302")


def main():
    if not os.path.exists(SQL):
        print("Falta " + SQL + ": desplegar primero con SUBIR_A_PRODUCCION.bat")
        return 1
    e = leer_env()
    entorno = dict(os.environ, MYSQL_PWD=e["DB_PASSWORD"])
    base = ["-h", e.get("DB_HOST", "localhost"), "-P", e.get("DB_PORT", "3306"), "-u", e["DB_USER"]]
    fallo = False
    sh(["systemctl", "stop", SERVICIO])
    try:
        with open(SQL, encoding="utf-8") as f:
            r = sh(["mysql"] + base + [e["DB_NAME"]], env=entorno, input=f.read())
        if r.returncode != 0:
            print("Migracion 006: FALLO:", r.stderr.strip()[:300])
            fallo = True
        for t in TABLAS:
            r = sh(["mysql"] + base + ["-N", "-e",
                   "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
                   f"AND TABLE_NAME='{t}'", e["DB_NAME"]], env=entorno)
            ok = r.stdout.strip() == "1"
            fallo = fallo or not ok
            print(f"Migracion 006: tabla {t}:", "OK" if ok else "NO ESTA")
    finally:
        sh(["systemctl", "start", SERVICIO])
        time.sleep(4)
    if not servicio_ok():
        print("El servicio no responde. Estado:")
        print(sh(["systemctl", "status", SERVICIO, "--no-pager", "-n", "8"]).stdout[-600:])
        return 1
    print("Servicio funcionando." + (" REVISAR: la migracion fallo." if fallo else " Migracion 006 aplicada."))
    return 1 if fallo else 0


sys.exit(main())
