"""Tests del resumen del motor (consigna vs medida vs deslizamiento)."""

from __future__ import annotations

import numpy as np

from analysis.stats import describe, summarize_motor


def test_describe_empty_series():
    st = describe(np.empty(0), "RPM")
    assert st.n == 0 and st.mean == 0.0 and st.unit == "RPM"


def test_summary_when_motor_follows_the_command():
    cmd = np.full(100, 5.0)
    enc = np.full(100, 5.0 * 1.98)
    s = summarize_motor(cmd, enc, 1.98)
    assert s.commanded_rpm == 5.0
    assert np.isclose(s.measured_rpm, 5.0)
    assert np.isclose(s.slip_pct, 0.0)
    assert s.running_frac == 1.0


def test_summary_ignores_the_stopped_part_of_the_window():
    """Mezclar tramos parados no debe hundir la mediana de la velocidad medida.

    Es el caso real de la toma: en una ventana de 10 s el motor solo corre 6.4 s.
    Si se promediaran los ceros, la "medida" saldría muy por debajo de la
    consigna y el deslizamiento diría 0 % — cifras que se contradicen.
    """
    cmd = np.concatenate([np.zeros(40), np.full(60, 5.0)])
    enc = np.concatenate([np.zeros(40), np.full(60, 5.0 * 1.98)])
    s = summarize_motor(cmd, enc, 1.98)
    assert s.commanded_rpm == 5.0
    assert np.isclose(s.measured_rpm, 5.0)          # no arrastrada por los ceros
    assert np.isclose(s.slip_pct, 0.0)
    assert np.isclose(s.running_frac, 0.6)


def test_summary_detects_a_blocked_shaft():
    cmd = np.full(50, 5.0)
    enc = np.zeros(50)
    s = summarize_motor(cmd, enc, 1.98)
    assert np.isclose(s.slip_pct, 100.0)
    assert np.isclose(s.measured_rpm, 0.0)


def test_summary_when_the_motor_never_runs():
    s = summarize_motor(np.zeros(50), np.zeros(50), 1.98)
    assert s.commanded_rpm is None and s.slip_pct is None
    assert s.running_frac == 0.0
    assert "parado" in s.as_text()


def test_summary_of_an_empty_window():
    s = summarize_motor(np.empty(0), np.empty(0), 1.98)
    assert s.commanded_rpm is None and s.running_frac == 0.0


def test_summary_text_is_readable():
    s = summarize_motor(np.full(10, 5.0), np.full(10, 9.9), 1.98)
    txt = s.as_text()
    assert "5.00" in txt and "RPM" in txt and "%" in txt


def test_summary_uses_encoder_magnitude():
    """Girar en reversa no debe contar como deslizamiento del 100 %."""
    s = summarize_motor(np.full(10, 5.0), np.full(10, -5.0 * 1.98), 1.98)
    assert np.isclose(s.slip_pct, 0.0)


def test_summary_figures_are_mutually_consistent():
    """El deslizamiento mostrado debe cuadrar con las dos velocidades mostradas.

    Con el encoder bimodal (mitad a la velocidad esperada, mitad a la mitad) la
    mediana de los deslizamientos por muestra y el cociente de las medianas dan
    resultados distintos; el resumen debe ser coherente con lo que enseña.
    """
    ratio = 1.98
    cmd = np.full(200, 5.0)
    enc = np.concatenate([np.full(100, 5.0 * ratio), np.full(100, 2.5 * ratio)])
    s = summarize_motor(cmd, enc, ratio)
    expected_slip = (1.0 - s.measured_rpm / s.commanded_rpm) * 100.0
    assert np.isclose(s.slip_pct, expected_slip)
    assert np.isclose(s.measured_rpm, 3.75)      # media de 5.0 y 2.5
    assert np.isclose(s.slip_pct, 25.0)
