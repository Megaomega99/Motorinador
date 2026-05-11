from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOTORINADOR_")

    port: str = "/dev/ttyACM0"
    baud: int = 115200
    serial_reconnect_interval: float = 2.0
    ws_rate_limit_ms: int = 100        # debounce RPM commands
    log_buffer_size: int = 200         # circular log kept for late-joiners
    allow_origins: list[str] = ["*"]


settings = Settings()
