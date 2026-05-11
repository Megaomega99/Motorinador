from __future__ import annotations

import time
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class StatusFrame(BaseModel):
    target_rpm: float
    real_rpm: float
    angle_deg: float
    dir: Literal["FWD", "REV"]
    running: bool
    ts: float = Field(default_factory=time.time)
    omega_rad_s: Optional[float] = None
    v_m_s: Optional[float] = None


class Params(BaseModel):
    radius_cm: float = 12.0
    steps_per_rev: int = 200
    microsteps: int = 8
    enc_ppr: int = 600
    debounce_us: int = 50
    rpm_min: float = 5.0
    rpm_max: float = 120.0
    rpm_step: float = 5.0


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
    firmware: str = "NEMA17 + TMC2208 + ENCODER"


class WsError(BaseModel):
    type: Literal["error"] = "error"
    msg: str


WsMessage = Union[WsStatus, WsLog, WsParams, WsReady, WsError]


# WebSocket messages: client → backend

class CmdMessage(BaseModel):
    type: Literal["cmd"] = "cmd"
    cmd: Literal["start", "stop", "reverse", "zero_encoder", "e_stop"]


class SetTargetMessage(BaseModel):
    type: Literal["set_target"] = "set_target"
    rpm: float = Field(ge=5.0, le=120.0)


class SetParamsMessage(BaseModel):
    type: Literal["set_params"] = "set_params"
    data: Params


ClientMessage = Union[CmdMessage, SetTargetMessage, SetParamsMessage]
