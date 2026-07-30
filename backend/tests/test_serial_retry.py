"""Tests del bucle de reconexión serial: ruido de log, backoff y modo sin Arduino.

Sin placa conectada, el bucle emitía el mismo aviso cada 2 s con las 32 UART del
sistema listadas. Aquí se fija el comportamiento nuevo para que no vuelva.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.config import settings
from app.port_detector import describe_available_ports
from app.serial_link import SerialLink
from app.state import motor_state


class _Port:
    """Doble de `ListPortInfo` con lo que consultan el detector y el resumen."""

    def __init__(self, device: str, description: str = "?", vid: int | None = None):
        self.device = device
        self.description = description
        self.manufacturer = None
        self.product = None
        self.vid = vid
        self.pid = None


@pytest.fixture()
def fast_retry(monkeypatch):
    """Reintentos instantáneos y contados, para no dormir en los tests."""
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)
        # Corta el bucle infinito tras unas cuantas vueltas.
        if len(slept) >= 6:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(settings, "serial_reconnect_interval", 2.0)
    monkeypatch.setattr(settings, "serial_reconnect_max", 30.0)
    return slept


def _run(link: SerialLink) -> None:
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(link.run())


# ── el aviso no se repite ────────────────────────────────────────


def test_same_failure_warns_only_once(fast_retry, caplog, monkeypatch):
    link = SerialLink()

    async def always_fail():
        raise RuntimeError("No se detectó ningún Arduino")

    monkeypatch.setattr(link, "_connect_and_read", always_fail)
    with caplog.at_level(logging.WARNING, logger="app.serial_link"):
        _run(link)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"se repitió el aviso {len(warnings)} veces"
    assert "No se detectó ningún Arduino" in warnings[0].getMessage()


def test_a_different_failure_warns_again(fast_retry, caplog, monkeypatch):
    link = SerialLink()
    causes = iter(["sin Arduino", "sin Arduino", "permiso denegado", "permiso denegado"])

    async def failing():
        raise RuntimeError(next(causes, "permiso denegado"))

    monkeypatch.setattr(link, "_connect_and_read", failing)
    with caplog.at_level(logging.WARNING, logger="app.serial_link"):
        _run(link)

    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(msgs) == 2, msgs
    assert "sin Arduino" in msgs[0] and "permiso denegado" in msgs[1]


def test_repeated_failures_are_logged_at_debug(fast_retry, caplog, monkeypatch):
    """Silenciar no es esconder: el detalle sigue en DEBUG."""
    link = SerialLink()

    async def always_fail():
        raise RuntimeError("sin Arduino")

    monkeypatch.setattr(link, "_connect_and_read", always_fail)
    with caplog.at_level(logging.DEBUG, logger="app.serial_link"):
        _run(link)

    debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug) >= 3, "los reintentos deberían dejar rastro en DEBUG"


def test_client_is_notified_once_per_cause(fast_retry, monkeypatch):
    """El navegador tampoco debe recibir un error cada 2 s."""
    sent: list[str] = []

    async def fake_broadcast(msg):
        sent.append(getattr(msg, "msg", ""))

    monkeypatch.setattr(motor_state, "broadcast", fake_broadcast)
    link = SerialLink()

    async def always_fail():
        raise RuntimeError("sin Arduino")

    monkeypatch.setattr(link, "_connect_and_read", always_fail)
    _run(link)
    assert len(sent) == 1, f"se enviaron {len(sent)} avisos al cliente"


# ── backoff ──────────────────────────────────────────────────────


def test_delay_grows_and_is_capped(fast_retry, monkeypatch):
    link = SerialLink()

    async def always_fail():
        raise RuntimeError("sin Arduino")

    monkeypatch.setattr(link, "_connect_and_read", always_fail)
    _run(link)

    assert fast_retry[0] == 2.0
    assert fast_retry[1] == 4.0
    assert fast_retry[2] == 8.0
    assert all(d <= settings.serial_reconnect_max for d in fast_retry)
    assert fast_retry == sorted(fast_retry), "la espera debería crecer monótonamente"


def test_delay_is_capped_at_the_maximum(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)
        if len(slept) >= 12:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(settings, "serial_reconnect_interval", 2.0)
    monkeypatch.setattr(settings, "serial_reconnect_max", 10.0)
    link = SerialLink()

    async def always_fail():
        raise RuntimeError("sin Arduino")

    monkeypatch.setattr(link, "_connect_and_read", always_fail)
    _run(link)
    assert max(slept) == 10.0
    assert slept[-1] == 10.0


def test_a_real_disconnection_resets_the_backoff(fast_retry, caplog, monkeypatch):
    """Tras una desconexión real hay que reintentar ya, no esperar 30 s."""
    link = SerialLink()
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        # El primer intento abre el puerto y luego se cae; los siguientes fallan
        # sin abrirlo (Arduino desenchufado).
        link._opened = attempts["n"] == 1
        raise RuntimeError("se desconectó" if attempts["n"] == 1 else "sin Arduino")

    monkeypatch.setattr(link, "_connect_and_read", flaky)
    with caplog.at_level(logging.WARNING, logger="app.serial_link"):
        _run(link)

    # Tras la caída de una conexión que existía, la espera vuelve al mínimo.
    assert fast_retry[0] == settings.serial_reconnect_interval
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("se desconectó" in m for m in msgs)


# ── modo sin Arduino ─────────────────────────────────────────────


@pytest.mark.parametrize("value", ["off", "none", "no", "disabled", "0", "OFF", " off "])
def test_serial_can_be_disabled(monkeypatch, value: str):
    monkeypatch.setattr(settings, "port", value)
    assert settings.serial_enabled is False


@pytest.mark.parametrize("value", ["auto", "/dev/ttyACM0", "COM3", ""])
def test_serial_is_enabled_for_real_port_values(monkeypatch, value: str):
    monkeypatch.setattr(settings, "port", value)
    assert settings.serial_enabled is True


def test_run_returns_immediately_when_disabled(monkeypatch, caplog):
    """Con el serial desactivado no se intenta abrir nada ni se duerme."""
    monkeypatch.setattr(settings, "port", "off")
    link = SerialLink()

    async def must_not_be_called():
        raise AssertionError("no debería intentar conectar")

    monkeypatch.setattr(link, "_connect_and_read", must_not_be_called)
    with caplog.at_level(logging.INFO, logger="app.serial_link"):
        asyncio.run(link.run())        # termina sola, sin CancelledError
    assert any("desactivado" in r.getMessage() for r in caplog.records)


# ── resumen de puertos ───────────────────────────────────────────


def test_describe_hides_system_uarts(monkeypatch):
    """Las 32 /dev/ttyS* del sistema se cuentan pero no se listan."""
    ports = [_Port(f"/dev/ttyS{i}", "n/a") for i in range(32)]
    ports.append(_Port("/dev/ttyACM0", "Arduino Nano 33 BLE", vid=0x2341))
    monkeypatch.setattr("app.port_detector.list_serial_ports", lambda: ports)

    out = describe_available_ports()
    assert "/dev/ttyACM0" in out
    assert "/dev/ttyS0" not in out
    assert "32 UART del sistema" in out
    assert len(out) < 200, f"el resumen sigue siendo enorme: {len(out)} chars"


def test_describe_when_only_system_uarts_exist(monkeypatch):
    ports = [_Port(f"/dev/ttyS{i}", "n/a") for i in range(32)]
    monkeypatch.setattr("app.port_detector.list_serial_ports", lambda: ports)
    out = describe_available_ports()
    assert "ningún puerto USB" in out
    assert "32 UART del sistema" in out


def test_describe_with_no_ports_at_all(monkeypatch):
    monkeypatch.setattr("app.port_detector.list_serial_ports", lambda: [])
    assert describe_available_ports() == "(ninguno)"


def test_describe_caps_a_long_list_of_usb_ports(monkeypatch):
    ports = [_Port(f"/dev/ttyUSB{i}", "FTDI", vid=0x0403) for i in range(20)]
    monkeypatch.setattr("app.port_detector.list_serial_ports", lambda: ports)
    out = describe_available_ports(limit=5)
    assert "y 15 más" in out
