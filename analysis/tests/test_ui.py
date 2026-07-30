"""Tests de la GUI (se saltan si no hay display disponible).

Construyen la ventana real, inyectan una caché y ejercitan el cableado de
controles → gráficas → estadísticos sin entrar en el bucle de eventos.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Sin display")


def _build_app(tmp_path, motor=None, name="cache.h5"):
    import matplotlib
    matplotlib.use("TkAgg")
    from analysis.processing import build_cache
    from analysis.ui.main_window import MainWindow

    from ._fakes import FakeReader, spinning_quadrature

    a, b = spinning_quadrature(cycles=20, samples_per_state=150)
    n = a.shape[0]
    elec = {f"A-{i:03d}": np.sin(np.linspace(0, 10 + i, n)) * (30 + i) for i in range(6)}
    cache = str(tmp_path / name)
    mot = None if motor is None else motor[:n]
    build_cache(FakeReader(a, b, elec, fs=30000.0, motor=mot), cache)

    app = MainWindow()
    app.update_idletasks()
    app._set_busy(True, "cargando")
    app._on_cache_ready(cache)
    app.update()
    return app


@pytest.fixture()
def app_with_cache(tmp_path):
    app = _build_app(tmp_path)
    yield app
    app._on_close()


@pytest.fixture()
def app_with_motor(tmp_path):
    """App con una grabación que sí trae el espejo STEP."""
    from analysis.motor import step_train

    motor = step_train(30.0, 1.0, 1.0 / 30000.0)
    app = _build_app(tmp_path, motor=motor, name="motor.h5")
    yield app
    app._on_close()


def test_electrodes_populated_and_preselected(app_with_cache):
    app = app_with_cache
    assert app.controls._listbox.size() == 6
    assert app.controls.get_selected_electrodes() == ["A-000", "A-001", "A-002"]


def test_session_and_window_stats_shown(app_with_cache):
    app = app_with_cache
    assert app.stats._session_lbl.cget("text") != "—"
    assert len(app.stats._window_tree.get_children()) == 7
    assert len(app.stats._session_tree.get_children()) == 7


def test_changing_units_redraws(app_with_cache):
    app = app_with_cache
    app.controls.vel_unit.set("rad/s")
    app.controls.angle_unit.set("rad")
    app._on_settings_changed()
    app.update()
    assert app.plot.ax_vel.get_ylabel() == "Vel. encoder (rad/s)"
    assert app.plot.ax_ang.get_ylabel() == "Ángulo (rad)"


def test_navigation_step(app_with_cache):
    app = app_with_cache
    app.controls.window_len.set("0.2")
    app._redraw()
    start_before = app.controls.get_start_s()
    app.controls._step(1)
    app.update()
    assert app.controls.get_start_s() >= start_before


def test_export_from_app(app_with_cache, tmp_path):
    from analysis.exporter import export
    app = app_with_cache
    out = str(tmp_path / "out.csv")
    export(app._cache, out, app.controls.get_angle_unit(), app.controls.get_vel_unit(),
           app._window_samples(), electrodes=app.controls.get_selected_electrodes())
    assert os.path.exists(out)


# ── señal del motor en la UI ─────────────────────────────────────


def test_motor_axis_says_so_when_there_is_no_signal(app_with_cache):
    app = app_with_cache
    assert app._cache is not None and app._cache.has_motor is False
    assert app.plot.ax_motor.get_ylabel() == "Motor (RPM)"
    # El resumen del motor debe indicarlo explícitamente, no quedarse en blanco.
    assert "sin señal" in app.stats._motor_lbl.cget("text").lower()


def test_motor_axis_is_drawn_when_the_signal_exists(app_with_motor):
    app = app_with_motor
    assert app._cache is not None and app._cache.has_motor is True
    # Dos trazas: comandada (STEP) y medida (encoder ÷ relación).
    assert len(app.plot.ax_motor.get_lines()) == 2
    labels = [ln.get_label() for ln in app.plot.ax_motor.get_lines()]
    assert any("Comandada" in str(x) for x in labels)


def test_motor_summary_shows_commanded_speed(app_with_motor):
    app = app_with_motor
    text = app.stats._motor_lbl.cget("text")
    assert "30.0" in text and "RPM" in text


def test_gear_ratio_is_measured_and_adopted_on_load(app_with_motor):
    app = app_with_motor
    assert "Medido:" in app.controls._ratio_lbl.cget("text")
    # La relación adoptada debe ser la medida, no la de por defecto.
    assert app._gear_est is not None and app._gear_est.ratio is not None
    assert app.controls.get_gear_ratio() == pytest.approx(app._gear_est.ratio, rel=1e-3)
    assert len(app.stats._gear_tree.get_children()) == 6


def test_changing_gear_ratio_redraws_motor_axis(app_with_motor):
    app = app_with_motor
    app.controls.set_gear_ratio(4.0)
    app._on_settings_changed()
    app.update()
    labels = [str(ln.get_label()) for ln in app.plot.ax_motor.get_lines()]
    assert any("÷ 4" in x for x in labels)


# ── tira de vista general ────────────────────────────────────────


def test_overview_strip_draws_the_whole_session(app_with_cache):
    app = app_with_cache
    assert app.overview._duration == pytest.approx(app._cache.duration_s)
    assert len(app.overview.ax.get_lines()) == 1
    # Sin señal de motor la tira muestra la velocidad del encoder.
    assert app.overview._label == "RPM encoder"
    assert app.overview.ax.get_xlim()[1] == pytest.approx(app._cache.duration_s)


def test_overview_strip_prefers_the_motor_signal(app_with_motor):
    assert app_with_motor.overview._label == "RPM motor (consigna)"


def test_overview_strip_highlights_the_visible_window(app_with_cache):
    app = app_with_cache
    app.controls.window_len.set("0.1")
    app._redraw()
    app.update()
    assert app.overview._span is not None
    t0, t1 = app.overview._span
    assert t1 > t0


def test_seeking_from_the_strip_moves_the_window(app_with_cache):
    app = app_with_cache
    app.controls.window_len.set("0.1")
    app._redraw()
    target = app._cache.duration_s * 0.5
    app._on_seek(target)
    app.update()
    # La ventana queda centrada en el instante pedido (con recorte a los bordes).
    start = app.controls.get_start_s()
    assert start == pytest.approx(target - 0.05, abs=0.02)


def test_seek_is_clamped_to_the_session(app_with_cache):
    app = app_with_cache
    app.controls.window_len.set("0.1")
    app._on_seek(-10.0)
    assert app.controls.get_start_s() == 0.0
    app._on_seek(1e6)
    assert app.controls.get_start_s() <= app._cache.duration_s


def test_export_with_motor_columns_from_app(app_with_motor, tmp_path):
    import pandas as pd
    from analysis.exporter import export

    app = app_with_motor
    out = str(tmp_path / "motor_out.csv")
    export(app._cache, out, app.controls.get_angle_unit(), app.controls.get_vel_unit(),
           app._window_samples(), electrodes=["A-000"],
           gear_ratio=app.controls.get_gear_ratio())
    df = pd.read_csv(out, skiprows=[1])
    assert "motor_rpm" in df.columns
    assert np.isclose(np.median(df["motor_rpm"]), 30.0, rtol=0.05)
