@echo off
chcp 65001 > nul
title SUBIR ENVIOBOT FULL A PRODUCCION
cd /d "%~dp0"
python desplegar_seguro.py %*
echo.
pause
