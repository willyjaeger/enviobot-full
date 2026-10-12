@echo off
chcp 65001 >nul
echo ======================================================================
echo    ENVIOBOT FULL - INSTALADOR DE ACCESO DIRECTO EN ESCRITORIO
echo ======================================================================
echo.
echo Creando acceso directo en el escritorio de Windows...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath('Desktop'); $shortcutPath = [System.IO.Path]::Combine($desktop, 'EnvioBot Full.lnk'); $chrome = '${env:ProgramFiles}\Google\Chrome\Application\chrome.exe'; if (-not (Test-Path $chrome)) { $chrome = '${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe' }; if (-not (Test-Path $chrome)) { $chrome = '${env:LocalAppData}\Google\Chrome\Application\chrome.exe' }; if (-not (Test-Path $chrome)) { $chrome = '${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe' }; $s = $ws.CreateShortcut($shortcutPath); $s.TargetPath = $chrome; $s.Arguments = '--app=https://enviobot.com.ar/full/ --start-maximized'; $s.Description = 'EnvioBot Full'; $s.Save(); Write-Host 'Acceso directo creado exitosamente en:' $shortcutPath"

echo.
echo Acceso directo creado con exito en tu escritorio.
timeout /t 3 >nul
