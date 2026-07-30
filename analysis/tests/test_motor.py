"""Tests de la recuperación de la velocidad del motor desde el espejo STEP."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.motor import (
    StepCounter,
    motor_rpm_from_step_counts,
    step_train,
)
from analysis.units import STEPS_PER_REV

FS = 30000.0
DT = 1.0 / FS


def _square(rpm: float, n: int, dt: float = DT, v_high: float = 3.29) -> np.ndarray:
    """Onda cuadrada de 50 % igual que la que genera el firmware para `rpm`."""
    f_step = rpm * STEPS_PER_REV / 60.0        # flancos de subida por segundo
    t = np.arange(n) * dt
    phase = np.mod(t * f_step, 1.0)
    return np.where(phase < 0.5, v_high, 0.0)


# ── StepCounter ──────────────────────────────────────────────────


def test_step_counter_counts_one_edge_per_step():
    rpm = 30.0
    dur = 1.0
    v = _square(rpm, int(dur * FS))
    counts = StepCounter().process(v)
    expected = rpm * STEPS_PER_REV / 60.0 * dur
    assert abs(counts[-1] - expected) <= 1


def test_step_counter_is_monotonic_and_per_sample():
    v = _square(60.0, 3000)
    counts = StepCounter().process(v)
    assert counts.shape == v.shape
    assert np.all(np.diff(counts) >= 0)


def test_step_counter_flat_idle_signal_counts_nothing():
    # Motor parado: el firmware deja STEP en LOW → solo ruido de µV.
    rng = np.random.default_rng(0)
    v = rng.normal(0.0022, 0.001, 5000)
    assert StepCounter().process(v)[-1] == 0


def test_step_counter_chunked_equals_whole():
    v = _square(45.0, 9000)
    whole = StepCounter().process(v)[-1]
    dec = StepCounter()
    for i in range(0, len(v), 700):
        last = dec.process(v[i:i + 700])[-1]
    assert last == whole


def test_step_counter_hysteresis_rejects_wander_inside_the_dead_band():
    """Una señal que oscila dentro de la banda muerta no genera flancos.

    Recorrido [0.85, 1.45] V: cruza muchas veces el punto medio (1.15) pero nunca
    alcanza v_low=0.8 ni v_high=1.5. Un comparador de umbral único daría cientos
    de flancos; con histéresis debe dar cero.
    """
    t = np.linspace(0, 40 * np.pi, 4000)
    v = 1.15 + 0.30 * np.sin(t)
    assert StepCounter().process(v)[-1] == 0


def test_step_counter_empty_chunk():
    dec = StepCounter()
    out = dec.process(np.empty(0))
    assert out.shape == (0,)
    assert dec.count == 0


# ── motor_rpm_from_step_counts ───────────────────────────────────


@pytest.mark.parametrize("rpm", [1.0, 5.0, 30.0, 120.0])
def test_motor_rpm_recovers_commanded_speed(rpm):
    v = _square(rpm, int(2.0 * FS))
    counts = StepCounter().process(v)
    out = motor_rpm_from_step_counts(counts, DT)
    mid = out[len(out) // 4: -len(out) // 4]
    assert np.allclose(np.median(mid), rpm, rtol=0.02)


def test_motor_rpm_zero_when_no_steps():
    counts = np.zeros(1000, dtype=np.int64)
    assert np.all(motor_rpm_from_step_counts(counts, DT) == 0.0)


def test_motor_rpm_decays_to_zero_after_stop():
    """Tras el último flanco la velocidad cae a 0 al superar el timeout."""
    v = np.concatenate([_square(30.0, int(0.5 * FS)), np.zeros(int(0.5 * FS))])
    counts = StepCounter().process(v)
    out = motor_rpm_from_step_counts(counts, DT, stop_timeout_s=0.05)
    assert out[-1] == 0.0
    assert np.median(out[:int(0.4 * FS)]) > 25.0


def test_motor_rpm_follows_a_speed_change():
    v = np.concatenate([_square(10.0, int(1.0 * FS)), _square(50.0, int(1.0 * FS))])
    counts = StepCounter().process(v)
    out = motor_rpm_from_step_counts(counts, DT)
    assert np.isclose(np.median(out[int(0.2 * FS):int(0.9 * FS)]), 10.0, rtol=0.03)
    assert np.isclose(np.median(out[int(1.2 * FS):int(1.9 * FS)]), 50.0, rtol=0.03)


def test_motor_rpm_short_input_is_safe():
    assert motor_rpm_from_step_counts(np.zeros(1, dtype=np.int64), DT).shape == (1,)
    assert motor_rpm_from_step_counts(np.empty(0, dtype=np.int64), DT).shape == (0,)


def test_motor_rpm_rejects_bad_dt():
    with pytest.raises(ValueError):
        motor_rpm_from_step_counts(np.zeros(10, dtype=np.int64), 0.0)


# ── step_train (helper de test/simulación) ───────────────────────


def test_step_train_matches_expected_edge_count():
    v = step_train(20.0, 1.0, DT)
    counts = StepCounter().process(v)
    assert abs(counts[-1] - 20.0 * STEPS_PER_REV / 60.0) <= 1
