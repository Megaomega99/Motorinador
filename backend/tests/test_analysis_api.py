"""Tests de la API de análisis offline.

No usan las grabaciones reales (1.3 GB): se fabrica una caché sintética con el
mismo `build_cache` que usa el servicio y se inyecta en el singleton, así se
ejercita la API completa sin depender de datos que pueden no estar.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.motor import step_train                       # noqa: E402
from analysis.processing import SessionCache, build_cache    # noqa: E402
from analysis.tests._fakes import FakeReader                 # noqa: E402
from analysis.units import COUNTS_PER_REV                    # noqa: E402
from app.analysis_service import (                           # noqa: E402
    PathOutsideRoot,
    analysis_service,
    browse,
    resolve_path,
)
from app.config import settings                              # noqa: E402
from app.main import app                                     # noqa: E402

FS = 30000.0
MOTOR_RPM = 30.0
RATIO = 2.0


def _build_synthetic_cache(path: str, dur_s: float = 2.0) -> int:
    """Caché con encoder y espejo STEP coherentes (ratio = 2.0)."""
    n = int(dur_s * FS)
    motor = step_train(MOTOR_RPM, dur_s, 1.0 / FS)[:n]
    phase = np.arange(n) / FS * (MOTOR_RPM * RATIO * COUNTS_PER_REV / 60.0) / 4.0
    quad = np.floor(np.mod(phase, 1.0) * 4).astype(int)
    a = np.isin(quad, (2, 3)).astype(float)
    b = np.isin(quad, (1, 2)).astype(float)
    elec = {"A-000": np.sin(np.linspace(0, 40, n)) * 100.0,
            "A-001": np.full(n, 5.0)}
    build_cache(FakeReader(a, b, elec, fs=FS, motor=motor), path, chunk_samples=20000)
    return n


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    analysis_service.close()


@pytest.fixture()
def session(tmp_path, client):
    """Inyecta una sesión ya construida en el servicio (sin pasar por /open)."""
    cache_path = str(tmp_path / "synthetic.h5")
    _build_synthetic_cache(cache_path)
    from app.analysis_service import Progress

    analysis_service._cache = SessionCache(cache_path)
    analysis_service._cache_path = cache_path
    analysis_service._progress = Progress(
        state="ready", fraction=1.0, path=cache_path, parts=1, message="listo"
    )
    yield client
    analysis_service.close()


# ── seguridad de rutas ───────────────────────────────────────────


def test_resolve_path_accepts_paths_inside_the_root() -> None:
    inside = resolve_path(str(settings.analysis_root_path / "analysis"))
    assert inside == settings.analysis_root_path / "analysis"


def test_resolve_path_defaults_to_the_root() -> None:
    assert resolve_path(None) == settings.analysis_root_path
    assert resolve_path("") == settings.analysis_root_path


@pytest.mark.parametrize("escape", ["/etc", "/etc/passwd", "../..", "../../../etc"])
def test_resolve_path_rejects_escaping_the_root(escape: str) -> None:
    with pytest.raises(PathOutsideRoot):
        resolve_path(escape)


def test_resolve_path_rejects_symlinks_out_of_the_root(tmp_path, monkeypatch) -> None:
    """Un symlink dentro de la raíz que apunte fuera tampoco debe colar."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secreto"
    outside.mkdir()
    (outside / "x.rhs").write_bytes(b"x")
    (root / "atajo").symlink_to(outside)
    monkeypatch.setattr(settings, "analysis_root", str(root))

    with pytest.raises(PathOutsideRoot):
        resolve_path(str(root / "atajo" / "x.rhs"))


def test_browse_endpoint_rejects_paths_outside_the_root(client) -> None:
    assert client.get("/api/analysis/browse", params={"path": "/etc"}).status_code == 403


def test_open_endpoint_rejects_paths_outside_the_root(client) -> None:
    r = client.post("/api/analysis/open", json={"path": "/etc/passwd"})
    assert r.status_code == 403


# ── navegador de archivos ────────────────────────────────────────


