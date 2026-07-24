from __future__ import annotations

import numpy as np

from analysis.processing import SessionCache, build_cache
from analysis.units import COUNTS_PER_REV, AngleUnit, VelocityUnit

from ._fakes import FakeReader, spinning_quadrature


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
