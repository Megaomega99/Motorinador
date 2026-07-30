@echo off
REM ============================================================================
REM  Motorinador - arranque de un doble clic en Windows
REM
REM  No hace falta instalar nada a mano ni abrir una terminal: este archivo
REM  busca Python, instala las dependencias la primera vez, levanta el servidor
REM  y abre el navegador.
REM
REM  Deliberadamente es un .bat y no un .ps1: PowerShell bloquea los scripts sin
REM  firmar por defecto ("ExecutionPolicy") y eso obligaba a tocar la politica
REM  del sistema antes de poder usar el programa.
REM ============================================================================
setlocal EnableDelayedExpansion
title Motorinador
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     MOTORINADOR   -   Control del motor y analisis de datos
echo   ==========================================================
echo.

REM --------------------------------------------------------------------------
REM  1. Buscar un Python utilizable
REM --------------------------------------------------------------------------
set "PYCMD="

REM El lanzador "py" viene con el instalador oficial de Python: es lo mas fiable.
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"

if not defined PYCMD (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)

REM Instalaciones habituales de Anaconda/Miniconda o Python que no estan en PATH.
if not defined PYCMD (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%USERPROFILE%\miniconda3\python.exe"
        "%USERPROFILE%\anaconda3\python.exe"
        "%USERPROFILE%\miniforge3\python.exe"
        "C:\ProgramData\miniconda3\python.exe"
        "C:\ProgramData\anaconda3\python.exe"
        "C:\ProgramData\miniforge3\python.exe"
    ) do (
        if not defined PYCMD if exist %%P set "PYCMD=%%P"
    )
)

if not defined PYCMD (
    echo   [ERROR] No se encontro Python en este equipo.
    echo.
    echo   Instala Python 3.11 o superior desde https://www.python.org/downloads/
    echo   y marca la casilla "Add python.exe to PATH" durante la instalacion.
    echo   Despues vuelve a hacer doble clic en este archivo.
    echo.
    pause
    exit /b 1
)

REM La version se lee via archivo temporal: un `for /f` cuyo comando empieza por
REM comilla (la ruta de conda) lo malinterpreta CMD.
set "PYVER=?"
%PYCMD% -c "import sys;print(sys.version.split()[0])" > "%TEMP%\motorinador_pyver.txt" 2>nul
if exist "%TEMP%\motorinador_pyver.txt" set /p PYVER=<"%TEMP%\motorinador_pyver.txt"
del "%TEMP%\motorinador_pyver.txt" >nul 2>&1
echo   Python !PYVER! encontrado.

REM El codigo usa `match` y anotaciones `X | None` evaluadas en tiempo de
REM ejecucion: por debajo de 3.10 no arranca, y el error seria incomprensible.
%PYCMD% -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [ERROR] Se necesita Python 3.10 o superior ^(este es !PYVER!^).
    echo   Instala una version reciente desde https://www.python.org/downloads/
    echo   y marca "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM --------------------------------------------------------------------------
REM  2. Comprobar dependencias (solo instala si falta algo)
REM --------------------------------------------------------------------------
%PYCMD% -c "import fastapi, uvicorn, serial, numpy, pandas, h5py, neo" >nul 2>&1
if errorlevel 1 (
    echo   Faltan dependencias. Instalando ^(solo la primera vez, puede tardar^)...
    echo.
    %PYCMD% -m pip install --upgrade pip >nul 2>&1
    %PYCMD% -m pip install -r "backend\requirements.txt"
    if errorlevel 1 (
        echo.
        echo   [ERROR] La instalacion de dependencias fallo.
        echo   Revisa tu conexion a internet y vuelve a intentarlo.
        echo   Si usas Anaconda, prueba en su terminal:
        echo       pip install -r backend\requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   Dependencias instaladas.
) else (
    echo   Dependencias correctas.
)

REM --------------------------------------------------------------------------
REM  3. Abrir el navegador con un retraso, para que el servidor ya responda
REM --------------------------------------------------------------------------
echo.
echo   Abriendo http://127.0.0.1:8000 en el navegador...
REM Se lanza en una ventana aparte con un retraso, para que el servidor ya
REM responda cuando el navegador pida la pagina. Sin comillas anidadas: mezclar
REM start "" dentro de cmd /c "..." rompe el parseo de comillas de CMD.
start /min "" cmd /c timeout /t 4 /nobreak ^>nul ^& start http://127.0.0.1:8000

REM --------------------------------------------------------------------------
REM  4. Arrancar el servidor en esta ventana (cerrarla detiene el programa)
REM --------------------------------------------------------------------------
echo.
echo   ----------------------------------------------------------
echo    El programa esta corriendo. NO CIERRES esta ventana.
echo    Para detenerlo: cierra la ventana o pulsa Ctrl+C.
echo.
echo    Si no tienes el Arduino conectado no pasa nada: la pestana
echo    "Analisis de grabaciones" funciona igual.
echo   ----------------------------------------------------------
echo.

%PYCMD% "backend\main.py"

REM Si el servidor termina (error o Ctrl+C), dejar el mensaje a la vista.
echo.
echo   El programa se ha detenido.
pause