def test_browse_lists_dirs_and_openable_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_root", str(tmp_path))
    (tmp_path / "sub").mkdir()
    (tmp_path / "toma.rhs").write_bytes(b"x")
    (tmp_path / "notas.md").write_text("no abrible")
    (tmp_path / ".oculto").write_text("x")

    out = browse(None)
    assert [d["name"] for d in out["dirs"]] == ["sub"]
    assert [f["name"] for f in out["files"]] == ["toma.rhs"]
    assert out["parent"] is None          # estamos en la raíz
    assert out["root"] == str(tmp_path.resolve())


def test_browse_counts_session_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_root", str(tmp_path))
    folder = tmp_path / "sesion"
    folder.mkdir()
    for i in range(4):
        (folder / f"t_14{i:02d}.rhs").write_bytes(b"x")

    listing = browse(None)
    assert listing["dirs"][0]["session_files"] == 4
    inner = browse(str(folder))
    assert inner["is_session"] is True and inner["session_files"] == 4
    assert inner["parent"] == str(tmp_path.resolve())


def test_config_endpoint_reports_the_root(client) -> None:
    cfg = client.get("/api/analysis/config").json()
    assert cfg["root"] == str(settings.analysis_root_path)
    assert cfg["max_points"] == settings.analysis_max_points


# ── sin sesión abierta ───────────────────────────────────────────


def test_endpoints_report_conflict_without_a_session(client) -> None:
    assert client.get("/api/analysis/progress").json()["state"] == "idle"
    assert client.get("/api/analysis/meta").status_code == 409
    assert client.get("/api/analysis/overview").status_code == 409
    body = {"t0": 0.0, "t1": 1.0}
    assert client.post("/api/analysis/window", json=body).status_code == 409


# ── metadatos y relación de engranajes ───────────────────────────


def test_meta_describes_the_session(session) -> None:
    meta = session.get("/api/analysis/meta").json()
    assert meta["has_motor"] is True
    assert meta["sample_rate_hz"] == FS
    assert meta["electrodes"] == ["A-000", "A-001"]
    assert meta["duration_s"] == pytest.approx(2.0, rel=1e-3)


def test_meta_measures_the_gear_ratio(session) -> None:
    gearing = session.get("/api/analysis/meta").json()["gearing"]
    assert gearing is not None
    assert gearing["ratio"] == pytest.approx(RATIO, rel=0.05)
    assert gearing["n_stall"] == 0


# ── vista general ────────────────────────────────────────────────


def test_overview_returns_a_decimated_series(session) -> None:
    ov = session.get("/api/analysis/overview", params={"points": 400}).json()
    assert ov["kind"] == "motor"
    assert len(ov["t"]) == len(ov["y"]) <= 400
    assert ov["duration_s"] == pytest.approx(2.0, rel=1e-3)
    # La consigna del tren sintético es constante a 30 RPM.
    assert np.isclose(np.median(ov["y"]), MOTOR_RPM, rtol=0.05)


def test_overview_points_are_clamped(session) -> None:
    assert session.get("/api/analysis/overview", params={"points": 99999}).status_code == 422
    ov = session.get("/api/analysis/overview", params={"points": 50}).json()
    assert len(ov["t"]) <= 50


# ── ventana ──────────────────────────────────────────────────────


