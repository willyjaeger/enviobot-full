@echo off
chcp 65001 > nul
title SUBIR A DONWEB VPS - ENVIOBOT FULL
color 0A

echo ====================================================================
echo             ENVIOBOT FULL - SUBIR DIRECTO A DONWEB VPS
echo ====================================================================
echo.
echo  Destino:  179.43.123.220:5375 (/var/www/enviobot-full)
echo  Metodo:   SSH / SFTP Directo (Sin Git ni intermediarios)
echo.
echo ====================================================================
echo.

cd /d "C:\Proyecto\Enviobot Full"
if errorlevel 1 (
    echo [ERROR] No se pudo encontrar la carpeta C:\Proyecto\Enviobot Full
    pause
    exit /b 1
)

python deploy_direct.py

echo.
pause
