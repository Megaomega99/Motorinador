"""Servicio de análisis offline: envuelve el paquete `analysis/` para la API web.

Reutiliza **el mismo motor** que la app de escritorio (`analysis.processing`,
`analysis.motor`, `analysis.gearing`, `analysis.exporter`); aquí no se recalcula
nada, solo se adapta a HTTP:

  · **Una sesión abierta a la vez.** Cada sesión son ~230 MB de conteos en RAM y
    una caché HDF5 de ~1.4 GB en disco; abrir otra cierra y borra la anterior.
  · **Construcción en segundo plano** con progreso consultable, porque la pasada
    inicial recorre 1.3 GB.
  · **Lecturas serializadas.** `h5py` no es thread-safe: todo acceso a la caché
    pasa por un lock y corre en un hilo aparte para no bloquear el bucle async.
  · **Rutas confinadas** a `settings.analysis_root` (ver :func:`resolve_path`):
    la API no tiene autenticación, así que no puede servir de lector universal
    del disco.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

# El paquete `analysis` vive en la raíz del repo, un nivel por encima de backend/.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from analysis.exporter import export as export_session          # noqa: E402
from analysis.gearing import enc_rpm_to_motor_rpm               # noqa: E402
from analysis.processing import SessionCache, build_cache       # noqa: E402
from analysis.readers.factory import open_reader                # noqa: E402
from analysis.readers.session import session_files              # noqa: E402
from analysis.units import (                                    # noqa: E402
    GEAR_RATIO_DEFAULT,
    AngleUnit,
    VelocityUnit,
)

from .config import settings  # noqa: E402

logger = logging.getLogger(__name__)

JobState = Literal["idle", "building", "ready", "error"]

# Extensiones que el navegador de archivos ofrece como abribles.
OPENABLE_EXTS = frozenset({".rhs", ".rhd", ".txt", ".csv", ".tsv"})


class PathOutsideRoot(ValueError):
    """La ruta pedida cae fuera de `analysis_root`."""


def resolve_path(raw: str | None) -> pathlib.Path:
    """Resuelve una ruta de cliente y garantiza que esté dentro de la raíz.

    Se resuelve primero (siguiendo symlinks) y luego se comprueba la
    pertenencia, de modo que ni `../../etc` ni un enlace simbólico que apunte
    fuera consiguen escapar.
    """
    root = settings.analysis_root_path
    candidate = root if not raw else pathlib.Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathOutsideRoot(
            f"Ruta fuera de la carpeta permitida ({root}): {raw!r}"
        )
    return resolved


@dataclass
class Progress:
    """Estado del trabajo en curso, consultable desde la API."""

    state: JobState = "idle"
    fraction: float = 0.0
    message: str = ""
    path: str | None = None
    parts: int = 0


@dataclass
class ExportProgress:
    state: JobState = "idle"
    fraction: float = 0.0
    message: str = ""
    out_path: str | None = None


@dataclass
class WindowRequest:
    """Parámetros de una ventana de análisis (todo lo que el cliente puede pedir)."""

    t0: float
    t1: float
    electrodes: list[str] = field(default_factory=list)
    angle_unit: AngleUnit = AngleUnit.DEG
    vel_unit: VelocityUnit = VelocityUnit.RPM
    window_ms: float = 50.0
    motor_window_ms: float = 500.0
    gear_ratio: float = GEAR_RATIO_DEFAULT
    wrap_angle: bool = False
    points: int = 2000


class AnalysisService:
    def __init__(self) -> None:
        self._cache: SessionCache | None = None
        self._cache_path: str | None = None
        self._lock = threading.Lock()          # protege el acceso a h5py
        self._progress = Progress()
        self._export = ExportProgress()
        self._task: asyncio.Task | None = None
        self._export_task: asyncio.Task | None = None

    # ── estado ───────────────────────────────────────────────────
    @property
    def ready(self) -> bool:
        return self._cache is not None and self._progress.state == "ready"

    def progress(self) -> Progress:
        return self._progress

    def export_progress(self) -> ExportProgress:
        return self._export

    def _require(self) -> SessionCache:
        if self._cache is None or self._progress.state != "ready":
            raise RuntimeError("No hay ninguna sesión abierta")
        return self._cache

    # ── apertura ─────────────────────────────────────────────────
    async def open(self, raw_path: str, whole_session: bool) -> None:
        """Arranca la construcción de la caché en segundo plano."""
        if self._progress.state == "building":
            raise RuntimeError("Ya hay una sesión procesándose")
        path = resolve_path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe: {path}")

        self.close()
        self._progress = Progress(state="building", fraction=0.0,
                                  message=f"Procesando {path.name}...", path=str(path))
        self._task = asyncio.create_task(self._build(str(path), whole_session))

    async def _build(self, path: str, whole_session: bool) -> None:
        try:
            cache_path = await asyncio.to_thread(self._build_blocking, path, whole_session)
            with self._lock:
                self._cache = SessionCache(cache_path)
                self._cache_path = cache_path
                cache = self._cache
            self._progress = Progress(
                state="ready", fraction=1.0, path=path, parts=cache.n_parts,
                message=(f"{cache.n_samples} muestras · {cache.duration_s:.2f} s"
                         + (f" · {cache.n_parts} archivos" if cache.n_parts > 1 else "")
                         + (" · con señal de motor" if cache.has_motor
                            else " · SIN señal de motor")),
            )
        except Exception as exc:  # noqa: BLE001 — se reporta al cliente
            logger.exception("Fallo al procesar la grabación")
            self._progress = Progress(state="error", message=str(exc), path=path)

    def _build_blocking(self, path: str, whole_session: bool) -> str:
        reader = open_reader(path, whole_session=whole_session)
        fd, cache_path = tempfile.mkstemp(suffix=".h5", prefix="motorinador_cache_")
        os.close(fd)

        def on_progress(f: float) -> None:
            self._progress.fraction = min(1.0, f)

        build_cache(reader, cache_path, progress_cb=on_progress)
        return cache_path

    def close(self) -> None:
        """Cierra la sesión y borra su caché temporal."""
        with self._lock:
            if self._cache is not None:
                self._cache.close()
                self._cache = None
            if self._cache_path and os.path.exists(self._cache_path):
                try:
                    os.remove(self._cache_path)
                except OSError:
                    logger.warning("No se pudo borrar la caché %s", self._cache_path)
            self._cache_path = None
        self._progress = Progress()
        self._export = ExportProgress()

    # ── lectura (todo en hilo + lock: h5py no es thread-safe) ────
    async def meta(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._meta_blocking)

    def _meta_blocking(self) -> dict[str, Any]:
        with self._lock:
            c = self._require()
            est = c.gear_estimate() if c.has_motor else None
            return {
                "path": self._progress.path,
                "n_samples": c.n_samples,
                "duration_s": c.duration_s,
                "sample_rate_hz": c.sample_rate_hz,
                "n_parts": c.n_parts,
                "electrodes": list(c.electrode_names),
                "has_motor": c.has_motor,
                "motor_channel": c.motor_channel,
                "gearing": None if est is None else {
                    "ratio": est.ratio,
                    "median_ratio": est.median_ratio,
                    "n_steady": est.n_steady,
                    "n_stall": est.n_stall,
                    "stall_pct": est.stall_pct,
                    "motor_revs": est.motor_revs,
                    "enc_revs": est.enc_revs,
                },
            }

    async def overview(self, points: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._overview_blocking, points)

    def _overview_blocking(self, points: int) -> dict[str, Any]:
        points = _clamp_points(points)
        with self._lock:
            c = self._require()
            if c.has_motor:
                ov = c.motor_rpm_overview(max_points=points)
                label, kind = "RPM motor (consigna)", "motor"
            else:
                win = max(1, int(0.05 * c.sample_rate_hz))
                ov = c.velocity_overview(VelocityUnit.RPM, win, max_points=points)
                label, kind = "RPM encoder", "encoder"
            return {
                "kind": kind,
                "label": label,
                "duration_s": c.duration_s,
                "t": _round(ov.t, 4),
                "y": _round(ov.y, 3),
            }

    async def window(self, req: WindowRequest) -> dict[str, Any]:
        return await asyncio.to_thread(self._window_blocking, req)

    def _window_blocking(self, req: WindowRequest) -> dict[str, Any]:
        from analysis.processing import decimate_minmax

        points = _clamp_points(req.points)
        with self._lock:
            c = self._require()
            i0 = c.sample_at(req.t0)
            i1 = c.clamp(max(i0 + 1, c.sample_at(req.t1)))
            win = max(1, int(round(req.window_ms / 1000.0 * c.sample_rate_hz)))
            motor_win = max(1, int(round(req.motor_window_ms / 1000.0 * c.sample_rate_hz)))
            t = c.time_slice(i0, i1)

            def dec(y):
                d = decimate_minmax(t, y, points)
                return {"t": _round(d.t, 5), "y": _round(d.y, 4)}

            out: dict[str, Any] = {
                "t0": i0 * c.dt,
                "t1": i1 * c.dt,
                "n_samples": i1 - i0,
                "sample_range": [i0, i1],
                "angle": dec(c.angle_slice(i0, i1, req.angle_unit, wrap=req.wrap_angle)),
                "angle_unit": req.angle_unit.value,
                "velocity": dec(c.velocity_slice(i0, i1, req.vel_unit, win)),
                "vel_unit": req.vel_unit.value,
                "electrodes": {
                    name: dec(c.electrode_slice(name, i0, i1))
                    for name in req.electrodes if name in c.electrode_names
                },
                "stats": _stats_dict(c.window_stats(i0, i1, req.vel_unit, win)),
            }

            if c.has_motor:
                enc = c.velocity_slice(i0, i1, VelocityUnit.RPM, motor_win)
                summary = c.motor_summary(i0, i1, req.gear_ratio, motor_win)
                out["motor"] = {
                    "commanded": dec(c.motor_rpm_slice(i0, i1)),
                    "measured": dec(enc_rpm_to_motor_rpm(abs(enc), req.gear_ratio)),
                    "summary": {
                        "commanded_rpm": summary.commanded_rpm,
                        "measured_rpm": summary.measured_rpm,
                        "slip_pct": summary.slip_pct,
                        "running_frac": summary.running_frac,
                        "text": summary.as_text(),
                    },
                }
            else:
                out["motor"] = None
            return out

    # ── exportación ──────────────────────────────────────────────
    async def start_export(
        self, raw_out: str, req: WindowRequest, whole_session: bool
    ) -> str:
        if self._export.state == "building":
            raise RuntimeError("Ya hay una exportación en curso")
        self._require()
        out = resolve_path(raw_out)
        if out.is_dir():
            raise ValueError("El destino debe ser un archivo, no una carpeta")
        out.parent.mkdir(parents=True, exist_ok=True)

        self._export = ExportProgress(state="building", message=f"Exportando a {out.name}...",
                                      out_path=str(out))
        self._export_task = asyncio.create_task(
            self._run_export(str(out), req, whole_session)
        )
        return str(out)

    async def _run_export(self, out: str, req: WindowRequest, whole_session: bool) -> None:
        try:
            await asyncio.to_thread(self._export_blocking, out, req, whole_session)
            self._export = ExportProgress(state="ready", fraction=1.0, out_path=out,
                                          message=f"Escrito: {os.path.basename(out)}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fallo al exportar")
            self._export = ExportProgress(state="error", message=str(exc), out_path=out)

    def _export_blocking(self, out: str, req: WindowRequest, whole_session: bool) -> None:
        with self._lock:
            c = self._require()
            win = max(1, int(round(req.window_ms / 1000.0 * c.sample_rate_hz)))
            motor_win = max(1, int(round(req.motor_window_ms / 1000.0 * c.sample_rate_hz)))
            rng = None
            if not whole_session:
                rng = (c.sample_at(req.t0), c.sample_at(req.t1))

            def on_progress(f: float) -> None:
                self._export.fraction = min(1.0, f)

            export_session(
                c, out, req.angle_unit, req.vel_unit, win,
                electrodes=req.electrodes or None,
                gear_ratio=req.gear_ratio,
                motor_window_samples=motor_win,
                sample_range=rng,
                progress_cb=on_progress,
            )


# ── navegador de archivos ────────────────────────────────────────


def browse(raw_path: str | None) -> dict[str, Any]:
    """Lista carpetas y grabaciones abribles dentro de la raíz permitida."""
    path = resolve_path(raw_path)
    if not path.is_dir():
        path = path.parent
    root = settings.analysis_root_path

    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise ValueError(f"No se puede leer la carpeta: {exc}") from exc

    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                members = session_files(str(entry))
                dirs.append({
                    "name": entry.name,
                    "path": str(entry),
                    "session_files": len(members),
                })
            elif entry.suffix.lower() in OPENABLE_EXTS:
                files.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_mb": round(entry.stat().st_size / 1e6, 1),
                })
        except OSError:
            continue

    return {
        "path": str(path),
        "parent": None if path == root else str(path.parent),
        "root": str(root),
        "is_session": len(session_files(str(path))) > 1,
        "session_files": len(session_files(str(path))),
        "dirs": dirs,
        "files": files,
    }


# ── utilidades ───────────────────────────────────────────────────


def _clamp_points(points: int) -> int:
    return max(50, min(int(points), settings.analysis_max_points))


def _round(arr, decimals: int) -> list[float]:
    """Serie a lista de floats redondeada — recorta bastante el tamaño del JSON."""
    import numpy as np

    return np.round(np.asarray(arr, dtype=float), decimals).tolist()


def _stats_dict(stats) -> dict[str, Any]:
    return {
        "n": stats.n,
        "mean": stats.mean,
        "mean_abs": stats.mean_abs,
        "std": stats.std,
        "vmin": stats.vmin,
        "vmax": stats.vmax,
        "median": stats.median,
        "unit": stats.unit,
    }


analysis_service = AnalysisService()
