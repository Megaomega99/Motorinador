from __future__ import annotations

import time
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

# Límites de velocidad — espejo de RPM_MIN/RPM_MAX/RPM_STEP en src/main.cpp.
# Única fuente de verdad del backend: los clientes no pueden modificarlos.
RPM_MIN = 1.0
RPM_MAX = 120.0
RPM_STEP = 1.0


class StatusFrame(BaseModel):
    target_rpm: float
    real_rpm: float
    angle_deg: float
    dir: Literal["FWD", "REV"]
    running: bool
    ts: float = Field(default_factory=time.time)
    omega_rad_s: Optional[float] = None
    v_m_s: Optional[float] = None
    # Controlador PI
    use_pid: bool = False
    measured_rpm: Optional[float] = None
    pi_error: Optional[float] = None
    control_rpm: Optional[float] = None


class Params(BaseModel):
    radius_cm: float = 12.0
    steps_per_rev: int = 200
    microsteps: int = 8
    enc_ppr: int = 600
    debounce_us: int = 50
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
    firmware: str = "NEMA17 + TMC2208 + ENCODER + PI"


class WsError(BaseModel):
    type: Literal["error"] = "error"
    msg: str


WsMessage = Union[WsStatus, WsLog, WsParams, WsReady, WsError]


# WebSocket messages: client → backend

class CmdMessage(BaseModel):
    type: Literal["cmd"] = "cmd"
    cmd: Literal[
        "start", "stop", "e_stop", "zero_encoder",
        "dir_fwd", "dir_rev", "mode_pi", "mode_libre",
    ]


class SetTargetMessage(BaseModel):
    type: Literal["set_target"] = "set_target"
    rpm: float = Field(ge=RPM_MIN, le=RPM_MAX)


class SetParamsMessage(BaseModel):
    type: Literal["set_params"] = "set_params"
    data: Params
