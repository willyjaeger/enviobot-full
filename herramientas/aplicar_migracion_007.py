"""Corre EN EL SERVIDOR (se manda por ssh). Aplica la migracion 007 de EnvioBot Full: tabla nueva ml_reposicion.
Solo crea una tabla nueva de Full: no toca ninguna tabla existente ni Pedidos.
Apaga enviobot-full, aplica el SQL, vuelve a prender y verifica la tabla y que el servicio responda. Nunca muestra claves.
"""
import os
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
SERVICIO = "enviobot-full"
SQL = RAIZ + "/backend/migration_007_reposicion_ml.sql"


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
        print("Falta " + SQL + ": desplegar primero")
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
            print("Migracion 007: FALLO:", r.stderr.strip()[:300])
            fallo = True
        r = sh(["mysql"] + base + ["-N", "-e", "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
               "AND TABLE_NAME='ml_reposicion'", e["DB_NAME"]], env=entorno)
        ok = r.stdout.strip() == "1"
        fallo = fallo or not ok
        print("Migracion 007: tabla ml_reposicion:", "OK" if ok else "NO ESTA")
    finally:
        sh(["systemctl", "start", SERVICIO])
        time.sleep(4)
    if not servicio_ok():
        print("El servicio no responde. Estado:")
        print(sh(["systemctl", "status", SERVICIO, "--no-pager", "-n", "8"]).stdout[-600:])
        return 1
    print("Servicio funcionando." + (" REVISAR: la migracion fallo." if fallo else " Migracion 007 aplicada."))
    return 1 if fallo else 0


sys.exit(main())
