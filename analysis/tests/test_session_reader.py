"""Tests del lector de sesión: varios archivos como una grabación continua."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.readers.session import SessionReader, session_files
from analysis.tests._fakes import FakeReader, spinning_quadrature


def _ab(n: int):
    """Cuadratura de exactamente ``n`` muestras (un ciclo son 4 estados)."""
    a, b = spinning_quadrature(cycles=-(-n // 4), samples_per_state=1)
    return a[:n], b[:n]


def _part(n: int, offset: float = 0.0, fs: float = 30000.0, motor: bool = False):
    a, b = _ab(n)
    elec = {"A-000": np.arange(n, dtype=np.float64) + offset}
    mot = np.full(n, 3.29) if motor else None
    return FakeReader(a, b, elec, fs=fs, motor=mot)


# ── metadatos ────────────────────────────────────────────────────


def test_totals_add_up():
    s = SessionReader([_part(100), _part(60), _part(40)])
    m = s.metadata()
    assert m.n_samples == 200
    assert m.sample_rate_hz == 30000.0
    assert m.electrode_names == ["A-000"]


def test_duration_is_the_sum_of_parts():
    s = SessionReader([_part(30000), _part(30000)])
    assert s.metadata().duration_s == pytest.approx(2.0)


def test_rejects_mismatched_sample_rates():
    with pytest.raises(ValueError, match="frecuencia"):
        SessionReader([_part(10, fs=30000.0), _part(10, fs=20000.0)])


def test_rejects_empty_list():
    with pytest.raises(ValueError):
        SessionReader([])


def test_electrode_names_are_the_intersection():
    """Solo se ofrecen los electrodos presentes en TODOS los archivos."""
    p1 = FakeReader(*_ab(10), {"A-000": np.zeros(10), "A-001": np.zeros(10)})
    p2 = FakeReader(*_ab(10), {"A-000": np.zeros(10)})
    assert SessionReader([p1, p2]).metadata().electrode_names == ["A-000"]


def test_motor_is_present_only_if_every_part_has_it():
    both = SessionReader([_part(10, motor=True), _part(10, motor=True)])
    assert both.metadata().has_motor is True
    mixed = SessionReader([_part(10, motor=True), _part(10, motor=False)])
    assert mixed.metadata().has_motor is False


# ── iteración ────────────────────────────────────────────────────


def test_concatenates_signals_in_order():
    s = SessionReader([_part(100, offset=0), _part(50, offset=1000)])
    chunks = list(s.iter_chunks(chunk_samples=30, electrodes=["A-000"]))
    uv = np.concatenate([c.electrodes["A-000"] for c in chunks])
    assert uv.shape == (150,)
    assert uv[0] == 0.0
    assert uv[99] == 99.0
    assert uv[100] == 1000.0          # arranca el segundo archivo
    assert uv[149] == 1049.0


def test_time_axis_is_continuous_across_files():
    fs = 1000.0
    s = SessionReader([_part(100, fs=fs), _part(100, fs=fs)])
    t = np.concatenate([c.t for c in s.iter_chunks(chunk_samples=40)])
    assert t.shape == (200,)
    assert np.allclose(np.diff(t), 1.0 / fs)   # sin salto en la frontera
    assert t[0] == 0.0


def test_motor_channel_is_concatenated():
    s = SessionReader([_part(50, motor=True), _part(50, motor=True)])
    mot = np.concatenate([c.motor for c in s.iter_chunks(chunk_samples=20)])
    assert mot.shape == (100,)
    assert np.all(mot == 3.29)


def test_quadrature_is_continuous_across_the_boundary():
    """Decodificar la sesión debe dar lo mismo que decodificar la señal unida."""
    from analysis.encoder import QuadratureDecoder

    a, b = spinning_quadrature(cycles=20, samples_per_state=3)
    half = a.shape[0] // 2
    p1 = FakeReader(a[:half], b[:half], {})
    p2 = FakeReader(a[half:], b[half:], {})

    whole = QuadratureDecoder().process(a, b)[-1]
    dec = QuadratureDecoder()
    last = 0
    for c in SessionReader([p1, p2]).iter_chunks(chunk_samples=7):
        last = int(dec.process(c.a, c.b)[-1])
    assert last == whole


def test_unknown_electrode_raises():
    s = SessionReader([_part(10)])
    with pytest.raises(ValueError, match="desconocido"):
        list(s.iter_chunks(chunk_samples=5, electrodes=["A-999"]))


# ── descubrimiento de archivos ───────────────────────────────────


def test_session_files_sorted_and_filtered(tmp_path):
    for name in ("b_143004.rhs", "a_142804.rhs", "c_143104.rhs", "settings.xml"):
        (tmp_path / name).write_bytes(b"x")
    found = session_files(str(tmp_path))
    assert [f.rsplit("/", 1)[-1] for f in found] == [
        "a_142804.rhs", "b_143004.rhs", "c_143104.rhs"
    ]


def test_session_files_from_a_member_file(tmp_path):
    for name in ("a_1.rhs", "a_2.rhs"):
        (tmp_path / name).write_bytes(b"x")
    found = session_files(str(tmp_path / "a_2.rhs"))
    assert len(found) == 2


def test_session_files_empty_folder(tmp_path):
    assert session_files(str(tmp_path)) == []
