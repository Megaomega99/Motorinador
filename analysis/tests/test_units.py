from __future__ import annotations

import math

import pytest

from analysis.units import (
    COUNTS_PER_REV,
    AngleUnit,
    VelocityUnit,
    counts_per_sec_to_velocity,
    counts_to_angle,
)


def test_counts_per_rev_is_x4():
    assert COUNTS_PER_REV == 2400


@pytest.mark.parametrize(
    "counts, unit, expected",
    [
        (COUNTS_PER_REV, AngleUnit.DEG, 360.0),
        (COUNTS_PER_REV, AngleUnit.RAD, 2 * math.pi),
        (COUNTS_PER_REV // 2, AngleUnit.DEG, 180.0),
        (0, AngleUnit.RAD, 0.0),
        (-COUNTS_PER_REV, AngleUnit.DEG, -360.0),
    ],
)
def test_counts_to_angle(counts, unit, expected):
    assert counts_to_angle(counts, unit) == pytest.approx(expected)


def test_one_rev_per_second():
    # CPR cuentas en 1 s == 1 vuelta/s
    cps = float(COUNTS_PER_REV)
    assert counts_per_sec_to_velocity(cps, VelocityUnit.RAD_S) == pytest.approx(2 * math.pi)
    assert counts_per_sec_to_velocity(cps, VelocityUnit.DEG_S) == pytest.approx(360.0)
    assert counts_per_sec_to_velocity(cps, VelocityUnit.RPM) == pytest.approx(60.0)


def test_velocity_sign_preserved():
    cps = -float(COUNTS_PER_REV)
    assert counts_per_sec_to_velocity(cps, VelocityUnit.RPM) == pytest.approx(-60.0)


def test_rpm_matches_firmware_relation():
    # 60 RPM == 1 rev/s == 2π rad/s (relación usada en backend serial_link._enrich)
    rpm = 60.0
    rad_s = rpm * 2 * math.pi / 60
    cps = rpm / 60 * COUNTS_PER_REV
    assert counts_per_sec_to_velocity(cps, VelocityUnit.RAD_S) == pytest.approx(rad_s)
