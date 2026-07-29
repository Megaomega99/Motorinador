@echo off
REM Wrapper para ejecutar run_backend.ps1 desde el Explorador con doble clic
REM Ejecuta el script PowerShell con política temporal Bypass
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_backend.ps1"
pause
