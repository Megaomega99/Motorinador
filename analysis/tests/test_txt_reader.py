from __future__ import annotations

import numpy as np

from analysis.readers.factory import open_reader
from analysis.readers.txt_reader import TxtReader, toggles_to_levels

# Cabecera mínima estilo Intan: Time, 2 digitales, 1 electrodo (A + uV).
_HEADER = '"Time"\t"66 DIGITAL-IN-02"\t"65 DIGITAL-IN-01"\t"4 A-000"\t"3 A-000"\n'
_UNITS = '"Units"\t""\t""\t"A"\t"uV"\n'


def _write_fixture(path, n=10, dt=1.0 / 30000.0):
    lines = [_HEADER, _UNITS]
    for i in range(n):
        t = i * dt
        digb = i % 2          # DIGITAL-IN-02 (B)
        diga = (i // 2) % 2   # DIGITAL-IN-01 (A)
        current = 0.0
        uv = 100.0 + i        # electrodo en µV
        lines.append(f"{t:.8f}\t{digb}\t{diga}\t{current:.7f}\t{uv:.2f}\n")
    path.write_text("".join(lines))
    return path


def test_metadata(tmp_path):
    f = _write_fixture(tmp_path / "mini.txt", n=30)
    r = TxtReader(str(f))
    m = r.metadata()
    assert m.fmt == "txt"
    assert m.electrode_names == ["A-000"]
    assert m.digital_names == ["DIGITAL-IN-01", "DIGITAL-IN-02"]
    # Sin settings.xml, fs se infiere de la columna Time (truncada a 8
    # decimales) → aproximado dentro de ~0.1 %.
    assert abs(m.sample_rate_hz - 30000.0) < 30.0
    assert m.n_samples == 30


def test_iter_chunks_ab_only(tmp_path):
    f = _write_fixture(tmp_path / "mini.txt", n=10)
    r = TxtReader(str(f), digital_mode="level")
    chunks = list(r.iter_chunks(chunk_samples=4))
    total = sum(len(c) for c in chunks)
    assert total == 10
    a = np.concatenate([c.a for c in chunks])
    b = np.concatenate([c.b for c in chunks])
    # A = (i//2)%2, B = i%2
    assert list(a.astype(int)) == [(i // 2) % 2 for i in range(10)]
    assert list(b.astype(int)) == [i % 2 for i in range(10)]
    assert all(not c.electrodes for c in chunks)


def test_iter_chunks_with_electrode(tmp_path):
    f = _write_fixture(tmp_path / "mini.txt", n=10)
    r = TxtReader(str(f), digital_mode="level")
    chunks = list(r.iter_chunks(chunk_samples=10, electrodes=["A-000"]))
    uv = np.concatenate([c.electrodes["A-000"] for c in chunks])
    assert np.allclose(uv, [100.0 + i for i in range(10)])


def test_factory_picks_txt(tmp_path):
    f = _write_fixture(tmp_path / "mini.txt", n=5)
    assert isinstance(open_reader(str(f)), TxtReader)


def test_toggles_to_levels_parity():
    pulses = np.array([1, 0, 0, 1, 0, 1], dtype=np.int64)
    lvl, parity = toggles_to_levels(pulses, parity0=0)
    # paridad acumulada: 1,1,1,0,0,1
    assert list(lvl.astype(int)) == [1, 1, 1, 0, 0, 1]
    assert parity == 1


def test_toggles_to_levels_stateful_across_split():
    pulses = np.array([1, 0, 1, 1, 0, 1], dtype=np.int64)
    full, _ = toggles_to_levels(pulses, 0)
    l1, p1 = toggles_to_levels(pulses[:3], 0)
    l2, _ = toggles_to_levels(pulses[3:], p1)
    assert np.array_equal(np.concatenate([l1, l2]), full)


def _write_toggle_fixture(path, levels_a, levels_b, dt=1.0 / 30000.0):
    """Escribe un fixture cuyas columnas DIGITAL-IN son pulsos de flanco."""
    # pulso[i] = 1 si el nivel cambia respecto al anterior (o nivel inicial en i=0)
    la = np.asarray(levels_a)
    lb = np.asarray(levels_b)
    pa = np.concatenate(([la[0]], (np.diff(la) != 0).astype(int)))
    pb = np.concatenate(([lb[0]], (np.diff(lb) != 0).astype(int)))
    lines = [_HEADER, _UNITS]
    for i in range(len(la)):
        lines.append(f"{i*dt:.8f}\t{pb[i]}\t{pa[i]}\t0.0000000\t{100.0+i:.2f}\n")
    path.write_text("".join(lines))
    return path


def test_toggle_mode_reconstructs_levels(tmp_path):
    # Niveles de cuadratura conocidos → pulsos → reader modo toggle → niveles.
    la = [1, 1, 0, 0, 1, 1, 0, 0, 1]
    lb = [1, 0, 0, 1, 1, 0, 0, 1, 1]
    f = _write_toggle_fixture(tmp_path / "tog.txt", la, lb)
    r = TxtReader(str(f))  # modo por defecto: toggle
    chunks = list(r.iter_chunks(chunk_samples=3))  # fuerza reconstrucción entre segmentos
    a = np.concatenate([c.a for c in chunks]).astype(int)
    b = np.concatenate([c.b for c in chunks]).astype(int)
    assert list(a) == la
    assert list(b) == lb
