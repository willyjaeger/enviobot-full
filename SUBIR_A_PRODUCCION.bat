@echo off
chcp 65001 > nul
title SUBIR A PRODUCCION - ENVIOBOT FULL
color 0B

echo ====================================================================
echo               ENVIOBOT FULL - SUBIR A PRODUCCION
echo ====================================================================
echo.
echo Repositorio: C:\Proyecto\Enviobot Full
echo Servidor:    DonWeb VPS (179.43.123.220)
echo.

cd /d "C:\Proyecto\Enviobot Full"
if errorlevel 1 (
    echo [ERROR] No se pudo acceder a C:\Proyecto\Enviobot Full
    pause
    exit /b 1
)

echo [PASO 1/2] Estado de archivos locales modificados:
echo --------------------------------------------------------------------
git status -s
echo --------------------------------------------------------------------
echo.

set /p COMMIT_MSG="Descripcion del cambio (ENTER para usar automatica): "
if "%COMMIT_MSG%"=="" (
    set COMMIT_MSG=feat: consolidacion stock fisico Full sin duplicados y restauracion de tiempo de preparacion
)

echo.
echo [PASO 2/2] Ejecutando deploy a GitHub y DonWeb VPS...
python deploy.py "%COMMIT_MSG%"

echo.
echo ====================================================================
echo    PROCESO COMPLETADO - REVISA LOS RESULTADOS ARRIBA
echo ====================================================================
echo.
pause
