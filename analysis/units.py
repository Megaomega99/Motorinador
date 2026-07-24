"""Unidades y conversiones para ángulo y velocidad angular.

Fuente de verdad de la geometría del encoder: src/main.cpp
    ENC_PPR = 600  →  COUNTS_PER_REV = ENC_PPR * 4 = 2400  (decodificación X4)

Todas las conversiones parten del *conteo* entero de cuentas del encoder
(equivalente a `encoderCount` del firmware) y del intervalo de muestreo `dt`.
"""

from __future__ import annotations

import math
from enum import Enum

# ── Geometría del encoder (espejo de src/main.cpp) ───────────────────────
ENC_PPR: int = 600
COUNTS_PER_REV: int = ENC_PPR * 4  # 2400 cuentas/vuelta (X4)

_TWO_PI = 2.0 * math.pi


class AngleUnit(str, Enum):
    """Unidad de ángulo seleccionable por el usuario."""

    RAD = "rad"
    DEG = "grados"

    @property
    def per_rev(self) -> float:
        """Cuánto vale una vuelta completa en esta unidad."""
        return _TWO_PI if self is AngleUnit.RAD else 360.0


class VelocityUnit(str, Enum):
    """Unidad de velocidad angular seleccionable por el usuario."""

    RAD_S = "rad/s"
    DEG_S = "grad/s"  # grados/segundo
    RPM = "RPM"

    @property
    def per_rev(self) -> float:
        """Valor de una vuelta en las unidades angulares de esta velocidad.

        Para RPM la 'unidad angular' es la vuelta (1), porque RPM ya cuenta
        revoluciones por minuto.
        """
        if self is VelocityUnit.RAD_S:
            return _TWO_PI
        if self is VelocityUnit.DEG_S:
            return 360.0
        return 1.0  # RPM

    @property
    def per_time(self) -> float:
        """Factor temporal: RPM es por minuto (60 s), el resto por segundo."""
        return 60.0 if self is VelocityUnit.RPM else 1.0


def counts_to_angle(counts: float, unit: AngleUnit) -> float:
    """Convierte un conteo de encoder a ángulo en la unidad pedida."""
    return counts * (unit.per_rev / COUNTS_PER_REV)


def counts_per_sec_to_velocity(counts_per_sec: float, unit: VelocityUnit) -> float:
    """Convierte una tasa de cuentas/segundo a velocidad angular.

    rad/s  = cps / CPR * 2π
    grad/s = cps / CPR * 360
    RPM    = cps / CPR * 60
    """
    return counts_per_sec / COUNTS_PER_REV * unit.per_rev * unit.per_time
