"""
deploy_direct.py - Despliegue directo al VPS DonWeb (sin pasar por Git/GitHub)
Transfiere los archivos directamente via SSH/SFTP y reinicia el servicio en segundos.
"""

import io
import os
import sys
import tarfile
import time
import paramiko

VPS_HOST = "179.43.123.220"
VPS_PORT = 5375
VPS_USER = "root"
VPS_PASS = "Willy.48462800"
REMOTE_DIR = "/var/www/enviobot-full"

# Carpetas y archivos a excluir de la sincronización
EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", ".vscode", ".idea"}
EXCLUDE_FILES = {".env", "SUBIR_A_PRODUCCION.bat", ".gitignore", "deploy.py"}
EXCLUDE_EXTS = {".pyc", ".tmp", ".log"}

def should_exclude(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    filename = parts[-1]
    if filename in EXCLUDE_FILES:
        return True
    if filename.startswith(("scratch_", "check_", "test_", "inspect_")):
        return True
    if filename.startswith("admin_index_") and not rel_path.startswith("frontend"):
        return True
    _, ext = os.path.splitext(filename)
    if ext.lower() in EXCLUDE_EXTS:
        return True
    return False

def build_tarball(root_dir):
    buffer = io.BytesIO()
    added_files = []
    
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for root, dirs, files in os.walk(root_dir):
            # Filtrar directorios in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                
                if should_exclude(rel_path):
                    continue
                
                # Normalizar ruta para tar unix
                tar_rel_path = rel_path.replace("\\", "/")
                tar.add(full_path, arcname=tar_rel_path)
                added_files.append(tar_rel_path)
                
    buffer.seek(0)
    return buffer, added_files

def main():
    start_time = time.time()
    project_root = os.path.abspath(os.path.dirname(__file__))
    
    print("=" * 65)
    print("      ENVIOBOT FULL - DESPLIEGUE DIRECTO A DONWEB VPS")
    print("=" * 65)
    print(f"Origen local:    {project_root}")
    print(f"Destino remoto:  {VPS_HOST}:{VPS_PORT} -> {REMOTE_DIR}")
    print("Método:          SSH / SFTP directo (Sin dependencias de Git/GitHub)")
    print("-" * 65)

    print("\n[1/5] Empaquetando archivos del proyecto...")
    tar_buffer, added_files = build_tarball(project_root)
    tar_size_kb = len(tar_buffer.getvalue()) / 1024
    print(f"      Total archivos empaquetados: {len(added_files)} ({tar_size_kb:.1f} KB comprimido)")

    print(f"\n[2/5] Conectando por SSH a DonWeb VPS ({VPS_HOST}:{VPS_PORT})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
        print("      Conexión SSH establecida exitosamente.")
    except Exception as e:
        print(f"      [ERROR] Falló la conexión SSH: {e}")
        sys.exit(1)

    print("\n[3/5] Transfiriendo paquete por SFTP directo...")
    try:
        sftp = ssh.open_sftp()
        remote_tmp_tar = "/tmp/enviobot_direct_update.tar.gz"
        sftp.putfo(tar_buffer, remote_tmp_tar)
        sftp.close()
        print("      Paquete transferido a /tmp en el VPS.")
    except Exception as e:
        print(f"      [ERROR] Falló la transferencia SFTP: {e}")
        ssh.close()
        sys.exit(1)

    print("\n[4/5] Extrayendo archivos y actualizando producción...")
    cmds = [
        f"tar -xzf /tmp/enviobot_direct_update.tar.gz -C {REMOTE_DIR}",
        "rm -f /tmp/enviobot_direct_update.tar.gz",
        f"sed -i 's/^ML_SHARED_CLIENT_ID=.*/ML_SHARED_CLIENT_ID=1845856849463362/' {REMOTE_DIR}/.env 2>/dev/null || true",
        f"sed -i 's/^ML_CLIENT_SECRET=.*/ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q/' {REMOTE_DIR}/.env 2>/dev/null || true",
        f"grep -q 'ML_SHARED_CLIENT_ID' {REMOTE_DIR}/.env || echo 'ML_SHARED_CLIENT_ID=1845856849463362' >> {REMOTE_DIR}/.env",
        f"grep -q 'ML_CLIENT_SECRET' {REMOTE_DIR}/.env || echo 'ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q' >> {REMOTE_DIR}/.env",
        f"grep -q 'ML_REDIRECT_URI' {REMOTE_DIR}/.env || echo 'ML_REDIRECT_URI=https://enviobot.com.ar/api/full/ml/auth/callback' >> {REMOTE_DIR}/.env",
        "systemctl restart enviobot-full",
    ]

    full_cmd = " && ".join(cmds)
    stdin, stdout, stderr = ssh.exec_command(full_cmd, timeout=60)
    out = stdout.read().decode("utf-8", errors="ignore").strip()
    err = stderr.read().decode("utf-8", errors="ignore").strip()
    if err and "Warning" not in err:
        print(f"      Avisos/Salida: {err}")

    print("\n[5/5] Verificando salud del servicio y API...")
    _, stdout_status, _ = ssh.exec_command("systemctl is-active enviobot-full", timeout=5)
    service_status = stdout_status.read().decode("utf-8", errors="ignore").strip()
    
    _, stdout_api, _ = ssh.exec_command("curl -s --max-time 3 http://127.0.0.1:5001/api/full/items -H 'Accept: application/json' || true", timeout=5)
    api_response = stdout_api.read().decode("utf-8", errors="ignore").strip()
    
    ssh.close()

    elapsed = time.time() - start_time
    print("-" * 65)
    print(f"Estado del servicio: {service_status.upper()}")
    print(f"Respuesta de la API: {api_response[:60]}...")
    print(f"Tiempo total:        {elapsed:.2f} segundos")
    print("=" * 65)
    
    if service_status == "active":
        print(">>> DESPLIEGUE DIRECTO A DONWEB COMPLETADO CON ÉXITO <<<")
    else:
        print(">>> ADVERTENCIA: Revisar estado del servicio en el VPS <<<")
        sys.exit(1)

if __name__ == "__main__":
    main()
