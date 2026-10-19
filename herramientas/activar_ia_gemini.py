"""Asistente interactivo para activar la IA (Google Gemini 2.5 Flash) en EnvioBot Full.

- No requiere usar comandos complejos ni pegar la clave en el chat.
- Abre Google AI Studio si todavía no tenés la clave.
- Prueba la clave en vivo con un mensaje de colecta de ejemplo antes de guardarla.
- La guarda en el .env local (backend/.env) y, si confirmás con SI, también la carga en el
  servidor de producción (enviobot-vps:/var/www/enviobot-full/backend/.env) con respaldo previo.
"""
import os
import shutil
import subprocess
import sys
import time
import webbrowser

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(RAIZ, "backend")
ENV_LOCAL = os.path.join(BACKEND_DIR, ".env")
SERVIDOR = "enviobot-vps"
ENV_REMOTO = "/var/www/enviobot-full/backend/.env"
SERVICIO = "enviobot-full"
URL_GOOGLE_AI_STUDIO = "https://aistudio.google.com/apikey"

sys.path.insert(0, BACKEND_DIR)
import correo_colectas as c  # noqa: E402


def guardar_clave_en_archivo(ruta_env, clave, modelo="gemini-2.5-flash"):
    """Actualiza o agrega GEMINI_API_KEY y GEMINI_MODEL en un archivo .env local."""
    lineas = []
    if os.path.exists(ruta_env):
        sello = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(ruta_env, f"{ruta_env}.bak_{sello}")
        with open(ruta_env, "r", encoding="utf-8") as f:
            lineas = f.read().splitlines()

    nuevas = []
    puso_key = False
    puso_mod = False
    for linea in lineas:
        limpia = linea.lstrip()
        if limpia.startswith("GEMINI_API_KEY="):
            nuevas.append(f"GEMINI_API_KEY={clave}")
            puso_key = True
        elif limpia.startswith("GEMINI_MODEL="):
            nuevas.append(f"GEMINI_MODEL={modelo}")
            puso_mod = True
        else:
            nuevas.append(linea)

    if not puso_key:
        if nuevas and nuevas[-1].strip() != "":
            nuevas.append("")
        nuevas.append("# IA Gemini para analizar mails y avisos de colecta")
        nuevas.append(f"GEMINI_API_KEY={clave}")
    if not puso_mod:
        nuevas.append(f"GEMINI_MODEL={modelo}")

    with open(ruta_env, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(nuevas) + "\n")


def cargar_en_servidor(clave, modelo="gemini-2.5-flash"):
    """Guarda GEMINI_API_KEY en el .env del VPS con respaldo previo y reinicia el servicio."""
    import base64
    script_remoto = """import os, shutil, sys, time
ruta = "/var/www/enviobot-full/backend/.env"
clave = sys.stdin.readline().strip()
modelo = sys.stdin.readline().strip() or "gemini-2.5-flash"
if not clave:
    sys.exit(2)
sello = time.strftime("%Y%m%d_%H%M%S")
respaldo = f"{ruta}.antes_ia_{sello}"
shutil.copy2(ruta, respaldo)
os.chmod(respaldo, 0o600)
with open(ruta, "r", encoding="utf-8") as f:
    lineas = f.read().splitlines()
nuevas = [l for l in lineas if not l.lstrip().startswith(("GEMINI_API_KEY=", "GEMINI_MODEL="))]
if nuevas and nuevas[-1].strip() != "":
    nuevas.append("")
nuevas.append(f"GEMINI_API_KEY={clave}")
nuevas.append(f"GEMINI_MODEL={modelo}")
with open(ruta, "w", encoding="utf-8", newline="\\n") as f:
    f.write("\\n".join(nuevas) + "\\n")
os.chmod(ruta, 0o600)
print("OK_RESPALDO:" + respaldo)
"""
    b64 = base64.b64encode(script_remoto.encode("utf-8")).decode("ascii")
    cmd_remoto = f"python3 -c 'import base64; exec(base64.b64decode(\"{b64}\").decode(\"utf-8\"))' && systemctl restart {SERVICIO}"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SERVIDOR, cmd_remoto],
        input=f"{clave}\n{modelo}\n",
        text=True,
        capture_output=True,
    )
    return r.returncode == 0, (r.stdout + "\n" + r.stderr).strip()


def main():
    print("=" * 66)
    print("  ACTIVAR IA (GOOGLE GEMINI 2.5 FLASH) EN ENVIOBOT FULL")
    print("=" * 66)
    print("\nCómo sacar tu clave gratis en 2 clics:")
    print(f"  1. Entrá a: {URL_GOOGLE_AI_STUDIO}")
    print("  2. Hacé clic en el botón azul 'Create API key' (Crear clave de API).")
    print("  3. Copiala (empieza con 'AIza...').\n")

    abrir = input("¿Querés que te abra ahora la página de Google para copiar la clave? (S/n): ").strip().lower()
    if abrir in ("", "s", "si", "sí", "y"):
        try:
            webbrowser.open(URL_GOOGLE_AI_STUDIO)
            print("  -> Página abierta en tu navegador.\n")
        except Exception:
            pass

    clave = input("Pegá acá tu clave de Gemini (AIza...) y apretá Enter:\n> ").strip()
    if not clave:
        print("\nNo ingresaste ninguna clave. Cancelado.")
        return

    print("\n[1/3] Probando la clave en vivo con Gemini 2.5 Flash...")
    prueba_asunto = "Reprogramación de tu colecta de Mercado Envíos Full"
    prueba_cuerpo = (
        "Hola MISTERNUT, te avisamos que la colecta del envío N.º 78889570 "
        "pasará el 19 de octubre entre las 16:00 y las 18:00 hs. "
        "Cód. autorización: 9F769D2F. Transportista: Luciano Damian Marenzi. "
        "Patente: AB304TX. Transportadora: Dos Haches."
    )
    res = c.analizar_con_ia(prueba_asunto, prueba_cuerpo, env={"GEMINI_API_KEY": clave, "GEMINI_MODEL": "gemini-2.5-flash"})
    if not res or not res.get("resumen"):
        print("\n[ERROR] Google rechazó la clave o no respondió. Revisá que esté bien copiada (sin espacios de más).")
        return

    print("      ¡Funciona perfecto! Así resumió el mensaje de prueba:")
    print("      --------------------------------------------------------")
    print(f"      Resumen IA : {res.get('resumen')}")
    print(f"      Horario    : {res.get('desde')} a {res.get('hasta')} hs ({res.get('fecha')})")
    print(f"      Código     : {res.get('codigo')} | Patente: {res.get('patente')}")
    print("      --------------------------------------------------------")

    print("\n[2/3] Guardando en esta PC (backend/.env)...")
    guardar_clave_en_archivo(ENV_LOCAL, clave)
    print("      Guardada en backend/.env.")

    subir = input("\n[3/3] ¿Querés dejarla activa también en el servidor de producción ahora mismo? (escribí SI): ").strip().upper()
    if subir == "SI":
        print("      Conectando al servidor y guardando con respaldo previo...")
        ok, detalle = cargar_en_servidor(clave)
        if ok:
            print("      ¡LISTO! La IA ya quedó activa en el servidor de producción y en esta PC.")
        else:
            print(f"      No se pudo guardar en el servidor automáticamente ({detalle}).")
            print("      Quedó guardada en tu PC.")
    else:
        print("      Listo: quedó activa en tu PC (el servidor no se tocó).")


if __name__ == "__main__":
    main()
