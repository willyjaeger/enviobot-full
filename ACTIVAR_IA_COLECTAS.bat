@echo off
chcp 65001 > nul
title ACTIVAR IA GEMINI - ENVIOBOT FULL
cd /d "%~dp0"
python herramientas\activar_ia_gemini.py
echo.
pause
