"""Corre EN EL SERVIDOR (se manda por ssh). Aplica la migracion 002 de EnvioBot Full.

Solo agrega la columna full_items.sub_status. No toca Pedidos ni otras tablas.
1) Respaldo de la tabla full_items en /var/www/enviobot-full/backups/.
2) Apaga enviobot-full, aplica el SQL, vuelve a prender.
3) Verifica que el servicio responda y que la columna exista. Si el servicio no vuelve, lo reintenta.
Nunca muestra claves.
"""
import os
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
SERVICIO = "enviobot-full"
SQL = RAIZ + "/backend/migration_002_motivo_pausa.sql"


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

    os.makedirs(RAIZ + "/backups", exist_ok=True)
    resp = RAIZ + "/backups/full_items_antes_mig002_" + time.strftime("%Y%m%d_%H%M%S") + ".sql"
    r = sh(["mysqldump"] + base + ["--single-transaction", "--no-tablespaces", "-r", resp, e["DB_NAME"], "full_items"], env=entorno)
    if r.returncode != 0 or not os.path.getsize(resp):
        print("Fallo el respaldo, no se toco nada:", r.stderr.strip()[:200])
        return 1
    os.chmod(resp, 0o600)
    print("Respaldo listo:", resp)

    sh(["systemctl", "stop", SERVICIO])
    try:
        with open(SQL, encoding="utf-8") as f:
            r = sh(["mysql"] + base + [e["DB_NAME"]], env=entorno, input=f.read())
        if r.returncode != 0:
            print("Fallo la migracion:", r.stderr.strip()[:300])
            return 1
        r = sh(["mysql"] + base + ["-N", "-e",
               "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
               "AND TABLE_NAME='full_items' AND COLUMN_NAME='sub_status'", e["DB_NAME"]], env=entorno)
        existe = r.stdout.strip() == "1"
        print("Columna sub_status:", "OK" if existe else "NO ESTA")
    finally:
        sh(["systemctl", "start", SERVICIO])
        time.sleep(4)

    if not servicio_ok():
        print("El servicio no responde. Estado:")
        print(sh(["systemctl", "status", SERVICIO, "--no-pager", "-n", "8"]).stdout[-600:])
        return 1
    print("Servicio funcionando. Migracion 002 aplicada.")
    return 0


sys.exit(main())
