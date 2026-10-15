"""
desplegar_seguro.py - Despliegue seguro de EnvioBot Full a producción.

Criterios (ver ../enviobot-comun/CRITERIOS_ENVIOBOT.md):
  - Entra al servidor SOLO con llave SSH (alias `enviobot-vps`); no hay contraseñas acá.
  - Antes de subir: git al día con origin (Guillermo también despliega desde otra PC).
  - Respaldo con fecha en el servidor, subida, reinicio y verificación.
  - Si la verificación falla, vuelve solo a la versión anterior.
  - NO toca la base de datos, el .env ni el entorno virtual (venv).

Uso:
    python desplegar_seguro.py              despliegue real (pide escribir SI)
    python desplegar_seguro.py simular      recorre todo sin tocar el servidor
    python desplegar_seguro.py simular fallo  simula un fallo para probar la vuelta atrás
"""

import os
import subprocess
import sys
import tempfile
import time

SERVIDOR = "enviobot-vps"            # alias SSH con llave (definido en ~/.ssh/config)
REMOTO = "/var/www/enviobot-full"    # carpeta de la app en el servidor
SERVICIO = "enviobot-full"
PUERTO_LOCAL = 5001                  # gunicorn escucha en 127.0.0.1:5001
CARPETAS = ("backend", "frontend")   # lo único que se sube
RAIZ = os.path.abspath(os.path.dirname(__file__))

SIMULAR = len(sys.argv) > 1 and sys.argv[1].lower() == "simular"
FORZAR_FALLO = SIMULAR and len(sys.argv) > 2 and sys.argv[2].lower() == "fallo"


def correr(cmd, **kw):
    return subprocess.run(cmd, cwd=RAIZ, text=True, capture_output=True, **kw)


def ssh(comando):
    """Corre un comando en el servidor. En simulación solo lo muestra."""
    if SIMULAR:
        print(f"      [SIMULACION] ssh {SERVIDOR}: {comando}")
        return subprocess.CompletedProcess([], 0, "", "")
    return correr(["ssh", "-o", "BatchMode=yes", SERVIDOR, comando])


def frenar(mensaje):
    print(f"\n[FRENADO] {mensaje}")
    sys.exit(1)


def revisar_git():
    print("[0/5] Revisando que git esté al día...")
    rama = correr(["git", "branch", "--show-current"]).stdout.strip()
    if rama != "main":
        frenar(f"Estás en la rama '{rama}', no en 'main'. No se despliega.")
    sucios = correr(["git", "status", "--short", "--untracked-files=no", "--", *CARPETAS]).stdout.strip()
    if sucios:
        print("      Archivos con cambios SIN commitear (se subirían igual):")
        for linea in sucios.splitlines():
            print(f"        {linea}")
    f = correr(["git", "fetch", "origin"])
    if f.returncode != 0:
        frenar(f"No pude consultar GitHub: {f.stderr.strip()}")
    cuenta = correr(["git", "rev-list", "--left-right", "--count", "main...origin/main"]).stdout.split()
    adelante, atras = int(cuenta[0]), int(cuenta[1])
    if atras:
        frenar(f"GitHub tiene {atras} cambio(s) que esta PC no tiene. Hacé 'git pull' primero: "
               "si no, se pisaría en producción trabajo hecho desde otra PC.")
    if adelante:
        print(f"      Aviso: hay {adelante} commit(s) locales sin subir a GitHub.")
    print("      Git al día.")


def armar_paquete(destino):
    """Empaqueta solo los archivos versionados de backend/ y frontend/."""
    archivos = correr(["git", "ls-files", "--", *CARPETAS]).stdout.splitlines()
    archivos = [a for a in archivos if not os.path.basename(a).startswith(("scratch_", "check_", "inspect_"))]
    lista = os.path.join(tempfile.gettempdir(), "enviobot_full_lista.txt")
    with open(lista, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(archivos) + "\n")
    r = correr(["tar", "-czf", destino, "-T", lista])
    if r.returncode != 0:
        frenar(f"No pude armar el paquete: {r.stderr.strip()}")
    return len(archivos)


