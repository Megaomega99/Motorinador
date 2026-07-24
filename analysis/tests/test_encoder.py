from __future__ import annotations

import numpy as np
import pytest

from analysis.encoder import QuadratureDecoder, velocity_from_counts
from analysis.units import COUNTS_PER_REV, VelocityUnit

# Secuencia de estados de cuadratura (A, B) para un ciclo eléctrico.
# Sentido + (horario, igual convención que el firmware): 00→01→11→10→00
CW_STATES = [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
# Sentido − (antihorario): recorrido inverso.
CCW_STATES = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]


def _ab(states):
    a = np.array([s[0] for s in states], dtype=np.uint8)
    b = np.array([s[1] for s in states], dtype=np.uint8)
    return a, b


def test_forward_cycle_is_plus_four():
    a, b = _ab(CW_STATES)
    counts = QuadratureDecoder().process(a, b)
    # 4 transiciones válidas de +1 → +4; primera muestra no incrementa.
    assert counts[-1] == 4
    assert counts[0] == 0


def test_reverse_cycle_is_minus_four():
    a, b = _ab(CCW_STATES)
    counts = QuadratureDecoder().process(a, b)
    assert counts[-1] == -4


def test_full_revolution_counts():
    # CPR/4 ciclos eléctricos == 1 vuelta == CPR cuentas.
    cycles = COUNTS_PER_REV // 4
    states = [(0, 0)]
    for _ in range(cycles):
        states += [(0, 1), (1, 1), (1, 0), (0, 0)]
    a, b = _ab(states)
    counts = QuadratureDecoder().process(a, b)
    assert counts[-1] == COUNTS_PER_REV


def test_stateful_across_chunks():
    a, b = _ab(CW_STATES)
    dec = QuadratureDecoder()
    c1 = dec.process(a[:3], b[:3])
    c2 = dec.process(a[3:], b[3:])
    # La continuidad debe dar el mismo total que procesar de una vez.
    full = QuadratureDecoder().process(a, b)
    assert c2[-1] == full[-1]
    assert c1[-1] == full[2]


def test_glitch_double_transition_ignored():
    # Salto 00→11 (ambos bits cambian) es ambiguo → incremento 0.
    a, b = _ab([(0, 0), (1, 1)])
    counts = QuadratureDecoder().process(a, b)
    assert counts[-1] == 0


def test_no_movement_is_zero():
    a, b = _ab([(1, 1)] * 100)
    counts = QuadratureDecoder().process(a, b)
    assert np.all(counts == 0)


def test_velocity_constant_rotation():
    # 1 vuelta/s a fs=30kHz durante 1 s → 60 RPM.
    fs = 30000
    dt = 1.0 / fs
    # counts sube linealmente CPR cuentas en fs muestras.
    counts = np.round(np.linspace(0, COUNTS_PER_REV, fs)).astype(np.int64)
    vel = velocity_from_counts(counts, dt, window_samples=300, unit=VelocityUnit.RPM)
    # En el interior (lejos de bordes) debe rondar 60 RPM.
    mid = vel[fs // 2]
    assert mid == pytest.approx(60.0, rel=0.05)
