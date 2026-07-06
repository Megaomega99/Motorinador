"""Tests del protocolo serial y de la validación de la API.

No requieren hardware: el puerto serial se sustituye por un escritor falso.
"""
from __future__ import annotations

import asyncio
import json
from typing import get_args

import pytest
from pydantic import ValidationError

from app.models import CmdMessage, RPM_MAX, RPM_MIN, RPM_STEP, Params, SetTargetMessage
from app.routes.control import TargetPayload, post_cmd, update_params
from app.routes.ws import _handle_client_message
from app.serial_link import SerialLink, _parse_line, serial_link
from app.state import motor_state


# ── _parse_line ──────────────────────────────────────────────────


def test_parse_line_pi() -> None:
    line = "[PI]  Tgt:30.0RPM  Meas:28.5RPM  Err:1.5  Ctrl:30.2RPM  Ang:185.4deg  Dir:FWD  CORRIENDO"
    frame = _parse_line(line)
    assert frame is not None
    assert frame.use_pid is True
    assert frame.target_rpm == 30.0
    assert frame.measured_rpm == 28.5
    assert frame.pi_error == 1.5
    assert frame.control_rpm == 30.2
    assert frame.angle_deg == 185.4
    assert frame.dir == "FWD"
    assert frame.running is True


def test_parse_line_libre_negative_parado() -> None:
    line = "[LIBRE]  Tgt:15.0RPM  Real:-14.8RPM  Ang:0.0deg  Dir:REV  PARADO"
    frame = _parse_line(line)
    assert frame is not None
    assert frame.use_pid is False
    assert frame.target_rpm == 15.0
    assert frame.real_rpm == -14.8
    assert frame.dir == "REV"
    assert frame.running is False


def test_parse_line_garbage_returns_none() -> None:
    assert _parse_line("E-STOP") is None
    assert _parse_line("Modo PI ON  — lazo cerrado velocidad") is None
    assert _parse_line("") is None


# ── validación de objetivo (WS y REST unificados) ────────────────


@pytest.mark.parametrize("model", [SetTargetMessage, TargetPayload])
@pytest.mark.parametrize("rpm", [0.5, 121.0, -3.0])
def test_target_out_of_range_rejected(model, rpm: float) -> None:
    with pytest.raises(ValidationError):
        model(rpm=rpm)


@pytest.mark.parametrize("model", [SetTargetMessage, TargetPayload])
@pytest.mark.parametrize("rpm", [RPM_MIN, 37.0, RPM_MAX])
def test_target_in_range_accepted(model, rpm: float) -> None:
    assert model(rpm=rpm).rpm == rpm


# ── set_target_rpm → comando absoluto 'v<rpm>\n' ─────────────────


class _FakeWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, chunk: bytes) -> None:
        self.data.extend(chunk)

    async def drain(self) -> None:
        pass


def _linked_fake() -> tuple[SerialLink, _FakeWriter]:
    link = SerialLink()
    writer = _FakeWriter()
    link._writer = writer  # inyección directa: no hay puerto real en tests
    return link, writer


def test_set_target_rpm_sends_absolute_command() -> None:
    link, writer = _linked_fake()
    asyncio.run(link.set_target_rpm(37.0))
    assert writer.data == b"v37.0\n"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(999.0, f"v{RPM_MAX:.1f}\n"), (0.2, f"v{RPM_MIN:.1f}\n"), (-10.0, f"v{RPM_MIN:.1f}\n")],
)
def test_set_target_rpm_clamps(requested: float, expected: str) -> None:
    link, writer = _linked_fake()
    asyncio.run(link.set_target_rpm(requested))
    assert writer.data == expected.encode("ascii")


def test_set_target_rpm_disconnected_raises() -> None:
    link = SerialLink()
    with pytest.raises(RuntimeError):
        asyncio.run(link.set_target_rpm(30.0))


# ── comandos de alto nivel → caracteres absolutos ────────────────


def test_high_level_commands_send_expected_chars() -> None:
    link, writer = _linked_fake()

    async def run_all() -> None:
        await link.cmd_start()
        await link.cmd_stop()
        await link.cmd_e_stop()
        await link.cmd_set_direction(forward=True)
        await link.cmd_set_direction(forward=False)
        await link.cmd_set_mode(pid=True)
        await link.cmd_set_mode(pid=False)
        await link.cmd_zero_encoder()

    asyncio.run(run_all())
    assert writer.data == b"10efbplz"


def test_send_rejects_legacy_toggles() -> None:
    link, _ = _linked_fake()
    for legacy in ("s", "r", "c"):
        with pytest.raises(ValueError):
            asyncio.run(link.send(legacy))


# ── despacho de comandos (WS y REST) sobre el singleton ──────────

# Mapa esperado nombre-de-comando → carácter serial. Cubre TODOS los
# literales de CmdMessage: si se añade un comando y falta aquí, el test
# de completitud falla.
CMD_TO_CHAR = {
    "start": "1",
    "stop": "0",
    "e_stop": "e",
    "zero_encoder": "z",
    "dir_fwd": "f",
    "dir_rev": "b",
    "mode_pi": "p",
    "mode_libre": "l",
}


@pytest.fixture()
def fake_serial(monkeypatch):
    """Conecta el singleton serial_link a un escritor falso."""
    writer = _FakeWriter()
    monkeypatch.setattr(serial_link, "_writer", writer)
    monkeypatch.setattr(serial_link, "_connected", True)
    return writer


def test_cmd_map_covers_all_literals() -> None:
    literals = set(get_args(CmdMessage.model_fields["cmd"].annotation))
    assert literals == set(CMD_TO_CHAR)


@pytest.mark.parametrize(("cmd", "char"), sorted(CMD_TO_CHAR.items()))
def test_ws_cmd_dispatch(fake_serial, cmd: str, char: str) -> None:
    asyncio.run(_handle_client_message(json.dumps({"type": "cmd", "cmd": cmd})))
    assert fake_serial.data == char.encode("ascii")


@pytest.mark.parametrize(("cmd", "char"), sorted(CMD_TO_CHAR.items()))
def test_rest_cmd_dispatch(fake_serial, cmd: str, char: str) -> None:
    result = asyncio.run(post_cmd(cmd))
    assert result == {"ok": True, "cmd": cmd}
    assert fake_serial.data == char.encode("ascii")


def test_ws_unknown_cmd_rejected(fake_serial) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(_handle_client_message(json.dumps({"type": "cmd", "cmd": "reverse"})))
    assert fake_serial.data == b""


def test_ws_unknown_type_raises(fake_serial) -> None:
    with pytest.raises(ValueError):
        asyncio.run(_handle_client_message(json.dumps({"type": "bogus"})))


def test_ws_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(_handle_client_message("{not json"))


# ── parámetros: límites de RPM propiedad del servidor ────────────


def test_update_params_overrides_rpm_fields() -> None:
    original = motor_state.params
    try:
        client_params = Params(
            radius_cm=8.0, rpm_min=50.0, rpm_max=999.0, rpm_step=25.0
        )
        result = asyncio.run(update_params(client_params))
        assert result.radius_cm == 8.0
        assert result.rpm_min == RPM_MIN
        assert result.rpm_max == RPM_MAX
        assert result.rpm_step == RPM_STEP
        assert motor_state.params == result
    finally:
        motor_state.params = original
