"""Tests de la GUI (se saltan si no hay display disponible).

Construyen la ventana real, inyectan una caché y ejercitan el cableado de
controles → gráficas → estadísticos sin entrar en el bucle de eventos.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Sin display")


@pytest.fixture()
def app_with_cache(tmp_path):
    import matplotlib
    matplotlib.use("TkAgg")
    from analysis.processing import build_cache
    from analysis.ui.main_window import MainWindow

    from ._fakes import FakeReader, spinning_quadrature

    a, b = spinning_quadrature(cycles=20, samples_per_state=150)
    n = a.shape[0]
    elec = {f"A-{i:03d}": np.sin(np.linspace(0, 10 + i, n)) * (30 + i) for i in range(6)}
    cache = str(tmp_path / "cache.h5")
    build_cache(FakeReader(a, b, elec, fs=30000.0), cache)

    app = MainWindow()
    app.update_idletasks()
    app._set_busy(True, "cargando")
    app._on_cache_ready(cache)
    app.update()
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
    assert app.plot.ax_vel.get_ylabel() == "Velocidad (rad/s)"
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
