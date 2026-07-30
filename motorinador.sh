#!/usr/bin/env bash
# =============================================================================
#  Motorinador — arranque en Linux / macOS
#
#  Equivalente a Motorinador.bat: busca Python, instala las dependencias la
#  primera vez, levanta el servidor y abre el navegador.
#
#  Uso:  ./motorinador.sh      (o doble clic, si el escritorio lo permite)
# =============================================================================
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

echo
echo "  =========================================================="
echo "    MOTORINADOR  -  Control del motor y análisis de datos"
echo "  =========================================================="
echo

# ── 1. Buscar Python ────────────────────────────────────────────────────────
PY=""
for candidate in python3 python "$HOME/miniforge3/bin/python" \
                 "$HOME/miniconda3/bin/python" "$HOME/anaconda3/bin/python"; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "  [ERROR] No se encontró Python."
    echo "  Instala Python 3.10 o superior y vuelve a ejecutar este script."
    read -rp "  Pulsa Intro para salir..." _
    exit 1
fi
PYVER="$("$PY" -c 'import sys;print(sys.version.split()[0])' 2>/dev/null || echo '?')"
echo "  Python $PYVER encontrado."

# El código usa `match` y anotaciones `X | None` evaluadas en tiempo de ejecución:
# por debajo de 3.10 no arranca, y el error sería incomprensible.
if ! "$PY" -c 'import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    echo "  [ERROR] Se necesita Python 3.10 o superior (este es $PYVER)."
    read -rp "  Pulsa Intro para salir..." _
    exit 1
fi

# ── 2. Dependencias ─────────────────────────────────────────────────────────
# Aquí NO se instala nada: en Ubuntu 23.04+ el Python del sistema está marcado
# como "externally managed" (PEP 668) y rechaza `pip install`, así que intentarlo
# solo daría un error confuso. Se comprueba y, si falta algo, se dice exactamente
# qué ejecutar. Ver la sección de Linux en el README.
if ! "$PY" -c "import fastapi, uvicorn, serial, numpy, pandas, h5py, neo" >/dev/null 2>&1; then
    echo
    echo "  [!] Faltan dependencias de Python."
    echo
    echo "  Instálalas en un entorno aislado (una sola vez):"
    echo
    echo "      python3 -m venv .venv"
    echo "      .venv/bin/pip install -r backend/requirements.txt"
    echo
    echo "  y después lanza el programa con ese entorno:"
    echo
    echo "      .venv/bin/python backend/main.py"
    echo
    echo "  Si 'python3 -m venv' falla:  sudo apt install python3-venv python3-pip"
    echo
    echo "  (Con conda/miniforge basta:  pip install -r backend/requirements.txt)"
    echo
    exit 1
fi
echo "  Dependencias correctas."

# ── 3. Abrir el navegador cuando el servidor ya responda ────────────────────
URL="http://127.0.0.1:8000"
(
    for _ in $(seq 1 40); do
        if command -v curl >/dev/null 2>&1 && curl -s -o /dev/null "$URL/healthz"; then
            break
        fi
        sleep 0.5
    done
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
    elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1
    fi
) &

# ── 4. Servidor en primer plano (Ctrl+C lo detiene) ─────────────────────────
echo
echo "  ----------------------------------------------------------"
echo "   El programa está corriendo en $URL"
echo "   Para detenerlo: Ctrl+C."
echo
echo "   Sin Arduino conectado la pestaña «Análisis de grabaciones»"
echo "   funciona igual."
echo "  ----------------------------------------------------------"
echo

exec "$PY" backend/main.py
