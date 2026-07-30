from __future__ import annotations

from typing import get_args

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models import RPM_MAX, RPM_MIN, RPM_STEP, CmdMessage, Params, StatusFrame
from ..port_detector import list_serial_ports
from ..serial_link import serial_link
from ..state import motor_state

router = APIRouter(prefix="/api")

# Derivado del Literal de CmdMessage: una sola fuente de verdad para
# los nombres de comando de la API (REST y WebSocket).
VALID_CMDS = frozenset(get_args(CmdMessage.model_fields["cmd"].annotation))


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
    # Los rangos válidos los impone el propio modelo (ver Params).
    # Los límites de RPM son propiedad del servidor (espejo del firmware):
    # se ignora cualquier valor enviado por el cliente.
    motor_state.params = params.model_copy(
        update={"rpm_min": RPM_MIN, "rpm_max": RPM_MAX, "rpm_step": RPM_STEP}
    )
    return motor_state.params


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
        case "e_stop":
            await serial_link.cmd_e_stop()
        case "zero_encoder":
            await serial_link.cmd_zero_encoder()
        case "dir_fwd":
            await serial_link.cmd_set_direction(forward=True)
        case "dir_rev":
            await serial_link.cmd_set_direction(forward=False)
    return {"ok": True, "cmd": cmd}


class TargetPayload(BaseModel):
    rpm: float = Field(ge=RPM_MIN, le=RPM_MAX)


@router.post("/target")
async def set_target(payload: TargetPayload) -> dict:
    if not serial_link.connected:
        raise HTTPException(status_code=503, detail="Serial port not connected")
    await serial_link.set_target_rpm(payload.rpm)
    return {"ok": True, "rpm": payload.rpm}
