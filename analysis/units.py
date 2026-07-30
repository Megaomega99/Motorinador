"""Unidades y conversiones para ángulo y velocidad angular.

Fuente de verdad de la geometría, espejo de src/main.cpp:
    ENC_PPR = 600         →  COUNTS_PER_REV = ENC_PPR * 4 = 2400  (encoder, X4)
    STEPS_PER_REV = 1600  →  200 pasos × 8 micropasos            (motor)

Hay dos ejes y por tanto dos "cuentas por vuelta": el del **encoder** (2400) y el
del **motor** (1600 micropasos). Las conversiones aceptan `counts_per_rev` para
poder servir a ambos; el valor por defecto es el del encoder por compatibilidad.

Los dos ejes están unidos por engranajes con relación ``GEAR_RATIO_DEFAULT``
(vueltas de encoder por vuelta de motor), medida sobre la toma de referencia
`intento serio 2_260729_142804` — ver analysis/gearing.py, que la estima desde
los datos en lugar de suponerla.
"""

from __future__ import annotations

import math
from enum import Enum

# ── Geometría del encoder (espejo de src/main.cpp) ───────────────────────
ENC_PPR: int = 600
COUNTS_PER_REV: int = ENC_PPR * 4  # 2400 cuentas/vuelta (X4)

# ── Geometría del motor (espejo de src/main.cpp) ─────────────────────────
MOTOR_STEPS: int = 200             # pasos/vuelta del NEMA17
MICROSTEPS: int = 8                # MS1=MS2=GND en el TMC2208 → 1/8
STEPS_PER_REV: int = MOTOR_STEPS * MICROSTEPS  # 1600 micropasos/vuelta

# ── Transmisión motor → encoder ──────────────────────────────────────────
# Vueltas de encoder por vuelta de motor. Medido = 1.979 (mediana 1.981) sobre
# 125 s de consigna estable; el valor nominal supuesto era 2.1 (un 6 % alto).
GEAR_RATIO_DEFAULT: float = 1.98

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


def counts_to_angle(
    counts: float, unit: AngleUnit, counts_per_rev: int = COUNTS_PER_REV
) -> float:
    """Convierte un conteo a ángulo en la unidad pedida.

    ``counts_per_rev`` por defecto es el del encoder (2400); pásale
    :data:`STEPS_PER_REV` para razonar sobre el eje del motor.
    """
    return counts * (unit.per_rev / counts_per_rev)


def counts_per_sec_to_velocity(
    counts_per_sec: float, unit: VelocityUnit, counts_per_rev: int = COUNTS_PER_REV
) -> float:
    """Convierte una tasa de cuentas/segundo a velocidad angular.

    rad/s  = cps / CPR * 2π
    grad/s = cps / CPR * 360
    RPM    = cps / CPR * 60

    ``counts_per_rev`` permite usar la misma conversión para el encoder (2400
    cuentas/vuelta) y para el motor (1600 micropasos/vuelta).
    """
    return counts_per_sec / counts_per_rev * unit.per_rev * unit.per_time
