from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..models import (
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


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    q = motor_state.add_client()

    # Send buffered log to late-joining client
    for entry in motor_state.get_log_buffer():
        await ws.send_text(json.dumps(entry))

    # Send current params and status if available
    await ws.send_text(WsParams(data=motor_state.params).model_dump_json())
    if motor_state.last_status:
        await ws.send_text(WsStatus(data=motor_state.last_status).model_dump_json())
    if serial_link.connected:
        await ws.send_text(WsReady().model_dump_json())
    else:
        await ws.send_text(WsError(msg="Serial port not connected").model_dump_json())

    drain_task = asyncio.create_task(_drain(ws, q))

    try:
        while True:
            raw = await ws.receive_text()
            await _handle_client_message(raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error: %s", exc)
    finally:
        drain_task.cancel()
        motor_state.remove_client(q)


async def _handle_client_message(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    msg_type = data.get("type")

    if msg_type == "cmd":
        msg = CmdMessage.model_validate(data)
        match msg.cmd:
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

    elif msg_type == "set_target":
        msg = SetTargetMessage.model_validate(data)
        serial_link.schedule_set_target(msg.rpm)

    elif msg_type == "set_params":
        msg = SetParamsMessage.model_validate(data)
        motor_state.params = msg.data
        await motor_state.broadcast(WsParams(data=motor_state.params))
