"""Relación de engranajes motor↔encoder y deslizamiento (pasos perdidos).

Desde que la transmisión pasa por engranajes, el encoder ya no mide el eje del
motor: da ``GEAR_RATIO`` vueltas por cada vuelta del motor. Como la grabación
tiene **las dos** señales —micropasos comandados (`ANALOG-IN-2`) y cuentas del
encoder (`DIGITAL-IN-01/02`)— la relación se puede medir en lugar de suponerla.

Además, comparar ambas delata lo que el encoder solo no puede ver: si el motor
**perdió pasos** o se atascó. Sobre la toma de referencia
(`intento serio 2_260729_142804`) esto ocurre en un 7.7 % de los segundos con
consigna constante, con un caso de bloqueo casi total (8 cuentas de encoder
frente a 187 micropasos comandados en un segundo).

Método de estimación (robusto por diseño):
  1. Trocear en ventanas de ``window_s``.
  2. Quedarse solo con las ventanas **estables**: consigna apreciable y constante
     respecto a sus vecinas (durante una rampa el motor no sigue al tren).
  3. Ratio de cada ventana = vueltas de encoder / vueltas de motor; tomar la mediana.
  4. Integrar vueltas solo sobre las ventanas dentro de ``tol`` de esa mediana:
     así los atascos quedan fuera del ratio y se cuentan aparte.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .units import COUNTS_PER_REV, STEPS_PER_REV


@dataclass(frozen=True)
class GearEstimate:
    """Resultado de estimar la relación de engranajes sobre una grabación."""

    ratio: float | None      # vueltas de encoder por vuelta de motor (None si no hay datos)
    median_ratio: float | None
    n_steady: int            # ventanas con consigna estable usadas
    n_stall: int             # ventanas estables con déficit de encoder (pasos perdidos)
    motor_revs: float        # vueltas de motor integradas en el ratio
    enc_revs: float          # vueltas de encoder integradas en el ratio

    @property
    def stall_pct(self) -> float:
        """Porcentaje de ventanas estables con pérdida de paso."""
        return 100.0 * self.n_stall / self.n_steady if self.n_steady else 0.0

    def as_rows(self) -> list[tuple[str, str]]:
        """Filas (etiqueta, valor) listas para una tabla de la UI."""
        ratio = "—" if self.ratio is None else f"{self.ratio:.4f}"
        median = "—" if self.median_ratio is None else f"{self.median_ratio:.4f}"
        return [
            ("Relación medida", f"{ratio} enc/motor"),
            ("Mediana por ventana", median),
            ("Ventanas estables", f"{self.n_steady}"),
            ("Con pérdida de paso", f"{self.n_stall} ({self.stall_pct:.1f} %)"),
            ("Vueltas motor", f"{self.motor_revs:.2f}"),
            ("Vueltas encoder", f"{self.enc_revs:.2f}"),
        ]


def estimate_gear_ratio(
    step_counts: np.ndarray,
    enc_counts: np.ndarray,
    dt: float,
    window_s: float = 1.0,
    min_steps: int = 20,
    tol: float = 0.15,
    steps_per_rev: int = STEPS_PER_REV,
    counts_per_rev: int = COUNTS_PER_REV,
) -> GearEstimate:
    """Estima vueltas de encoder por vuelta de motor. Ver el detalle arriba.

    Parameters
    ----------
    step_counts, enc_counts : np.ndarray
        Conteos acumulados de micropasos y de cuentas del encoder, misma longitud.
    dt : float
        Intervalo de muestreo en segundos.
    window_s : float
        Ancho de las ventanas de análisis.
    min_steps : int
        Micropasos mínimos en una ventana para considerarla en movimiento.
    tol : float
        Desviación relativa admitida respecto de la mediana para integrar.
    """
    if dt <= 0:
        raise ValueError("dt debe ser positivo")
    step = np.asarray(step_counts, dtype=np.int64)
    enc = np.asarray(enc_counts, dtype=np.int64)
    if step.shape != enc.shape:
        raise ValueError("step_counts y enc_counts deben tener la misma longitud")

    empty = GearEstimate(None, None, 0, 0, 0.0, 0.0)
    win = max(1, int(round(window_s / dt)))
    # Los bordes indexan muestras, así que la última ventana debe caber dentro
    # del array: n_win ventanas necesitan n_win*win + 1 muestras.
    n_win = (step.shape[0] - 1) // win
    if n_win < 3:
        return empty

    edges = np.arange(n_win + 1) * win
    d_step = np.diff(step[edges]).astype(np.float64)
    d_enc = np.abs(np.diff(enc[edges])).astype(np.float64)

    # Ventanas estables: en movimiento y con la consigna igual a la de sus vecinas.
    moving = d_step >= min_steps
    flat = np.zeros(n_win, dtype=bool)
    if n_win >= 3:
        same_prev = np.abs(d_step[1:-1] - d_step[:-2]) <= 0.02 * d_step[1:-1] + 2
        same_next = np.abs(d_step[1:-1] - d_step[2:]) <= 0.02 * d_step[1:-1] + 2
        flat[1:-1] = same_prev & same_next
    steady = moving & flat
    if not steady.any():
        return empty

    motor_revs = d_step / float(steps_per_rev)
    enc_revs = d_enc / float(counts_per_rev)
    ratios = np.divide(enc_revs, motor_revs, out=np.zeros_like(enc_revs),
                       where=motor_revs > 0)

    median = float(np.median(ratios[steady]))
    if median <= 0:
        return empty

    keep = steady & (ratios > median * (1.0 - tol)) & (ratios < median * (1.0 + tol))
    stall = int(np.count_nonzero(steady & (ratios <= median * (1.0 - tol))))
    if not keep.any():
        return GearEstimate(median, median, int(steady.sum()), stall, 0.0, 0.0)

    m_rev = float(motor_revs[keep].sum())
    e_rev = float(enc_revs[keep].sum())
    return GearEstimate(
        ratio=e_rev / m_rev if m_rev > 0 else None,
        median_ratio=median,
        n_steady=int(steady.sum()),
        n_stall=stall,
        motor_revs=m_rev,
        enc_revs=e_rev,
    )


def slip_fraction(
    motor_rpm: np.ndarray,
    enc_rpm: np.ndarray,
    gear_ratio: float,
) -> np.ndarray:
    """Fracción de deslizamiento por muestra: 0 = el motor sigue la consigna, 1 = eje bloqueado.

    ``slip = 1 − |ω_enc| / (gear_ratio · ω_motor_comandada)``. Con el motor parado
    el deslizamiento no está definido y se devuelve 0 (no infinito). Se recorta a
    [0, 1]: un encoder por encima de lo comandado (rebote, inercia) no es "pérdida
    de paso negativa".
    """
    if gear_ratio <= 0:
        raise ValueError("gear_ratio debe ser positivo")
    cmd = np.asarray(motor_rpm, dtype=np.float64)
    meas = np.abs(np.asarray(enc_rpm, dtype=np.float64))
    expected = cmd * gear_ratio
    slip = np.divide(expected - meas, expected, out=np.zeros_like(expected),
                     where=expected > 0)
    return np.clip(slip, 0.0, 1.0)


def enc_rpm_to_motor_rpm(enc_rpm: np.ndarray, gear_ratio: float) -> np.ndarray:
    """Velocidad del encoder referida al eje del motor (divide por la relación)."""
    if gear_ratio <= 0:
        raise ValueError("gear_ratio debe ser positivo")
    return np.asarray(enc_rpm, dtype=np.float64) / gear_ratio
