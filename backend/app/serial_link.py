from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from typing import Optional

import serial_asyncio

from .config import settings
from .models import Params, StatusFrame, WsError, WsReady, WsStatus
from .state import motor_state

logger = logging.getLogger(__name__)

_STATUS_RE = re.compile(
    r"Target:\s*([-+]?\d+\.?\d*)\s*RPM\s*\|\s*"
    r"Real:\s*([-+]?\d+\.?\d*)\s*RPM\s*\|\s*"
    r"Ang:\s*([-+]?\d+\.?\d*)\s*deg\s*\|\s*"
    r"Dir:\s*(FWD|REV)\s*\|\s*"
    r"(CORRIENDO|PARADO)"
)

VALID_CMDS = frozenset({"+", "-", "r", "s", "z"})


def _parse_line(line: str) -> Optional[StatusFrame]:
    m = _STATUS_RE.search(line)
    if not m:
        return None
    return StatusFrame(
        target_rpm=float(m.group(1)),
        real_rpm=float(m.group(2)),
        angle_deg=float(m.group(3)),
        dir=m.group(4),
        running=m.group(5) == "CORRIENDO",
        ts=time.time(),
    )


def _enrich(frame: StatusFrame, params: Params) -> StatusFrame:
    omega = frame.real_rpm * 2 * math.pi / 60
    v = omega * (params.radius_cm / 100.0)
    return frame.model_copy(update={"omega_rad_s": round(omega, 4), "v_m_s": round(v, 4)})


class SerialLink:
    def __init__(self) -> None:
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._cmd_lock = asyncio.Lock()
        self._last_target: float = 30.0
        self._pending_target: Optional[float] = None
        self._debounce_task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ── lifecycle ──────────────────────────────────────────────

    async def run(self) -> None:
        while True:
            try:
                await self._connect_and_read()
            except Exception as exc:
                logger.warning("Serial error: %s — retrying in %.1fs", exc, settings.serial_reconnect_interval)
                self._connected = False
                await motor_state.broadcast(WsError(msg=f"Serial port disconnected: {exc}"))
                await asyncio.sleep(settings.serial_reconnect_interval)

    async def _connect_and_read(self) -> None:
        logger.info("Opening serial port %s @ %d baud", settings.port, settings.baud)
        reader, writer = await serial_asyncio.open_serial_connection(
            url=settings.port, baudrate=settings.baud
        )
        self._writer = writer
        # Wait for Arduino reset after USB connect
        await asyncio.sleep(2.0)
        self._connected = True
        await motor_state.broadcast(WsReady())
        await motor_state.log_info(f"Serial abierto: {settings.port} @ {settings.baud}")

        try:
            while True:
                raw = await reader.readline()
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                await self._handle_line(line)
        finally:
            self._connected = False
            writer.close()
            self._writer = None

    async def _handle_line(self, line: str) -> None:
        frame = _parse_line(line)
        if frame:
            frame = _enrich(frame, motor_state.params)
            motor_state.last_status = frame
            self._last_target = frame.target_rpm   # siempre en sync con el firmware
            await motor_state.broadcast(WsStatus(data=frame))
        else:
            level = "warn" if "error" in line.lower() else "info"
            await motor_state.log(line, level)

    # ── command sending ────────────────────────────────────────

    async def send(self, cmd: str) -> None:
        if cmd not in VALID_CMDS:
            raise ValueError(f"Invalid command: {cmd!r}")
        if self._writer is None:
            raise RuntimeError("Serial port not connected")
        async with self._cmd_lock:
            self._writer.write(cmd.encode("ascii"))
            await self._writer.drain()

    async def set_target_rpm(self, target: float) -> None:
        params = motor_state.params
        step = params.rpm_step if params.rpm_step > 0 else 5.0
        target = max(params.rpm_min, min(params.rpm_max, target))
        steps = round((target - self._last_target) / step)
        if steps == 0:
            return
        cmd = "+" if steps > 0 else "-"
        for _ in range(abs(steps)):
            await self.send(cmd)
            await asyncio.sleep(0.02)
        self._last_target = self._last_target + steps * step

    def schedule_set_target(self, target: float) -> None:
        self._pending_target = target
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounced_set_target())

    async def _debounced_set_target(self) -> None:
        await asyncio.sleep(settings.ws_rate_limit_ms / 1000.0)
        if self._pending_target is not None:
            try:
                await self.set_target_rpm(self._pending_target)
            except Exception as exc:
                logger.error("set_target_rpm failed: %s", exc)
            finally:
                self._pending_target = None

    # ── high-level commands ────────────────────────────────────

    async def cmd_toggle(self) -> None:
        await self.send("s")

    async def cmd_start(self) -> None:
        status = motor_state.last_status
        # Si no hay status aún, asume parado y envía toggle
        if status is None or not status.running:
            await self.send("s")

    async def cmd_stop(self) -> None:
        status = motor_state.last_status
        # Si no hay status aún, asume corriendo y envía toggle
        if status is None or status.running:
            await self.send("s")

    async def cmd_e_stop(self) -> None:
        # E-STOP es sagrado: para siempre, sin importar el estado conocido
        status = motor_state.last_status
        if status is None or status.running:
            await self.send("s")

    async def cmd_reverse(self) -> None:
        await self.send("r")

    async def cmd_zero_encoder(self) -> None:
        await self.send("z")


serial_link = SerialLink()
