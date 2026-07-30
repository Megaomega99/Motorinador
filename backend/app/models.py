from __future__ import annotations

import time
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

# Límites de velocidad — espejo de RPM_MIN/RPM_MAX/RPM_STEP en src/main.cpp.
# Única fuente de verdad del backend: los clientes no pueden modificarlos.
RPM_MIN = 1.0
RPM_MAX = 120.0
RPM_STEP = 1.0

# Relación de la transmisión: vueltas de ENCODER por vuelta de MOTOR.
# Espejo de GEAR_RATIO en src/main.cpp. Medido 1.986 sobre la toma
# `intento serio 2_260729_142804` (el nominal supuesto era 2.1, un 6 % alto).
GEAR_RATIO = 1.986


class StatusFrame(BaseModel):
    """Estado del motor tal y como lo reporta el firmware (1 Hz).

    Tres velocidades, todas en RPM y con el signo indicando la dirección:
      · ``target_rpm``  consigna del MOTOR (se convierte en tren de pasos)
      · ``motor_rpm``   motor MEDIDO = encoder ÷ gear_ratio → comparable con la consigna
      · ``enc_rpm``     encoder en bruto (gira ``gear_ratio`` veces más rápido)

    ``slip_pct`` es la diferencia relativa entre consigna y motor medido: delata
    pasos perdidos o un atasco. No hay lazo cerrado — ver la nota de src/main.cpp.
    """

    target_rpm: float
    motor_rpm: float
    enc_rpm: float
    angle_deg: float
    dir: Literal["FWD", "REV"]
    running: bool
    ts: float = Field(default_factory=time.time)
    omega_rad_s: Optional[float] = None
    v_m_s: Optional[float] = None
    slip_pct: Optional[float] = None


class Params(BaseModel):
    """Parámetros mecánicos. Se validan aquí, en el borde del sistema, para que
    las dos vías (REST y WebSocket) queden cubiertas por la misma regla."""

    radius_cm: float = Field(default=12.0, gt=0)
    steps_per_rev: int = Field(default=200, gt=0)
    microsteps: int = Field(default=8, gt=0)
    enc_ppr: int = Field(default=600, gt=0)
    debounce_us: int = Field(default=50, ge=0)
    gear_ratio: float = Field(default=GEAR_RATIO, gt=0)
    rpm_min: float = RPM_MIN
    rpm_max: float = RPM_MAX
    rpm_step: float = RPM_STEP


# WebSocket messages: backend → client

class WsStatus(BaseModel):
    type: Literal["status"] = "status"
    data: StatusFrame


class WsLog(BaseModel):
    type: Literal["log"] = "log"
    level: Literal["info", "warn", "error"] = "info"
    msg: str
    ts: float = Field(default_factory=time.time)


class WsParams(BaseModel):
    type: Literal["params"] = "params"
    data: Params


class WsReady(BaseModel):
    type: Literal["ready"] = "ready"
    firmware: str = "NEMA17 + TMC2208 + ENCODER (lazo abierto)"


class WsError(BaseModel):
    type: Literal["error"] = "error"
    msg: str


WsMessage = Union[WsStatus, WsLog, WsParams, WsReady, WsError]


# WebSocket messages: client → backend

class CmdMessage(BaseModel):
    type: Literal["cmd"] = "cmd"
    cmd: Literal[
        "start", "stop", "e_stop", "zero_encoder",
        "dir_fwd", "dir_rev",
    ]


class SetTargetMessage(BaseModel):
    type: Literal["set_target"] = "set_target"
    rpm: float = Field(ge=RPM_MIN, le=RPM_MAX)


class SetParamsMessage(BaseModel):
    type: Literal["set_params"] = "set_params"
    data: Params
