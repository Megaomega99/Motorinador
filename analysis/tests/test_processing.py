from __future__ import annotations

import numpy as np
import pytest

from analysis.motor import step_train
from analysis.processing import SessionCache, build_cache
from analysis.units import COUNTS_PER_REV, STEPS_PER_REV, AngleUnit, VelocityUnit

from ._fakes import FakeReader, spinning_quadrature

FS = 30000.0


def _make_cache(tmp_path, chunk=350):
    a, b = spinning_quadrature(cycles=6, samples_per_state=100)  # 2400 muestras, 24 cuentas
    n = a.shape[0]
    electrodes = {
        "A-000": np.linspace(0, 1, n),
        "A-001": np.full(n, 7.0),
    }
    reader = FakeReader(a, b, electrodes)
    path = str(tmp_path / "cache.h5")
    build_cache(reader, path, chunk_samples=chunk)
    return path, n


def _make_motor_cache(tmp_path, motor_rpm=30.0, gear_ratio=2.0, dur_s=2.0, chunk=7000):
    """Caché con encoder y espejo STEP coherentes entre sí."""
    n = int(dur_s * FS)
    motor = step_train(motor_rpm, dur_s, 1.0 / FS)[:n]
    # Encoder girando gear_ratio veces más rápido que el motor.
    enc_rate = motor_rpm * gear_ratio * COUNTS_PER_REV / 60.0     # cuentas/s
    phase = np.arange(n) / FS * enc_rate / 4.0                    # 4 cuentas por ciclo
    quad = np.floor(np.mod(phase, 1.0) * 4).astype(int)           # estado 0..3
    a = np.isin(quad, (2, 3)).astype(np.float64)                  # 00,01,11,10
    b = np.isin(quad, (1, 2)).astype(np.float64)
    reader = FakeReader(a, b, {"A-000": np.zeros(n)}, fs=FS, motor=motor)
    path = str(tmp_path / "motor_cache.h5")
    build_cache(reader, path, chunk_samples=chunk)
    return path, n


def test_cache_counts_and_electrodes(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        assert c.n_samples == n
        assert c.electrode_names == ["A-000", "A-001"]
        # 24 bloques de estado (6 ciclos × 4) → 23 flancos → +23 cuentas.
        assert c.counts[-1] == 23
        assert np.allclose(c.electrode_slice("A-001", 0, n), 7.0)
        assert np.allclose(c.electrode_slice("A-000", 0, 1)[0], 0.0)


def test_cache_angle(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        ang = c.angle_slice(0, n, AngleUnit.DEG)
        assert ang[-1] == (23 / COUNTS_PER_REV) * 360.0


def test_cache_digital_roundtrip(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        a, b = c.digital_slice(0, n)
        assert set(np.unique(a)).issubset({0, 1})
        assert a.shape[0] == n


def test_overview_decimation_bounded(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        ov = c.velocity_overview(VelocityUnit.RPM, window_samples=50, max_points=100)
        assert ov.t.shape[0] <= 100
        assert ov.t.shape[0] == ov.y.shape[0]


def test_session_stats(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        st = c.session_stats(VelocityUnit.RPM, window_samples=50)
        assert st.n == n
        assert st.unit == "RPM"
        assert st.vmax >= st.mean >= st.vmin


# ── señal del motor (espejo STEP) ────────────────────────────────


def test_cache_without_motor_reports_it(tmp_path):
    path, _ = _make_cache(tmp_path)
    with SessionCache(path) as c:
        assert c.has_motor is False
        assert c.step_counts is None


def test_cache_stores_step_counts(tmp_path):
    path, n = _make_motor_cache(tmp_path, motor_rpm=30.0, dur_s=2.0)
    with SessionCache(path) as c:
        assert c.has_motor is True
        expected = 30.0 * STEPS_PER_REV / 60.0 * 2.0     # pasos en 2 s
        assert abs(c.step_counts[-1] - expected) <= 2


def test_motor_rpm_slice_recovers_commanded_speed(tmp_path):
    path, n = _make_motor_cache(tmp_path, motor_rpm=30.0, dur_s=2.0)
    with SessionCache(path) as c:
        rpm = c.motor_rpm_slice(int(0.5 * FS), int(1.5 * FS))
        assert rpm.shape == (int(1.0 * FS),)
        assert np.isclose(np.median(rpm), 30.0, rtol=0.02)


def test_motor_rpm_slice_matches_the_full_series(tmp_path):
    """Un tramo debe valer lo mismo que el mismo tramo de la serie completa.

    Es lo que garantiza que navegar por ventanas no cambie los números: el
    estimador necesita flancos a ambos lados, así que el slice lee con relleno.
    """
    path, n = _make_motor_cache(tmp_path, motor_rpm=20.0, dur_s=2.0)
    with SessionCache(path) as c:
        whole = c.motor_rpm_slice(0, c.n_samples)
        i0, i1 = int(0.8 * FS), int(1.2 * FS)
        assert np.allclose(c.motor_rpm_slice(i0, i1), whole[i0:i1])


def test_motor_voltage_slice_roundtrip(tmp_path):
    path, n = _make_motor_cache(tmp_path)
    with SessionCache(path) as c:
        v = c.motor_voltage_slice(0, 1000)
        assert v.shape == (1000,)
        assert v.max() > 3.0        # nivel lógico alto de 3.3 V


def test_motor_overview_is_bounded(tmp_path):
    path, n = _make_motor_cache(tmp_path)
    with SessionCache(path) as c:
        ov = c.motor_rpm_overview(max_points=100)
        assert ov.t.shape[0] <= 100
        assert ov.t.shape[0] == ov.y.shape[0]


def test_gear_estimate_recovers_the_synthetic_ratio(tmp_path):
    path, n = _make_motor_cache(tmp_path, motor_rpm=30.0, gear_ratio=2.0, dur_s=8.0)
    with SessionCache(path) as c:
        est = c.gear_estimate()
        assert est.ratio is not None
        assert np.isclose(est.ratio, 2.0, rtol=0.03)


def test_motor_stats_and_slip(tmp_path):
    path, n = _make_motor_cache(tmp_path, motor_rpm=30.0, gear_ratio=2.0, dur_s=2.0)
    with SessionCache(path) as c:
        st = c.motor_stats(0, c.n_samples)
        assert st.unit == "RPM"
        assert np.isclose(st.median, 30.0, rtol=0.03)
        slip = c.slip_slice(int(0.5 * FS), int(1.5 * FS), gear_ratio=2.0)
        assert np.all(slip >= 0.0) and np.all(slip <= 1.0)
        assert np.median(slip) < 0.05        # encoder y consigna coherentes


def test_motor_helpers_raise_without_motor_signal(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        for call in (
            lambda: c.motor_rpm_slice(0, 10),
            lambda: c.motor_voltage_slice(0, 10),
            lambda: c.motor_rpm_overview(),
            lambda: c.gear_estimate(),
            lambda: c.motor_stats(0, 10),
            lambda: c.slip_slice(0, 10, 2.0),
        ):
            with pytest.raises(ValueError, match="motor"):
                call()
