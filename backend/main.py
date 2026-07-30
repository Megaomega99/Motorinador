import os
import sys
import uvicorn

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# La raíz del repo hace falta para importar el paquete `analysis` (motor de la
# vista de análisis offline, compartido con la app de escritorio).
REPO_ROOT = os.path.dirname(BACKEND_DIR)

# Ambos al PYTHONPATH para que el subprocess de reload también los herede
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, REPO_ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [BACKEND_DIR, REPO_ROOT, os.environ.get("PYTHONPATH", "")]
)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[BACKEND_DIR],
    )
