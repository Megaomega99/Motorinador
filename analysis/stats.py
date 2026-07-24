"""Estadísticos de la velocidad angular (sesión completa y ventana visible)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


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