def _window(client, **kw):
    body = {"t0": 0.5, "t1": 1.5, "electrodes": ["A-000"], "points": 500}
    body.update(kw)
    r = client.post("/api/analysis/window", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_window_returns_every_series(session) -> None:
    w = _window(session)
    assert set(w) >= {"t0", "t1", "angle", "velocity", "electrodes", "motor", "stats"}
    for series in (w["angle"], w["velocity"], w["motor"]["commanded"]):
        assert len(series["t"]) == len(series["y"]) <= 500
    assert "A-000" in w["electrodes"]
    assert w["sample_range"] == [int(0.5 * FS), int(1.5 * FS)]


def test_window_motor_summary_is_coherent(session) -> None:
    """Consigna, medida y deslizamiento deben cuadrar entre sí."""
    s = _window(session, gear_ratio=RATIO)["motor"]["summary"]
    assert s["commanded_rpm"] == pytest.approx(MOTOR_RPM, rel=0.02)
    assert s["measured_rpm"] == pytest.approx(MOTOR_RPM, rel=0.05)
    assert s["slip_pct"] < 5.0
    assert s["running_frac"] == pytest.approx(1.0)


def test_window_gear_ratio_changes_the_measured_trace(session) -> None:
    """Duplicar la relación debe mitad la velocidad medida referida al motor."""
    a = _window(session, gear_ratio=RATIO)["motor"]["measured"]["y"]
    b = _window(session, gear_ratio=RATIO * 2)["motor"]["measured"]["y"]
    assert np.median(a) == pytest.approx(np.median(b) * 2, rel=0.02)


def test_window_only_returns_requested_electrodes(session) -> None:
    w = _window(session, electrodes=["A-001"])
    assert list(w["electrodes"]) == ["A-001"]
    assert np.allclose(w["electrodes"]["A-001"]["y"], 5.0)


def test_window_ignores_unknown_electrodes(session) -> None:
    w = _window(session, electrodes=["A-000", "NOPE"])
    assert list(w["electrodes"]) == ["A-000"]


def test_window_units_are_applied(session) -> None:
    deg = _window(session, angle_unit="grados")
    rad = _window(session, angle_unit="rad")
    assert deg["angle_unit"] == "grados" and rad["angle_unit"] == "rad"
    assert abs(np.max(deg["angle"]["y"])) > abs(np.max(rad["angle"]["y"]))


def test_window_rejects_bad_input(session) -> None:
    assert session.post("/api/analysis/window",
                        json={"t0": 1.0, "t1": 0.5}).status_code == 422
    assert session.post("/api/analysis/window",
                        json={"t0": 0.0, "t1": 1.0, "gear_ratio": 0}).status_code == 422
    assert session.post("/api/analysis/window",
                        json={"t0": 0.0, "t1": 1.0, "angle_unit": "leguas"}).status_code == 422


def test_window_is_clamped_to_the_session(session) -> None:
    w = _window(session, t0=0.0, t1=99999.0)
    assert w["t1"] == pytest.approx(2.0, rel=1e-3)


# ── exportación ──────────────────────────────────────────────────


def _wait_export(client, timeout=20.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = client.get("/api/analysis/export/progress").json()
        if p["state"] in ("ready", "error"):
            return p
        time.sleep(0.05)
    raise AssertionError("la exportación no terminó")


def test_export_range_writes_the_file(session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_root", str(tmp_path))
    out = tmp_path / "tramo.csv"
    r = session.post("/api/analysis/export", json={
        "t0": 0.5, "t1": 0.7, "out_path": str(out), "electrodes": ["A-000"],
        "gear_ratio": RATIO,
    })
    assert r.status_code == 200, r.text
    assert _wait_export(session)["state"] == "ready"

    import pandas as pd
    df = pd.read_csv(out, skiprows=[1])
    assert len(df) == pytest.approx(0.2 * FS, abs=2)
    for col in ("motor_rpm", "slip", "step_count", "A-000"):
        assert col in df.columns
    assert np.isclose(np.median(df["motor_rpm"]), MOTOR_RPM, rtol=0.05)


def test_export_rejects_destination_outside_the_root(session) -> None:
    r = session.post("/api/analysis/export",
                     json={"t0": 0.0, "t1": 1.0, "out_path": "/etc/x.csv"})
    assert r.status_code == 403


def test_export_without_session_conflicts(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_root", str(tmp_path))
    r = client.post("/api/analysis/export",
                    json={"t0": 0.0, "t1": 1.0, "out_path": str(tmp_path / "x.csv")})
    assert r.status_code == 409


# ── cierre ───────────────────────────────────────────────────────


def test_close_frees_the_session_and_deletes_the_cache(session, tmp_path) -> None:
    cache_path = analysis_service._cache_path
    assert cache_path and pathlib.Path(cache_path).exists()
    assert session.post("/api/analysis/close").json() == {"ok": True}
    assert not pathlib.Path(cache_path).exists()
    assert session.get("/api/analysis/meta").status_code == 409


def test_open_rejects_a_missing_path(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_root", str(tmp_path))
    r = client.post("/api/analysis/open", json={"path": str(tmp_path / "no_existe.rhs")})
    assert r.status_code == 404


def test_open_is_rejected_while_another_build_runs(client, monkeypatch) -> None:
    from app.analysis_service import Progress
    monkeypatch.setattr(analysis_service, "_progress", Progress(state="building"))
    r = client.post("/api/analysis/open", json={"path": "."})
    assert r.status_code == 409
