from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Optional

from .models import Params, StatusFrame, WsLog, WsMessage


class MotorState:
    def __init__(self) -> None:
        self.last_status: Optional[StatusFrame] = None
        self.params: Params = Params()
        self._clients: set[asyncio.Queue] = set()
        self._log_buffer: deque[dict] = deque(maxlen=200)
        self._lock = asyncio.Lock()

    # ── client registry ────────────────────────────────────────

    def add_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._clients.add(q)
        return q

    def remove_client(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    def get_log_buffer(self) -> list[dict]:
        return list(self._log_buffer)

    # ── broadcast ──────────────────────────────────────────────

    async def broadcast(self, msg: WsMessage) -> None:
        raw = msg.model_dump_json()
        dead: list[asyncio.Queue] = []
        for q in list(self._clients):
            try:
                q.put_nowait(raw)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.discard(q)

        if isinstance(msg, WsLog):
            self._log_buffer.append(json.loads(raw))

    async def broadcast_raw(self, raw: str) -> None:
        dead: list[asyncio.Queue] = []
        for q in list(self._clients):
            try:
                q.put_nowait(raw)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.discard(q)

    # ── convenience log helpers ────────────────────────────────

    async def log(self, msg: str, level: str = "info") -> None:
        await self.broadcast(WsLog(msg=msg, level=level, ts=time.time()))

    async def log_info(self, msg: str) -> None:
        await self.log(msg, "info")

    async def log_warn(self, msg: str) -> None:
        await self.log(msg, "warn")

    async def log_error(self, msg: str) -> None:
        await self.log(msg, "error")


motor_state = MotorState()
