"""Tests de la estimación de la relación de engranajes y del deslizamiento."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.gearing import GearEstimate, estimate_gear_ratio, slip_fraction
from analysis.units import COUNTS_PER_REV, STEPS_PER_REV

FS = 30000.0
DT = 1.0 / FS


def _counts(rate_per_s: float, n: int, dt: float = DT) -> np.ndarray:
    """Conteo acumulado ideal para una tasa constante de eventos/s."""
    return np.floor(np.arange(n) * dt * rate_per_s).astype(np.int64)


def _synth(motor_rpm: float, ratio: float, dur_s: float) -> tuple[np.ndarray, np.ndarray]:
    n = int(dur_s * FS)
    step_rate = motor_rpm * STEPS_PER_REV / 60.0
    enc_rate = motor_rpm * ratio * COUNTS_PER_REV / 60.0
    return _counts(step_rate, n), _counts(enc_rate, n)


# ── estimate_gear_ratio ──────────────────────────────────────────


@pytest.mark.parametrize("ratio", [1.0, 1.98, 2.1, 3.0])
def test_estimates_a_clean_ratio(ratio):
    step, enc = _synth(motor_rpm=5.0, ratio=ratio, dur_s=20.0)
    est = estimate_gear_ratio(step, enc, DT)
    assert est.ratio is not None
    assert np.isclose(est.ratio, ratio, rtol=0.02)
    assert est.n_stall == 0


def test_reports_revolutions_used():
    step, enc = _synth(motor_rpm=6.0, ratio=2.0, dur_s=10.0)
    est = estimate_gear_ratio(step, enc, DT)
    # 6 RPM durante ~10 s ≈ 1 vuelta de motor (se recortan ventanas de borde)
    assert 0.5 < est.motor_revs < 1.1
    assert np.isclose(est.enc_revs / est.motor_revs, 2.0, rtol=0.03)


def test_ignores_stalled_windows_in_the_ratio():
    """Un atasco (el encoder se para y los pasos siguen) no debe sesgar el ratio."""
    step_a, enc_a = _synth(5.0, 2.0, 12.0)
    step_b, enc_b = _synth(5.0, 2.0, 3.0)
    # tramo atascado: los pasos siguen, el encoder no avanza
    n_stall = int(3.0 * FS)
    step_stall = step_a[-1] + _counts(5.0 * STEPS_PER_REV / 60.0, n_stall)
    enc_stall = np.full(n_stall, enc_a[-1], dtype=np.int64)

    step = np.concatenate([step_a, step_stall, step_stall[-1] + step_b])
    enc = np.concatenate([enc_a, enc_stall, enc_stall[-1] + enc_b])

    est = estimate_gear_ratio(step, enc, DT)
    assert est.ratio is not None
    assert np.isclose(est.ratio, 2.0, rtol=0.05)
    assert est.n_stall >= 2


def test_returns_none_without_movement():
    n = int(5.0 * FS)
    est = estimate_gear_ratio(np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), DT)
    assert est.ratio is None
    assert est.n_steady == 0


def test_skips_windows_where_the_command_changes():
    """Durante una rampa el motor no sigue la consigna → esa ventana no cuenta."""
    ramp_step = np.concatenate([_counts(r * STEPS_PER_REV / 60.0, int(FS)) for r in (2, 4, 6, 8)])
    ramp_step = np.cumsum(np.diff(ramp_step, prepend=ramp_step[0]).clip(min=0))
    ramp_enc = np.zeros_like(ramp_step)          # el encoder no se mueve en la rampa
    steady_step, steady_enc = _synth(5.0, 2.0, 15.0)
    step = np.concatenate([ramp_step, ramp_step[-1] + steady_step])
    enc = np.concatenate([ramp_enc, ramp_enc[-1] + steady_enc])
    est = estimate_gear_ratio(step, enc, DT)
    assert est.ratio is not None
    assert np.isclose(est.ratio, 2.0, rtol=0.05)


def test_estimate_is_immutable_dataclass():
    est = GearEstimate(ratio=2.0, median_ratio=2.0, n_steady=3, n_stall=0,
                       motor_revs=1.0, enc_revs=2.0)
    with pytest.raises(Exception):
        est.ratio = 3.0  # type: ignore[misc]


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        estimate_gear_ratio(np.zeros(10, dtype=np.int64), np.zeros(9, dtype=np.int64), DT)


def test_rejects_bad_dt():
    with pytest.raises(ValueError):
        estimate_gear_ratio(np.zeros(10, dtype=np.int64), np.zeros(10, dtype=np.int64), 0.0)


# ── slip_fraction ────────────────────────────────────────────────


def test_slip_is_zero_when_encoder_matches_the_command():
    motor = np.full(100, 5.0)
    enc = motor * 1.98
    assert np.allclose(slip_fraction(motor, enc, 1.98), 0.0)


def test_slip_is_one_when_the_shaft_is_blocked():
    motor = np.full(10, 5.0)
    enc = np.zeros(10)
    assert np.allclose(slip_fraction(motor, enc, 1.98), 1.0)


def test_slip_is_zero_when_the_motor_is_stopped():
    """Sin consigna el deslizamiento no está definido → 0, no infinito."""
    out = slip_fraction(np.zeros(10), np.zeros(10), 1.98)
    assert np.all(np.isfinite(out))
    assert np.allclose(out, 0.0)


def test_slip_uses_magnitude_of_encoder_speed():
    """El signo del encoder es la dirección; el deslizamiento usa la magnitud."""
    motor = np.full(10, 5.0)
    enc = np.full(10, -5.0 * 1.98)
    assert np.allclose(slip_fraction(motor, enc, 1.98), 0.0)


def test_slip_rejects_bad_ratio():
    with pytest.raises(ValueError):
        slip_fraction(np.ones(3), np.ones(3), 0.0)
