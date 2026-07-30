from __future__ import annotations

import h5py
import pytest
import numpy as np
import pandas as pd

from analysis.exporter import export, infer_format
from analysis.processing import SessionCache, build_cache
from analysis.units import AngleUnit, VelocityUnit

from ._fakes import FakeReader, spinning_quadrature


def _make_cache(tmp_path):
    a, b = spinning_quadrature(cycles=4, samples_per_state=50)
    n = a.shape[0]
    electrodes = {"A-000": np.arange(n, dtype=float), "A-001": np.full(n, 3.5)}
    build_cache(FakeReader(a, b, electrodes), str(tmp_path / "cache.h5"), chunk_samples=120)
    return str(tmp_path / "cache.h5"), n


def test_infer_format():
    assert infer_format("x.csv") == "tabular"
    assert infer_format("x.txt") == "tabular"
    assert infer_format("x.h5") == "hdf5"
    assert infer_format("x.hdf5") == "hdf5"


def test_export_csv_roundtrip(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "out.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20, chunk_samples=100)
        ref_ang = c.angle_slice(0, n, AngleUnit.DEG)

    df = pd.read_csv(out, skiprows=[1])  # fila 1 = unidades
    assert list(df.columns[:3]) == ["Time", "DIGITAL-IN-01", "DIGITAL-IN-02"]
    assert "angle_grados" in df.columns
    assert "omega_RPM" in df.columns
    assert "A-000" in df.columns and "A-001" in df.columns
    assert len(df) == n
    assert np.allclose(df["angle_grados"].to_numpy(), ref_ang, atol=1e-4)
    assert np.allclose(df["A-001"].to_numpy(), 3.5)


def test_export_hdf5_roundtrip(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "out.h5")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.RAD, VelocityUnit.RAD_S, window_samples=20, chunk_samples=100)
        ref_vel = c.velocity_slice(0, n, VelocityUnit.RAD_S, 20)

    with h5py.File(out, "r") as h5:
        assert h5.attrs["angle_unit"] == "rad"
        assert "angle_rad" in h5
        assert "omega_rad/s" in h5
        assert h5["electrodes"]["A-000"].shape[0] == n
        assert np.allclose(h5["omega_rad/s"][:], ref_vel, atol=1e-3)


def test_export_subset_electrodes(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "sub.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20, electrodes=["A-001"])
    df = pd.read_csv(out, skiprows=[1])
    assert "A-001" in df.columns
    assert "A-000" not in df.columns


def test_export_without_motor_has_no_motor_columns(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "nomotor.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20)
    df = pd.read_csv(out, skiprows=[1])
    assert "motor_rpm" not in df.columns


# ── columnas del motor ───────────────────────────────────────────


def _make_motor_cache(tmp_path):
    from analysis.motor import step_train
    from analysis.units import COUNTS_PER_REV

    fs, dur, rpm, ratio = 30000.0, 1.0, 30.0, 2.0
    n = int(fs * dur)
    motor = step_train(rpm, dur, 1.0 / fs)[:n]
    phase = np.arange(n) / fs * (rpm * ratio * COUNTS_PER_REV / 60.0) / 4.0
    quad = np.floor(np.mod(phase, 1.0) * 4).astype(int)
    a = np.isin(quad, (2, 3)).astype(float)
    b = np.isin(quad, (1, 2)).astype(float)
    p = str(tmp_path / "mcache.h5")
    build_cache(FakeReader(a, b, {"A-000": np.zeros(n)}, fs=fs, motor=motor), p,
                chunk_samples=7000)
    return p, n


def test_export_csv_includes_motor_columns(tmp_path):
    path, n = _make_motor_cache(tmp_path)
    out = str(tmp_path / "motor.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=1500,
               gear_ratio=2.0, chunk_samples=7000)
        ref_rpm = c.motor_rpm_slice(0, n)

    df = pd.read_csv(out, skiprows=[1])
    for col in ("step_count", "motor_rpm", "analog_in_2_V", "slip"):
        assert col in df.columns, col
    assert len(df) == n
    assert np.allclose(df["motor_rpm"].to_numpy(), ref_rpm, atol=1e-3)
    # Velocidad comandada constante de 30 RPM y deslizamiento coherente ≈ 0.
    assert np.isclose(np.median(df["motor_rpm"]), 30.0, rtol=0.02)
    assert np.median(df["slip"]) < 0.05
    assert df["step_count"].is_monotonic_increasing


# ── rango de exportación ─────────────────────────────────────────


def test_export_range_writes_only_that_span(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "range.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20,
               sample_range=(100, 300))
        ref_t = c.time_slice(100, 300)
    df = pd.read_csv(out, skiprows=[1])
    assert len(df) == 200
    assert np.allclose(df["Time"].to_numpy(), ref_t, atol=1e-6)


def test_export_range_hdf5_records_the_span(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "range.h5")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20,
               sample_range=(50, 150))
        dt = c.dt
    with h5py.File(out, "r") as h5:
        assert h5["time"].shape[0] == 100
        assert h5.attrs["t_start_s"] == pytest.approx(50 * dt)
        assert h5.attrs["t_stop_s"] == pytest.approx(150 * dt)
        assert h5["electrodes"]["A-000"].shape[0] == 100


def test_export_range_is_clamped_to_the_session(tmp_path):
    path, n = _make_cache(tmp_path)
    out = str(tmp_path / "clamp.csv")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20,
               sample_range=(-500, n + 5000))
    assert len(pd.read_csv(out, skiprows=[1])) == n


def test_export_empty_range_raises(tmp_path):
    path, n = _make_cache(tmp_path)
    with SessionCache(path) as c:
        with pytest.raises(ValueError, match="vacío"):
            export(c, str(tmp_path / "x.csv"), AngleUnit.DEG, VelocityUnit.RPM,
                   window_samples=20, sample_range=(200, 200))


def test_export_range_values_match_the_full_export(tmp_path):
    """Un tramo exportado debe ser idéntico a ese tramo del export completo."""
    path, n = _make_cache(tmp_path)
    full, part = str(tmp_path / "full.csv"), str(tmp_path / "part.csv")
    with SessionCache(path) as c:
        export(c, full, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20)
        export(c, part, AngleUnit.DEG, VelocityUnit.RPM, window_samples=20,
               sample_range=(120, 260))
    df_full = pd.read_csv(full, skiprows=[1]).iloc[120:260].reset_index(drop=True)
    df_part = pd.read_csv(part, skiprows=[1])
    for col in ("Time", "angle_grados", "omega_RPM", "A-000"):
        assert np.allclose(df_full[col].to_numpy(), df_part[col].to_numpy(), atol=1e-5), col


def test_export_hdf5_includes_motor_datasets(tmp_path):
    path, n = _make_motor_cache(tmp_path)
    out = str(tmp_path / "motor.h5")
    with SessionCache(path) as c:
        export(c, out, AngleUnit.RAD, VelocityUnit.RPM, window_samples=1500,
               gear_ratio=2.0, chunk_samples=7000)

    with h5py.File(out, "r") as h5:
        assert h5.attrs["gear_ratio"] == 2.0
        for ds in ("step_count", "motor_rpm", "analog_in_2_V", "slip"):
            assert ds in h5, ds
            assert h5[ds].shape[0] == n
        assert np.isclose(np.median(h5["motor_rpm"][:]), 30.0, rtol=0.02)