def main():
    print("=" * 62)
    print("  DESPLIEGUE SEGURO DE ENVIOBOT FULL A PRODUCCION")
    print("=" * 62)
    if SIMULAR:
        print("*** MODO SIMULACION: no se toca el servidor ***")
    print(f"Destino: {SERVIDOR}:{REMOTO}  (servicio {SERVICIO})")
    print("NO toca la base de datos, el .env ni el entorno virtual.")
    print("Si lo que subís necesita migraciones o dependencias nuevas, NO uses este programa.\n")

    revisar_git()

    if input("\nEscribí SI para continuar y apretá Enter: ").strip().upper() != "SI":
        print("Cancelado. No se tocó nada.")
        return

    sello = time.strftime("%Y%m%d_%H%M%S")
    paquete = os.path.join(tempfile.gettempdir(), f"enviobot_full_{sello}.tar.gz")
    respaldo = f"{REMOTO}/backups/antes_deploy_{sello}.tar.gz"
    remoto_tmp = f"/tmp/enviobot_full_{sello}.tar.gz"

    print("\n[1/5] Armando el paquete...")
    n = armar_paquete(paquete)
    print(f"      {n} archivos.")

    print("\n[2/5] Respaldo de lo que hay en el servidor...")
    r = ssh(f"mkdir -p {REMOTO}/backups && cd {REMOTO} && "
            f"tar --exclude='backend/venv' --exclude='backend/logs' --exclude='backend/.env' "
            f"--exclude='__pycache__' -czf {respaldo} backend frontend")
    if r.returncode != 0:
        frenar(f"No se pudo hacer el respaldo, no se sube nada. {r.stderr.strip()}")
    print(f"      Respaldo: {respaldo}")

    print("\n[3/5] Subiendo...")
    if not SIMULAR:
        r = correr(["scp", "-o", "BatchMode=yes", paquete, f"{SERVIDOR}:{remoto_tmp}"])
        if r.returncode != 0:
            frenar(f"Falló la subida (no se tocó la app): {r.stderr.strip()}")
    r = ssh(f"tar -xzf {remoto_tmp} -C {REMOTO} && rm -f {remoto_tmp}")
    if r.returncode != 0:
        print(f"      Falló la extracción: {r.stderr.strip()}")
        return revertir(respaldo)

    print("\n[4/5] Reiniciando el servicio (la app se corta unos segundos)...")
    r = ssh(f"systemctl restart {SERVICIO}")
    if r.returncode != 0:
        return revertir(respaldo)

    print("\n[5/5] Verificando...")
    if not SIMULAR:
        time.sleep(5)
    if FORZAR_FALLO:
        print("      [SIMULACION] forzando un fallo de verificación")
        return revertir(respaldo)
    r = ssh(f"systemctl is-active --quiet {SERVICIO} && "
            f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{PUERTO_LOCAL}/ | grep -qE '^(200|301|302|404)$'")
    if r.returncode != 0:
        return revertir(respaldo)

    print("\n" + "=" * 62)
    print("  DESPLIEGUE COMPLETADO. La app responde.")
    print(f"  Respaldo por si hace falta volver atrás: {respaldo}")
    print("=" * 62)


def revertir(respaldo):
    print("\n[ATENCION] Algo falló. Volviendo a la versión anterior...")
    r = ssh(f"tar -xzf {respaldo} -C {REMOTO} && systemctl restart {SERVICIO} && systemctl is-active --quiet {SERVICIO}")
    if r.returncode == 0:
        print("      Volví a la versión anterior y el servicio está activo.")
    else:
        print("      NO pude confirmar la vuelta atrás. Revisá el servidor YA:")
        print(f"      el respaldo está en {respaldo}")
    sys.exit(1)


if __name__ == "__main__":
    main()
