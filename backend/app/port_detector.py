from __future__ import annotations

import logging
import sys
from typing import Optional

from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

logger = logging.getLogger(__name__)

# VID conocidos de Arduino y chips USB-Serial comunes (clones incluidos)
KNOWN_VIDS = {
    0x2341,  # Arduino LLC / Arduino SA (incluye Nano 33 BLE por USB nativo nRF52840)
    0x2A03,  # Arduino (alternativo)
    0x1B4F,  # SparkFun
    0x239A,  # Adafruit
    0x10C4,  # Silicon Labs (CP210x)
    0x1A86,  # QinHeng (CH340/CH341)
    0x0403,  # FTDI
    0x067B,  # Prolific (PL2303)
    0x16C0,  # Teensyduino
    0x03EB,  # Atmel (Nano Every usa ATSAMD11 como puente USB-Serial)
}

# Palabras clave en la descripción del dispositivo
KEYWORDS = (
    "arduino",
    "nano",
    "uno",
    "mega",
    "leonardo",
    "ch340",
    "ch341",
    "cp210",
    "ftdi",
    "usb serial",
    "usb-serial",
    "usbmodem",
    "usbserial",
    "wchusbserial",
)


def _score(port: ListPortInfo) -> int:
    """Asigna un puntaje a un puerto para priorizar candidatos a Arduino."""
    score = 0
    if port.vid in KNOWN_VIDS:
        score += 100
    haystack = " ".join(
        s.lower() for s in (port.description or "", port.manufacturer or "", port.product or "", port.device or "") if s
    )
    for kw in KEYWORDS:
        if kw in haystack:
            score += 10
    # Penaliza puertos seriales del sistema (no-USB) en Linux/Mac
    dev = (port.device or "").lower()
    if sys.platform.startswith("linux") and "/ttys" in dev:
        score -= 1000
    if sys.platform == "darwin" and "/tty." in dev:
        # En macOS preferimos /dev/cu.* sobre /dev/tty.* para evitar bloqueos
        score -= 50
    return score


def list_serial_ports() -> list[ListPortInfo]:
    return list(list_ports.comports())


def plausible_ports() -> list[ListPortInfo]:
    """Puertos que podrían llevar un Arduino.

    Descarta las UART heredadas del sistema (`/dev/ttyS0…S31` en Linux), que
    `_score` ya penaliza con −1000: existen siempre, nunca son un Arduino y
    llenaban el mensaje de error con 32 entradas inútiles.
    """
    return [p for p in list_serial_ports() if _score(p) > -1000]


def detect_arduino_port(preferred: Optional[str] = None) -> Optional[str]:
    """
    Detecta automáticamente el puerto del Arduino.

    Orden de prioridad:
    1. `preferred` si está presente físicamente.
    2. Puerto con VID conocido de Arduino/USB-Serial (mayor puntaje).
    3. Cualquier puerto USB-Serial detectado.

    Funciona en Linux (`/dev/ttyACM*`, `/dev/ttyUSB*`), macOS
    (`/dev/cu.usbmodem*`, `/dev/cu.usbserial*`) y Windows (`COMx`).
    """
    ports = list_serial_ports()
    if not ports:
        logger.warning("No se encontraron puertos seriales en el sistema")
        return None

    devices = {p.device for p in ports}

    if preferred and preferred in devices:
        logger.info("Puerto preferido encontrado: %s", preferred)
        return preferred

    if preferred:
        logger.info(
            "Puerto preferido %s no disponible — buscando automáticamente entre %d puertos",
            preferred,
            len(ports),
        )

    candidates = sorted(ports, key=_score, reverse=True)
    best = candidates[0]
    if _score(best) <= 0:
        # A nivel de depuración: quien llama (SerialLink.run) ya emite un aviso
        # legible y sin repetirlo en cada reintento.
        logger.debug(
            "Ningún puerto parece ser un Arduino. Candidatos: %s",
            [f"{p.device} ({p.description})" for p in plausible_ports()],
        )
        return None

    logger.info(
        "Arduino detectado automáticamente en %s (%s)",
        best.device,
        best.description or "sin descripción",
    )
    return best.device


def describe_available_ports(limit: int = 8) -> str:
    """Resumen legible de los puertos, solo con los que podrían ser un Arduino.

    Las UART del sistema se cuentan pero no se listan: mencionar 32 `/dev/ttyS*`
    en cada mensaje de error no ayuda a nadie a encontrar su placa.
    """
    total = len(list_serial_ports())
    if total == 0:
        return "(ninguno)"

    useful = plausible_ports()
    hidden = total - len(useful)
    suffix = f" (+{hidden} UART del sistema, descartadas)" if hidden else ""
    if not useful:
        return f"(ningún puerto USB){suffix}"

    shown = ", ".join(f"{p.device} [{p.description or '?'}]" for p in useful[:limit])
    if len(useful) > limit:
        shown += f", … y {len(useful) - limit} más"
    return shown + suffix
