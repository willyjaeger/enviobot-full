import os
import subprocess
import paramiko

def main():
    print("=== 1. COMMITTING LOCAL CHANGES ===")
    try:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "Separar suscripcion EnvioBot Pedidos de Full, activar 30 dias de prueba gratis y flujo OAuth MeLi"], check=False)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("Git push exitoso a origin/main.")
    except Exception as e:
        print(f"Aviso git local: {e}")

    print("\n=== 2. DEPLOYING TO DONWEB VPS ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('179.43.123.220', port=5375, username='root', password='Willy.48462800')

    cmds = [
        "cd /var/www/enviobot-full && git pull origin main",
        "sed -i 's/^ML_SHARED_CLIENT_ID=.*/ML_SHARED_CLIENT_ID=1845856849463362/' /var/www/enviobot-full/.env 2>/dev/null || true",
        "sed -i 's/^ML_CLIENT_SECRET=.*/ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q/' /var/www/enviobot-full/.env 2>/dev/null || true",
        "grep -q 'ML_SHARED_CLIENT_ID' /var/www/enviobot-full/.env || echo 'ML_SHARED_CLIENT_ID=1845856849463362' >> /var/www/enviobot-full/.env",
        "grep -q 'ML_CLIENT_SECRET' /var/www/enviobot-full/.env || echo 'ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q' >> /var/www/enviobot-full/.env",
        "grep -q 'ML_REDIRECT_URI' /var/www/enviobot-full/.env || echo 'ML_REDIRECT_URI=https://enviobot.com.ar/api/full/ml/auth/callback' >> /var/www/enviobot-full/.env",
        "systemctl restart enviobot-full",
        "systemctl is-active enviobot-full",
        "curl -s http://127.0.0.1:5001/api/full/items -H 'Accept: application/json' || true"
    ]

    for cmd in cmds:
        print(f"\n--- Ejecutando en VPS: {cmd} ---")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        if out: print(out.strip())
        if err: print(err.strip())

    ssh.close()
    print("\n=== DEPLOY COMPLETADO EXITOSAMENTE ===")

if __name__ == "__main__":
    main()
