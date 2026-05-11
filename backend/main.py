import os
import sys
import uvicorn

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Agrega backend/ al PYTHONPATH para que el subprocess de reload también lo herede
sys.path.insert(0, BACKEND_DIR)
os.environ["PYTHONPATH"] = BACKEND_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[BACKEND_DIR],
    )
