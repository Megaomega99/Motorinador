"""Tests del protocolo serial y de la validación de la API.

No requieren hardware: el puerto serial se sustituye por un escritor falso.
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import get_args

import pytest
from pydantic import ValidationError

from app.models import (
    GEAR_RATIO,
    RPM_MAX,
    RPM_MIN,
    RPM_STEP,
    CmdMessage,
    Params,
    SetTargetMessage,
    StatusFrame,
)
from app.routes.control import TargetPayload, post_cmd, update_params
from app.routes.ws import _handle_client_message
from app.serial_link import SerialLink, _enrich, _parse_line, serial_link
from app.state import motor_state


# ── _parse_line ──────────────────────────────────────────────────


def test_parse_line_running() -> None:
    line = "Tgt:30.0RPM  Mot:29.8RPM  Enc:59.2RPM  Ang:185.4deg  Dir:FWD  CORRIENDO"
    frame = _parse_line(line)
    assert frame is not None
    assert frame.target_rpm == 30.0
    assert frame.motor_rpm == 29.8
    assert frame.enc_rpm == 59.2
    assert frame.angle_deg == 185.4
    assert frame.dir == "FWD"
    assert frame.running is True


def test_parse_line_negative_parado() -> None:
    """El signo de las velocidades codifica la dirección."""
    line = "Tgt:15.0RPM  Mot:-7.4RPM  Enc:-14.8RPM  Ang:0.0deg  Dir:REV  PARADO"
    frame = _parse_line(line)
    assert frame is not None
    assert frame.target_rpm == 15.0
    assert frame.motor_rpm == -7.4
    assert frame.enc_rpm == -14.8
    assert frame.dir == "REV"
    assert frame.running is False


def test_parse_line_garbage_returns_none() -> None:
    assert _parse_line("E-STOP") is None
    assert _parse_line("Encoder -> 0") is None
    assert _parse_line("") is None


def test_parse_line_ignores_old_pi_format() -> None:
    """El formato antiguo con [PI]/[LIBRE] ya no existe: no debe colarse."""
    old_pi = "[PI]  Tgt:30.0RPM  Meas:28.5RPM  Err:1.5  Ctrl:30.2RPM  Ang:1.0deg  Dir:FWD  CORRIENDO"
    old_libre = "[LIBRE]  Tgt:15.0RPM  Real:-14.8RPM  Ang:0.0deg  Dir:REV  PARADO"
    assert _parse_line(old_pi) is None
    assert _parse_line(old_libre) is None


# ── _enrich: velocidad lineal y deslizamiento ────────────────────


def _frame(**kw) -> StatusFrame:
    base = dict(target_rpm=10.0, motor_rpm=10.0, enc_rpm=10.0 * GEAR_RATIO,
                angle_deg=0.0, dir="FWD", running=True)
    base.update(kw)
    return StatusFrame(**base)


def test_enrich_uses_motor_speed_for_linear_velocity() -> None:
    """La rueda va en el eje del motor, no en el del encoder."""
    params = Params(radius_cm=100.0)          # r = 1 m → v = ω
    out = _enrich(_frame(motor_rpm=60.0), params)
    assert out.omega_rad_s == pytest.approx(2 * math.pi, rel=1e-3)
    assert out.v_m_s == pytest.approx(2 * math.pi, rel=1e-3)


def test_enrich_reports_zero_slip_when_motor_follows() -> None:
    out = _enrich(_frame(target_rpm=10.0, motor_rpm=10.0), Params())
    assert out.slip_pct == 0.0


def test_enrich_reports_slip_when_steps_are_lost() -> None:
    out = _enrich(_frame(target_rpm=10.0, motor_rpm=8.0), Params())
    assert out.slip_pct == pytest.approx(20.0)


def test_enrich_slip_is_clamped_and_uses_magnitude() -> None:
    # Eje bloqueado → 100 %; girando más rápido de lo pedido → 0 %, no negativo.
    assert _enrich(_frame(target_rpm=10.0, motor_rpm=0.0), Params()).slip_pct == 100.0
    assert _enrich(_frame(target_rpm=10.0, motor_rpm=12.0), Params()).slip_pct == 0.0
    # En reversa la magnitud es lo que cuenta.
    assert _enrich(_frame(target_rpm=10.0, motor_rpm=-10.0), Params()).slip_pct == 0.0


def test_enrich_omits_slip_when_stopped() -> None:
    """Con el motor parado el deslizamiento no está definido."""
    out = _enrich(_frame(running=False, motor_rpm=0.0), Params())
    assert out.slip_pct is None


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
        await link.cmd_zero_encoder()

    asyncio.run(run_all())
    assert writer.data == b"10efbz"


def test_send_rejects_legacy_toggles() -> None:
    link, _ = _linked_fake()
    for legacy in ("s", "r", "c"):
        with pytest.raises(ValueError):
            asyncio.run(link.send(legacy))


def test_send_rejects_retired_pi_mode_commands() -> None:
    """'p'/'l' (modo PI) se retiraron del firmware: el backend no debe emitirlos."""
    link, _ = _linked_fake()
    for retired in ("p", "l"):
        with pytest.raises(ValueError):
            asyncio.run(link.send(retired))


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


def test_gear_ratio_defaults_to_the_measured_value() -> None:
    assert Params().gear_ratio == GEAR_RATIO


def test_update_params_accepts_a_new_gear_ratio() -> None:
    original = motor_state.params
    try:
        result = asyncio.run(update_params(Params(gear_ratio=2.1)))
        assert result.gear_ratio == 2.1
    finally:
        motor_state.params = original


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_non_positive_gear_ratio_rejected(bad: float) -> None:
    """Un gear_ratio de 0 dividiría por cero al referir el encoder al motor."""
    with pytest.raises(ValidationError):
        Params(gear_ratio=bad)


@pytest.mark.parametrize("bad", [0.0, -3.0])
def test_non_positive_radius_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        Params(radius_cm=bad)


def test_ws_set_params_updates_gear_ratio(fake_serial) -> None:
    original = motor_state.params
    try:
        payload = {"type": "set_params",
                   "data": {**Params().model_dump(), "gear_ratio": 2.05}}
        asyncio.run(_handle_client_message(json.dumps(payload)))
        assert motor_state.params.gear_ratio == 2.05
        # Los límites de RPM siguen siendo del servidor.
        assert motor_state.params.rpm_max == RPM_MAX
    finally:
        motor_state.params = original


def test_ws_set_params_rejects_bad_gear_ratio(fake_serial) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(_handle_client_message(json.dumps(
            {"type": "set_params", "data": {**Params().model_dump(), "gear_ratio": 0}}
        )))
