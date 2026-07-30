"""API de análisis offline de grabaciones.

Sirve al panel "Análisis" del frontend. Todas las series salen **ya decimadas**
en el servidor (envolvente min/max), así que un tramo de millones de muestras
viaja como unos pocos miles de puntos.

Las rutas de archivo que manda el cliente se confinan a `MOTORINADOR_ANALYSIS_ROOT`
(ver `analysis_service.resolve_path`): el servidor no tiene autenticación y no
debe convertirse en un lector universal del disco.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..analysis_service import (
    PathOutsideRoot,
    WindowRequest,
    analysis_service,
    browse,
)
from ..config import settings
from ..models import GEAR_RATIO

router = APIRouter(prefix="/api/analysis")


# ── modelos de petición ──────────────────────────────────────────


class OpenPayload(BaseModel):
    path: str
    whole_session: bool = False


class WindowPayload(BaseModel):
    """Ventana visible y ajustes de cálculo.

    Los dos suavizados son distintos a propósito: el del encoder (`window_ms`) y
    el de la comparación con el motor (`motor_window_ms`), que necesita más
    promediado porque el tren de engranajes resuena. Ver analysis/README.md.
    """

    t0: float = Field(ge=0)
    t1: float = Field(gt=0)
    electrodes: list[str] = Field(default_factory=list, max_length=32)
    angle_unit: str = "grados"
    vel_unit: str = "RPM"
    window_ms: float = Field(default=50.0, gt=0, le=5000)
    motor_window_ms: float = Field(default=500.0, gt=0, le=10000)
    gear_ratio: float = Field(default=GEAR_RATIO, gt=0, le=100)
    wrap_angle: bool = False
    points: int = Field(default=2000, ge=50, le=8000)

    def to_request(self) -> WindowRequest:
        from analysis.units import AngleUnit, VelocityUnit

        try:
            angle = AngleUnit(self.angle_unit)
            vel = VelocityUnit(self.vel_unit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Unidad no válida: {exc}") from exc
        return WindowRequest(
            t0=self.t0, t1=self.t1, electrodes=self.electrodes,
            angle_unit=angle, vel_unit=vel,
            window_ms=self.window_ms, motor_window_ms=self.motor_window_ms,
            gear_ratio=self.gear_ratio, wrap_angle=self.wrap_angle,
            points=self.points,
        )


class ExportPayload(WindowPayload):
    out_path: str
    whole_session: bool = False


# ── navegador de archivos ────────────────────────────────────────


@router.get("/browse")
async def get_browse(path: str | None = None) -> dict:
    try:
        return browse(path)
    except PathOutsideRoot as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config")
async def get_config() -> dict:
    """Datos que el cliente necesita para arrancar (raíz permitida, límites)."""
    return {
        "root": str(settings.analysis_root_path),
        "max_points": settings.analysis_max_points,
        "gear_ratio_default": GEAR_RATIO,
    }


# ── ciclo de vida de la sesión ───────────────────────────────────


@router.post("/open")
async def post_open(payload: OpenPayload) -> dict:
    try:
        await analysis_service.open(payload.path, payload.whole_session)
    except PathOutsideRoot as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "state": analysis_service.progress().state}


@router.get("/progress")
async def get_progress() -> dict:
    p = analysis_service.progress()
    return {"state": p.state, "fraction": round(p.fraction, 4),
            "message": p.message, "path": p.path, "parts": p.parts}


@router.post("/close")
async def post_close() -> dict:
    analysis_service.close()
    return {"ok": True}


# ── datos ────────────────────────────────────────────────────────


@router.get("/meta")
async def get_meta() -> dict:
    try:
        return await analysis_service.meta()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/overview")
async def get_overview(points: int = Query(default=3000, ge=50, le=8000)) -> dict:
    try:
        return await analysis_service.overview(points)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/window")
async def post_window(payload: WindowPayload) -> dict:
    if payload.t1 <= payload.t0:
        raise HTTPException(status_code=422, detail="t1 debe ser mayor que t0")
    try:
        return await analysis_service.window(payload.to_request())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── exportación ──────────────────────────────────────────────────


@router.post("/export")
async def post_export(payload: ExportPayload) -> dict:
    try:
        out = await analysis_service.start_export(
            payload.out_path, payload.to_request(), payload.whole_session
        )
    except PathOutsideRoot as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "out_path": out}


@router.get("/export/progress")
async def get_export_progress() -> dict:
    p = analysis_service.export_progress()
    return {"state": p.state, "fraction": round(p.fraction, 4),
            "message": p.message, "out_path": p.out_path}
