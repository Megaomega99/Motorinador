"""Tests for the serial line parser."""
import pytest
from app.serial_link import _parse_line


VALID_LINES = [
    (
        "Target: 30.0 RPM  |  Real: 29.8 RPM  |  Ang: 142.3 deg  |  Dir: FWD  |  CORRIENDO",
        dict(target_rpm=30.0, real_rpm=29.8, angle_deg=142.3, dir="FWD", running=True),
    ),
    (
        "Target: 5.0 RPM  |  Real: 5.0 RPM  |  Ang: 0.0 deg  |  Dir: REV  |  PARADO",
        dict(target_rpm=5.0, real_rpm=5.0, angle_deg=0.0, dir="REV", running=False),
    ),
    (
        "Target: 120.0 RPM  |  Real: 119.5 RPM  |  Ang: 359.9 deg  |  Dir: FWD  |  CORRIENDO",
        dict(target_rpm=120.0, real_rpm=119.5, angle_deg=359.9, dir="FWD", running=True),
    ),
    (
        "Target:  30.0 RPM  |  Real:  -0.1 RPM  |  Ang:  0.0 deg  |  Dir: FWD  |  PARADO",
        dict(target_rpm=30.0, real_rpm=-0.1, angle_deg=0.0, dir="FWD", running=False),
    ),
    (
        "Target: 75.0 RPM  |  Real: 74.9 RPM  |  Ang: 270.5 deg  |  Dir: REV  |  CORRIENDO",
        dict(target_rpm=75.0, real_rpm=74.9, angle_deg=270.5, dir="REV", running=True),
    ),
]

INVALID_LINES = [
    "===  NEMA17 + TMC2208 + ENCODER  ===",
    "Encoder -> 0",
    "Comandos: '+' subir  '-' bajar  'r' girar  's' parar  'z' zero",
    "",
    "Target: 30 RPM",  # incomplete
    "some garbage line",
]


@pytest.mark.parametrize("line,expected", VALID_LINES)
def test_parse_valid(line: str, expected: dict) -> None:
    frame = _parse_line(line)
    assert frame is not None
    assert frame.target_rpm == pytest.approx(expected["target_rpm"])
    assert frame.real_rpm == pytest.approx(expected["real_rpm"])
    assert frame.angle_deg == pytest.approx(expected["angle_deg"])
    assert frame.dir == expected["dir"]
    assert frame.running == expected["running"]


@pytest.mark.parametrize("line", INVALID_LINES)
def test_parse_invalid_returns_none(line: str) -> None:
    assert _parse_line(line) is None


def test_parse_sets_timestamp() -> None:
    line = "Target: 30.0 RPM  |  Real: 29.8 RPM  |  Ang: 10.0 deg  |  Dir: FWD  |  CORRIENDO"
    frame = _parse_line(line)
    assert frame is not None
    assert frame.ts > 0
