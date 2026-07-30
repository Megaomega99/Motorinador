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
from .port_detector import describe_available_ports, detect_arduino_port
from .state import motor_state

logger = logging.getLogger(__name__)

# Tgt:30.0RPM  Mot:-29.8RPM  Enc:-59.2RPM  Ang:185.4deg  Dir:REV  CORRIENDO
_STATUS_RE = re.compile(
    r"Tgt:([-+]?\d+\.?\d*)RPM\s+"
    r"Mot:([-+]?\d+\.?\d*)RPM\s+"
    r"Enc:([-+]?\d+\.?\d*)RPM\s+"
    r"Ang:([-+]?\d+\.?\d*)deg\s+"
    r"Dir:(FWD|REV)\s+"
    r"(CORRIENDO|PARADO)"
)

# Comandos de un carácter aceptados por el firmware (idempotentes salvo +/-).
# '+'/'-' no los emite ningún flujo del backend hoy (la UI usa objetivos
# absolutos vía 'v'), pero se permiten por ser parte del protocolo.
# Los toggles legados 's'/'r' existen en firmware pero el backend no los usa.
VALID_CMDS = frozenset({"+", "-", "z", "0", "1", "e", "f", "b"})


def _parse_line(line: str) -> Optional[StatusFrame]:
    m = _STATUS_RE.search(line)
    if not m:
        return None
    return StatusFrame(
        target_rpm=float(m.group(1)),
        motor_rpm=float(m.group(2)),
        enc_rpm=float(m.group(3)),
        angle_deg=float(m.group(4)),
        dir=m.group(5),
        running=m.group(6) == "CORRIENDO",
        ts=time.time(),
    )


def _enrich(frame: StatusFrame, params: Params) -> StatusFrame:
    """Añade magnitudes derivadas de la velocidad **del motor**.

    La rueda va en el eje del motor (el encoder es solo instrumento, y además
    gira más rápido por los engranajes), así que la velocidad lineal se calcula
    con la RPM del motor medida. ``slip_pct`` compara consigna y medida: si el
    motor sigue el tren de pasos es ~0; si pierde pasos o se atasca, sube.
    """
    omega = frame.motor_rpm * 2 * math.pi / 60
    v = omega * (params.radius_cm / 100.0)
    update = {"omega_rad_s": round(omega, 4), "v_m_s": round(v, 4)}
    if frame.running and frame.target_rpm > 0:
        slip = (1.0 - abs(frame.motor_rpm) / frame.target_rpm) * 100.0
        update["slip_pct"] = round(max(0.0, min(100.0, slip)), 1)
    return frame.model_copy(update=update)


class SerialLink:
    def __init__(self) -> None:
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._cmd_lock = asyncio.Lock()
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

    def _resolve_port(self) -> Optional[str]:
        """Resuelve el puerto a usar: detección automática o puerto fijo."""
        configured = settings.port.strip()
        if configured.lower() in {"", "auto"}:
            return detect_arduino_port()
        return detect_arduino_port(preferred=configured)

    async def _connect_and_read(self) -> None:
        port = self._resolve_port()
        if not port:
            available = describe_available_ports()
            raise RuntimeError(
                f"No se detectó ningún Arduino. Puertos disponibles: {available}. "
                "Conecta el Arduino por USB o define MOTORINADOR_PORT con el puerto correcto."
            )

        logger.info("Opening serial port %s @ %d baud", port, settings.baud)
        reader, writer = await serial_asyncio.open_serial_connection(
            url=port, baudrate=settings.baud
        )
        self._writer = writer
        # Wait for Arduino reset after USB connect
        await asyncio.sleep(2.0)
        self._connected = True
        await motor_state.broadcast(WsReady())
        await motor_state.log_info(f"Serial abierto: {port} @ {settings.baud}")

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
        """Envía el objetivo absoluto al firmware con el comando 'v<rpm>\\n'."""
        params = motor_state.params
        clamped = max(params.rpm_min, min(params.rpm_max, target))
        if self._writer is None:
            raise RuntimeError("Serial port not connected")
        async with self._cmd_lock:
            self._writer.write(f"v{clamped:.1f}\n".encode("ascii"))
            await self._writer.drain()

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
    # Todos son absolutos e idempotentes en firmware: no hace falta
    # (ni conviene) consultar el último estado, que llega a 1 Hz.

    async def cmd_start(self) -> None:
        await self.send("1")

    async def cmd_stop(self) -> None:
        await self.send("0")

    async def cmd_e_stop(self) -> None:
        await self.send("e")

    async def cmd_set_direction(self, forward: bool) -> None:
        await self.send("f" if forward else "b")

    async def cmd_zero_encoder(self) -> None:
        await self.send("z")



serial_link = SerialLink()
