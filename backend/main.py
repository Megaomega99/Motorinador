"""Punto de entrada del programa: levanta el servidor que sirve la interfaz.

Se arranca con `python backend/main.py`, o con un doble clic en
`Motorinador.bat` (Windows) / `./motorinador.sh` (Linux, macOS), que además
comprueban Python y las dependencias.

Variables de entorno útiles:
  MOTORINADOR_HOST    interfaz de escucha (por defecto 127.0.0.1, solo local)
  MOTORINADOR_HTTP_PORT  puerto (por defecto 8000)
  MOTORINADOR_RELOAD  "1" para recargar al editar código (desarrollo)
  MOTORINADOR_PORT    puerto serial del Arduino, o "off" para no usarlo
  MOTORINADOR_ANALYSIS_ROOT  carpeta desde la que se pueden abrir grabaciones
"""

import os
import sys

import uvicorn

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# La raíz del repo hace falta para importar el paquete `analysis` (motor de
# cálculo de la pestaña de análisis offline).
REPO_ROOT = os.path.dirname(BACKEND_DIR)

# Ambos al PYTHONPATH para que el subprocess de reload también los herede
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, REPO_ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [BACKEND_DIR, REPO_ROOT, os.environ.get("PYTHONPATH", "")]
)

# Escucha solo en local por defecto: la API no tiene autenticación y permite
# leer grabaciones del disco, así que no debe quedar expuesta a la red del
# laboratorio sin que alguien lo pida explícitamente.
HOST = os.environ.get("MOTORINADOR_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("MOTORINADOR_HTTP_PORT", "8000"))
# La recarga automática solo sirve para desarrollar: vigila archivos y duplica
# el proceso, así que viene desactivada.
RELOAD = os.environ.get("MOTORINADOR_RELOAD", "") in {"1", "true", "True", "yes"}


def main() -> None:
    print(f"  Servidor en http://{HOST}:{HTTP_PORT}", flush=True)
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=HTTP_PORT,
        reload=RELOAD,
        reload_dirs=[BACKEND_DIR] if RELOAD else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
