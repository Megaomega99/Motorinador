import pathlib

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo: backend/app/config.py → backend/app → backend → Motorinador
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOTORINADOR_")

    # "auto" → detección automática multiplataforma (Linux/Windows/Mac).
    # También se puede fijar un puerto concreto (ej. "/dev/ttyACM0", "COM3", "/dev/cu.usbmodem14101").
    port: str = "auto"
    baud: int = 115200
    serial_reconnect_interval: float = 2.0
    ws_rate_limit_ms: int = 100        # debounce RPM commands
    log_buffer_size: int = 200         # circular log kept for late-joiners
    allow_origins: list[str] = ["*"]

    # ── Análisis offline ────────────────────────────────────────
    # Carpeta raíz desde la que se pueden abrir grabaciones. TODA ruta pedida por
    # un cliente se resuelve y se comprueba que caiga dentro: el navegador de
    # archivos de la API no puede salirse de aquí (ni con "..", ni con symlinks).
    # Cámbiala con MOTORINADOR_ANALYSIS_ROOT si guardas las tomas en otro sitio.
    analysis_root: str = str(_REPO_ROOT)
    # Puntos máximos por serie que devuelve la API (ya decimados en el servidor).
    analysis_max_points: int = 4000

    @property
    def analysis_root_path(self) -> pathlib.Path:
        return pathlib.Path(self.analysis_root).expanduser().resolve()


settings = Settings()
