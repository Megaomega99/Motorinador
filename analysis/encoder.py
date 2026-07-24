"""Decodificación de cuadratura X4 y cálculo de ángulo/velocidad.

Réplica offline y vectorizada de la lógica de las ISRs del firmware
(src/main.cpp, ISR_encA / ISR_encB). A diferencia del firmware —que solo
actúa en los flancos vía interrupción— aquí las dos señales A/B llegan
muestreadas a fs (30 kHz), así que se detectan las transiciones entre
muestras consecutivas con una tabla de estados Gray, equivalente a la
decodificación X4 del firmware y con su misma convención de signo.

Deriva de las reglas del firmware:
  · flanco en A → (a==b): +1, si no −1
  · flanco en B → (a==b): −1, si no +1
Codificando el estado como  s = 2*A + B  (00,01,10,11 → 0,1,2,3), la tabla
de incrementos T[old, new] resultante es la estándar de cuadratura X4.
Las transiciones "imposibles" (ambos bits cambian a la vez, p. ej. 00→11)
son ambiguas → incremento 0 (glitch).
"""

from __future__ import annotations

import numpy as np

from .units import AngleUnit, VelocityUnit, counts_per_sec_to_velocity, counts_to_angle

# Tabla de transición X4 aplanada: índice = old*4 + new. Ver derivación arriba.
#            new: 0   1   2   3
_TABLE = np.array(
    [
        0, +1, -1, 0,   # old = 00
        -1, 0, 0, +1,   # old = 01
        +1, 0, 0, -1,   # old = 10
        0, -1, +1, 0,   # old = 11
    ],
    dtype=np.int8,
)


class QuadratureDecoder:
    """Decodificador X4 con estado persistente entre segmentos.

    Uso típico: instanciar una vez y llamar a :meth:`process` con cada
    segmento (chunk) de las señales A/B; el conteo acumulado se arrastra
    de una llamada a la siguiente, de modo que procesar por trozos da el
    mismo resultado que procesar toda la señal de una vez.
    """

    def __init__(self) -> None:
        self._last_state: int | None = None
        self._count: int = 0

    @property
    def count(self) -> int:
        """Conteo acumulado tras el último segmento procesado."""
        return self._count

    def process(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Decodifica un segmento y devuelve el conteo acumulado por muestra.

        Parameters
        ----------
        a, b : np.ndarray
            Señales digitales (0/1) de los canales A y B, misma longitud.

        Returns
        -------
        np.ndarray (int64)
            Conteo acumulado del encoder en cada muestra del segmento.
        """
        if a.shape != b.shape:
            raise ValueError("A y B deben tener la misma longitud")
        n = a.shape[0]
        if n == 0:
            return np.empty(0, dtype=np.int64)

        # Estado por muestra: s = 2*A + B  (garantiza 0..3 con señales 0/1).
        s = (2 * (a != 0).astype(np.intp) + (b != 0).astype(np.intp))

        if self._last_state is None:
            # Primera muestra de la sesión: no hay estado previo → incremento 0.
            prev = np.empty(n, dtype=np.intp)
            prev[0] = s[0]
            prev[1:] = s[:-1]
        else:
            prev = np.empty(n, dtype=np.intp)
            prev[0] = self._last_state
            prev[1:] = s[:-1]

        inc = _TABLE[prev * 4 + s].astype(np.int64)
        counts = self._count + np.cumsum(inc)

        self._count = int(counts[-1])
        self._last_state = int(s[-1])
        return counts


def counts_to_angle_array(counts: np.ndarray, unit: AngleUnit) -> np.ndarray:
    """Ángulo (acumulado) por muestra a partir del conteo. Vectorizado."""
    return counts_to_angle(counts.astype(np.float64), unit)


def wrap_angle(angle: np.ndarray, unit: AngleUnit) -> np.ndarray:
    """Envuelve el ángulo acumulado al rango [0, una vuelta)."""
    return np.mod(angle, unit.per_rev)


def velocity_from_counts(
    counts: np.ndarray,
    dt: float,
    window_samples: int,
    unit: VelocityUnit,
) -> np.ndarray:
    """Velocidad angular por muestra mediante ventana deslizante.

    Diferencia finita del conteo suavizada con media móvil uniforme de
    ``window_samples`` muestras (equivale a medir (Δcuentas/Δt) sobre una
    ventana de ese ancho). Robusta al ruido de cuantización de la cuadratura.

    Parameters
    ----------
    counts : np.ndarray
        Conteo acumulado del encoder por muestra.
    dt : float
        Intervalo de muestreo en segundos (1/fs).
    window_samples : int
        Ancho de la ventana de suavizado en muestras (≥ 1).
    unit : VelocityUnit
        Unidad de salida (rad/s, grad/s o RPM).
    """
    if dt <= 0:
        raise ValueError("dt debe ser positivo")
    n = counts.shape[0]
    if n < 2:
        return np.zeros(n, dtype=np.float64)

    w = max(1, int(window_samples))
    inc = np.diff(counts.astype(np.float64))  # cuentas por muestra (len n-1)

    if w == 1:
        smoothed = inc
    else:
        kernel = np.ones(w, dtype=np.float64) / w
        smoothed = np.convolve(inc, kernel, mode="same")

    cps = smoothed / dt  # cuentas por segundo
    # Alinear a longitud n (la muestra 0 hereda el primer valor).
    cps = np.concatenate(([cps[0]], cps))
    return counts_per_sec_to_velocity(cps, unit)
