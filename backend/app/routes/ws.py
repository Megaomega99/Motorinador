from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..models import (
    RPM_MAX,
    RPM_MIN,
    RPM_STEP,
    CmdMessage,
    SetParamsMessage,
    SetTargetMessage,
    WsError,
    WsParams,
    WsReady,
    WsStatus,
)
from ..serial_link import serial_link
from ..state import motor_state

logger = logging.getLogger(__name__)
router = APIRouter()


async def _drain(ws: WebSocket, q: asyncio.Queue) -> None:
    while True:
        msg = await q.get()
        await ws.send_text(msg)


def _log_drain_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("WS drain task terminó con error: %s", exc)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    q = motor_state.add_client()

    # Enviar log buffer al cliente tardío
    for entry in motor_state.get_log_buffer():
        await ws.send_text(json.dumps(entry))

    # Estado inicial
    await ws.send_text(WsParams(data=motor_state.params).model_dump_json())
    if motor_state.last_status:
        await ws.send_text(WsStatus(data=motor_state.last_status).model_dump_json())
    if serial_link.connected:
        await ws.send_text(WsReady().model_dump_json())
    else:
        await ws.send_text(WsError(msg="Puerto serial no conectado — esperando Arduino...").model_dump_json())

    drain_task = asyncio.create_task(_drain(ws, q))
    drain_task.add_done_callback(_log_drain_failure)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                await _handle_client_message(raw)
            except Exception as exc:
                logger.error("Error handling client message %r: %s", raw[:120], exc)
                await ws.send_text(WsError(msg=f"Error procesando comando: {exc}").model_dump_json())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS loop error: %s", exc)
    finally:
        drain_task.cancel()
        motor_state.remove_client(q)


async def _handle_client_message(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc}") from exc

    msg_type = data.get("type")
    if not msg_type:
        return

    if msg_type == "cmd":
        cmd_msg = CmdMessage.model_validate(data)
        if not serial_link.connected:
            raise RuntimeError("Puerto serial no conectado")
        match cmd_msg.cmd:
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

    elif msg_type == "set_target":
        target_msg = SetTargetMessage.model_validate(data)
        if not serial_link.connected:
            raise RuntimeError("Puerto serial no conectado")
        serial_link.schedule_set_target(target_msg.rpm)

    elif msg_type == "set_params":
        # Los rangos válidos los impone el modelo Params; un valor fuera de
        # rango levanta ValidationError y el llamante lo reporta al cliente.
        params_msg = SetParamsMessage.model_validate(data)
        # Los límites de RPM son propiedad del servidor (espejo del firmware):
        # se ignora cualquier valor enviado por el cliente.
        motor_state.params = params_msg.data.model_copy(
            update={"rpm_min": RPM_MIN, "rpm_max": RPM_MAX, "rpm_step": RPM_STEP}
        )
        await motor_state.broadcast(WsParams(data=motor_state.params))

    else:
        raise ValueError(f"Tipo de mensaje desconocido: {msg_type!r}")
