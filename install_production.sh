#!/bin/bash
set -e

echo "=========================================================="
echo "   Iniciando Instalación de EnvioBot Full en Producción   "
echo "=========================================================="

echo "[1/7] Actualizando repositorios e instalando paquetes del sistema..."
apt update
apt install -y git python3 python3-venv python3-pip nginx mysql-server

echo "[2/7] Iniciando y configurando MySQL..."
systemctl enable --now mysql
mysql -e "CREATE DATABASE IF NOT EXISTS enviobot_full CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql enviobot_full < /var/www/enviobot-full/backend/schema.sql

echo "[3/7] Configurando entorno virtual de Python..."
cd /var/www/enviobot-full/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt gunicorn

echo "[4/7] Configurando variables de entorno (.env)..."
if [ ! -f .env ]; then
    cp .env.example .env
    # Generar claves JWT seguras aleatorias
    SECRET_KEY=$(openssl rand -hex 24)
    JWT_SECRET=$(openssl rand -hex 24)
    sed -i "s/cambiar_en_produccion_clave_secreta_super_segura/$SECRET_KEY/" .env
    sed -i "s/cambiar_en_produccion_jwt_secret_key/$JWT_SECRET/" .env
    sed -i "s/DB_HOST=localhost/DB_HOST=127.0.0.1/" .env
fi

echo "[5/7] Configurando servicio Systemd (Gunicorn)..."
cp /var/www/enviobot-full/backend/enviobot-full.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now enviobot-full

echo "[6/7] Configurando servidor web Nginx..."
cp /var/www/enviobot-full/backend/nginx.conf /etc/nginx/sites-available/enviobot-full
ln -sf /etc/nginx/sites-available/enviobot-full /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "[7/7] Configurando tarea automática (Cron cada 4 horas)..."
(crontab -l 2>/dev/null | grep -v "worker.py"; echo "0 */4 * * * /var/www/enviobot-full/backend/venv/bin/python /var/www/enviobot-full/backend/worker.py >> /var/log/enviobot_full.log 2>&1") | crontab -

echo "=========================================================="
echo "   ¡EnvioBot Full instalado y funcionando en producción!  "
echo "=========================================================="
systemctl status enviobot-full --no-pager
