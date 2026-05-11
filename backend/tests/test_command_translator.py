"""Tests for the RPM command translator (set_target_rpm logic)."""
import pytest
from unittest.mock import AsyncMock, patch


def _expected_cmds(from_rpm: float, to_rpm: float, step: float = 5.0) -> list[str]:
    steps = round((to_rpm - from_rpm) / step)
    return ["+" if steps > 0 else "-"] * abs(steps)


@pytest.mark.parametrize("from_rpm,to_rpm,expected_cmds", [
    (30.0, 75.0, ["+"] * 9),
    (75.0, 30.0, ["-"] * 9),
    (30.0, 30.0, []),
    (5.0, 10.0, ["+"]),
    (120.0, 115.0, ["-"]),
    (30.0, 55.0, ["+"] * 5),
])
def test_expected_cmds_count(from_rpm: float, to_rpm: float, expected_cmds: list[str]) -> None:
    result = _expected_cmds(from_rpm, to_rpm)
    assert result == expected_cmds


@pytest.mark.asyncio
async def test_set_target_sends_correct_cmds() -> None:
    from app.serial_link import SerialLink
    from app.state import MotorState

    link = SerialLink()
    link._last_target = 30.0

    sent: list[str] = []

    async def fake_send(cmd: str) -> None:
        sent.append(cmd)

    link.send = fake_send

    import app.serial_link as sl
    original_state = sl.motor_state
    mock_state = MotorState()
    sl.motor_state = mock_state

    try:
        await link.set_target_rpm(75.0)
        assert sent == ["+"] * 9
    finally:
        sl.motor_state = original_state


@pytest.mark.asyncio
async def test_set_target_clamps_to_max() -> None:
    from app.serial_link import SerialLink
    from app.state import MotorState

    link = SerialLink()
    link._last_target = 115.0

    sent: list[str] = []

    async def fake_send(cmd: str) -> None:
        sent.append(cmd)

    link.send = fake_send

    import app.serial_link as sl
    mock_state = MotorState()
    sl.motor_state = mock_state

    try:
        await link.set_target_rpm(200.0)  # clamp to 120
        assert sent == ["+"]
    finally:
        sl.motor_state = mock_state
