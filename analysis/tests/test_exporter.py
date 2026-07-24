from __future__ import annotations

import h5py
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
