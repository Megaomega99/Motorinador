from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import Params, StatusFrame
from ..port_detector import list_serial_ports
from ..serial_link import serial_link
from ..state import motor_state

router = APIRouter(prefix="/api")

VALID_CMDS = frozenset({"start", "stop", "reverse", "zero_encoder", "e_stop"})


@router.get("/ports")
async def get_ports() -> dict:
    """Lista los puertos seriales disponibles para diagnóstico multiplataforma."""
    ports = [
        {
            "device": p.device,
            "description": p.description,
            "manufacturer": p.manufacturer,
            "product": p.product,
            "vid": p.vid,
            "pid": p.pid,
        }
        for p in list_serial_ports()
    ]
    return {"connected": serial_link.connected, "ports": ports}


@router.get("/state", response_model=StatusFrame)
async def get_state() -> StatusFrame:
    if motor_state.last_status is None:
        raise HTTPException(status_code=503, detail="No status available yet")
    return motor_state.last_status


@router.get("/params", response_model=Params)
async def get_params() -> Params:
    return motor_state.params


@router.put("/params", response_model=Params)
async def update_params(params: Params) -> Params:
    motor_state.params = params
    return params


@router.post("/cmd/{cmd}")
async def post_cmd(cmd: str) -> dict:
    if cmd not in VALID_CMDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {cmd!r}")
    if not serial_link.connected:
        raise HTTPException(status_code=503, detail="Serial port not connected")
    match cmd:
        case "start":
            await serial_link.cmd_start()
        case "stop":
            await serial_link.cmd_stop()
        case "reverse":
            await serial_link.cmd_reverse()
        case "zero_encoder":
            await serial_link.cmd_zero_encoder()
        case "e_stop":
            await serial_link.cmd_e_stop()
    return {"ok": True, "cmd": cmd}


class TargetPayload(BaseModel):
    rpm: float


@router.post("/target")
async def set_target(payload: TargetPayload) -> dict:
    if not serial_link.connected:
        raise HTTPException(status_code=503, detail="Serial port not connected")
    await serial_link.set_target_rpm(payload.rpm)
    return {"ok": True, "rpm": payload.rpm}
