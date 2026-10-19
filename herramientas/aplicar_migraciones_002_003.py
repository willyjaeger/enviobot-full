"""Corre EN EL SERVIDOR (se manda por ssh). Aplica las migraciones 002 y 003 de EnvioBot Full de una vez.

002: columna full_items.sub_status (motivo de pausa de cada publicacion).
003: columna alert_recipients.avisos (que avisos recibe cada destinatario).
Solo agrega esas dos columnas. No toca Pedidos ni otras tablas.
1) Respaldo de las dos tablas en /var/www/enviobot-full/backups/.
2) Apaga enviobot-full, aplica los SQL, vuelve a prender.
3) Verifica las columnas y que el servicio responda. Nunca muestra claves.
"""
import os
import subprocess
import sys
import time

RAIZ = "/var/www/enviobot-full"
SERVICIO = "enviobot-full"
MIGRACIONES = [
    ("002", RAIZ + "/backend/migration_002_motivo_pausa.sql", "full_items", "sub_status"),
    ("003", RAIZ + "/backend/migration_003_avisos_por_destinatario.sql", "alert_recipients", "avisos"),
]


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
    for _n, ruta, _t, _c in MIGRACIONES:
        if not os.path.exists(ruta):
            print("Falta " + ruta + ": desplegar primero con SUBIR_A_PRODUCCION.bat")
            return 1
    e = leer_env()
    entorno = dict(os.environ, MYSQL_PWD=e["DB_PASSWORD"])
    base = ["-h", e.get("DB_HOST", "localhost"), "-P", e.get("DB_PORT", "3306"), "-u", e["DB_USER"]]

    os.makedirs(RAIZ + "/backups", exist_ok=True)
    resp = RAIZ + "/backups/tablas_antes_mig002_003_" + time.strftime("%Y%m%d_%H%M%S") + ".sql"
    tablas = sorted({t for _n, _r, t, _c in MIGRACIONES})
    r = sh(["mysqldump"] + base + ["--single-transaction", "--no-tablespaces", "-r", resp, e["DB_NAME"]] + tablas, env=entorno)
    if r.returncode != 0 or not os.path.getsize(resp):
        print("Fallo el respaldo, no se toco nada:", r.stderr.strip()[:200])
        return 1
    os.chmod(resp, 0o600)
    print("Respaldo listo:", resp)

    fallo = False
    sh(["systemctl", "stop", SERVICIO])
    try:
        for n, ruta, tabla, col in MIGRACIONES:
            with open(ruta, encoding="utf-8") as f:
                r = sh(["mysql"] + base + [e["DB_NAME"]], env=entorno, input=f.read())
            if r.returncode != 0:
                print(f"Migracion {n}: FALLO:", r.stderr.strip()[:300])
                fallo = True
                continue
            r = sh(["mysql"] + base + ["-N", "-e",
                   "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                   f"AND TABLE_NAME='{tabla}' AND COLUMN_NAME='{col}'", e["DB_NAME"]], env=entorno)
            ok = r.stdout.strip() == "1"
            fallo = fallo or not ok
            print(f"Migracion {n}: columna {tabla}.{col}:", "OK" if ok else "NO ESTA")
    finally:
        sh(["systemctl", "start", SERVICIO])
        time.sleep(4)

    if not servicio_ok():
        print("El servicio no responde. Estado:")
        print(sh(["systemctl", "status", SERVICIO, "--no-pager", "-n", "8"]).stdout[-600:])
        return 1
    print("Servicio funcionando." + (" REVISAR: alguna migracion fallo." if fallo else " Migraciones 002 y 003 aplicadas."))
    return 1 if fallo else 0


sys.exit(main())
