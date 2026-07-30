"""Estadísticos de velocidad angular y resumen del motor (sesión y ventana)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gearing import slip_fraction


@dataclass(frozen=True)
class VelocityStats:
    """Resumen estadístico de una serie de velocidad angular.

    ``mean`` es el promedio con signo (equivale al desplazamiento neto sobre el
    tiempo); ``mean_abs`` promedia la magnitud (útil si el sentido cambia).
    """

    n: int
    mean: float
    mean_abs: float
    std: float
    vmin: float
    vmax: float
    median: float
    unit: str

    def as_rows(self) -> list[tuple[str, str]]:
        """Filas (etiqueta, valor) listas para una tabla de la UI."""
        u = self.unit
        return [
            ("Muestras", f"{self.n}"),
            ("Media (con signo)", f"{self.mean:.3f} {u}"),
            ("Media |·|", f"{self.mean_abs:.3f} {u}"),
            ("Desv. típica", f"{self.std:.3f} {u}"),
            ("Mínimo", f"{self.vmin:.3f} {u}"),
            ("Máximo", f"{self.vmax:.3f} {u}"),
            ("Mediana", f"{self.median:.3f} {u}"),
        ]


def describe(velocity: np.ndarray, unit: str) -> VelocityStats:
    """Calcula los estadísticos de una serie de velocidad angular."""
    v = np.asarray(velocity, dtype=np.float64)
    if v.size == 0:
        return VelocityStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, unit)
    return VelocityStats(
        n=int(v.size),
        mean=float(np.mean(v)),
        mean_abs=float(np.mean(np.abs(v))),
        std=float(np.std(v)),
        vmin=float(np.min(v)),
        vmax=float(np.max(v)),
        median=float(np.median(v)),
        unit=unit,
    )


@dataclass(frozen=True)
class MotorSummary:
    """Resumen del motor en una ventana: consigna, medida y deslizamiento.

    Dos decisiones que evitan cifras que se contradicen entre sí:

    1. Todo se calcula **solo sobre las muestras con el motor comandado**. Si se
       mezclaran los tramos parados, la velocidad medida bajaría por los ceros
       mientras el deslizamiento —no definido con el motor parado— seguiría
       diciendo 0 %. ``running_frac`` indica cuánto de la ventana iba en marcha.
    2. Se promedia (media, no mediana) y el deslizamiento se deriva de las dos
       cifras mostradas. La media sobre el tramo en marcha equivale a comparar
       **vueltas totales** comandadas contra vueltas medidas, que es exactamente
       la pregunta "¿perdió pasos?"; y derivar el deslizamiento de lo que se
       muestra garantiza que las tres cifras cuadren (la mediana de un cociente
       no es el cociente de las medianas).

    Para el detalle muestra a muestra está la columna ``slip`` del export, que sí
    usa :func:`~analysis.gearing.slip_fraction` punto por punto.
    """

    commanded_rpm: float | None    # RPM comandada al motor (espejo STEP)
    measured_rpm: float | None     # RPM del motor medida (encoder ÷ relación)
    slip_pct: float | None         # deslizamiento (%) — None si nunca hubo marcha
    running_frac: float            # fracción de la ventana con el motor comandado

    def as_text(self) -> str:
        """Una línea lista para la UI."""
        if self.commanded_rpm is None:
            return "motor parado en toda la ventana"
        meas = "—" if self.measured_rpm is None else f"{self.measured_rpm:.2f}"
        slip = "" if self.slip_pct is None else f"  ·  desliz. {self.slip_pct:.1f} %"
        return (f"{self.commanded_rpm:.2f} → {meas} RPM{slip}"
                f"  ({self.running_frac*100:.0f} % en marcha)")


def summarize_motor(
    commanded_rpm: np.ndarray,
    enc_rpm: np.ndarray,
    gear_ratio: float,
) -> MotorSummary:
    """Resume una ventana comparando consigna del motor y medida del encoder."""
    cmd = np.asarray(commanded_rpm, dtype=np.float64)
    enc = np.abs(np.asarray(enc_rpm, dtype=np.float64))
    if cmd.size == 0:
        return MotorSummary(None, None, None, 0.0)

    running = cmd > 0
    frac = float(running.mean())
    if not running.any():
        return MotorSummary(None, None, None, frac)

    commanded = float(np.mean(cmd[running]))
    measured = float(np.mean(enc[running])) / gear_ratio
    # Deslizamiento derivado de las dos cifras anteriores → siempre coherente.
    slip = slip_fraction(np.array([commanded]), np.array([measured * gear_ratio]), gear_ratio)
    return MotorSummary(
        commanded_rpm=commanded,
        measured_rpm=measured,
        slip_pct=float(slip[0] * 100.0),
        running_frac=frac,
    )
