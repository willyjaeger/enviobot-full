import os
import sys
import subprocess
import paramiko

def main():
    print("=== 1. COMMITTING LOCAL CHANGES ===")
    commit_msg = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else "feat: consolidacion stock fisico Full sin duplicados y restauracion de tiempo de preparacion"
    try:
        subprocess.run(["git", "add", "."], check=False)
        subprocess.run(["git", "commit", "-m", commit_msg], check=False)
        res = subprocess.run(["git", "push", "origin", "main"], check=False)
        if res.returncode == 0:
            print("Git push exitoso a origin/main.")
        else:
            print("Aviso: Git push termino con codigo distinto de 0 (posiblemente al dia o verificar red).")
    except Exception as e:
        print(f"Aviso git local: {e}")

    print("\n=== 2. DEPLOYING TO DONWEB VPS ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('179.43.123.220', port=5375, username='root', password='Willy.48462800')

    cmds = [
        "cd /var/www/enviobot-full && git fetch origin main && git reset --hard origin/main",
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
