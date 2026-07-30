"""Velocidad del motor recuperada del espejo del pulso STEP (`ANALOG-IN-2`).

El firmware saca por `PIN_STEP_OUT` (D11) una copia del tren STEP que alimenta al
TMC2208, y esa copia se graba en la entrada analógica `ANALOG-IN-2` del Intan. Es
una onda cuadrada lógica de 3.3 V y **ciclo de trabajo 50 %**, porque el firmware
conmuta el pin cada `half` µs (ver `loop()` en src/main.cpp):

    f_STEP  = flancos de subida/s = 1 micropaso/s
    RPM_mot = f_STEP · 60 / STEPS_PER_REV        (STEPS_PER_REV = 1600)

Por tanto esta señal da la velocidad **comandada** del motor de forma exacta, sin
pasar por el encoder. Lo que NO da es la dirección: DIR es otro pin y no se graba,
así que la magnitud viene de aquí y el signo del encoder.

Con el motor parado el firmware deja STEP en LOW (`stopMotor`), así que la señal
queda plana en ~2 mV y no genera flancos.

Dos piezas:
  · :class:`StepCounter` — binariza con histéresis y acumula flancos, con estado
    entre segmentos (igual que :class:`~analysis.encoder.QuadratureDecoder`), de
    modo que procesar por trozos da lo mismo que procesar todo de una vez.
  · :func:`motor_rpm_from_step_counts` — RPM por muestra a partir del **intervalo
    entre flancos**. Es exacto para un tren comandado, al contrario que una media
    móvil, que a 5 RPM (133 Hz) en 50 ms solo vería ~7 pasos (±15 % de
    cuantización) sobre una señal que en realidad es perfectamente plana.
"""

from __future__ import annotations

import numpy as np

from .units import STEPS_PER_REV

# Umbrales de la histéresis (V). La señal es lógica de 3.3 V y el reposo son ~2 mV,
# así que hay margen de sobra; la banda muerta evita flancos espurios si la señal
# quedara parada cerca del umbral.
V_THRESH_HIGH: float = 1.5
V_THRESH_LOW: float = 0.8

# Sin flancos durante este tiempo se considera el motor parado.
STOP_TIMEOUT_S: float = 0.25

# Tramo mínimo sobre el que promediar el periodo (ver motor_rpm_from_step_counts).
MIN_SPAN_S: float = 0.005


class StepCounter:
    """Cuenta micropasos (flancos de subida) del espejo STEP, con estado.

    Uso: instanciar una vez y llamar a :meth:`process` con cada segmento de la
    señal analógica en **voltios**; el conteo acumulado se arrastra entre llamadas.
    """

    def __init__(
        self,
        v_high: float = V_THRESH_HIGH,
        v_low: float = V_THRESH_LOW,
    ) -> None:
        if not v_low < v_high:
            raise ValueError("v_low debe ser menor que v_high")
        self._v_high = float(v_high)
        self._v_low = float(v_low)
        self._level: int = 0     # último nivel lógico conocido
        self._count: int = 0

    @property
    def count(self) -> int:
        """Micropasos acumulados tras el último segmento procesado."""
        return self._count

    def process(self, v: np.ndarray) -> np.ndarray:
        """Binariza el segmento y devuelve el conteo acumulado por muestra.

        Parameters
        ----------
        v : np.ndarray
            Señal analógica del espejo STEP en voltios.

        Returns
        -------
        np.ndarray (int64)
            Micropasos acumulados en cada muestra del segmento.
        """
        arr = np.asarray(v, dtype=np.float64)
        n = arr.shape[0]
        if n == 0:
            return np.empty(0, dtype=np.int64)

        level = self._binarize(arr)

        # Flanco de subida = 0→1 respecto de la muestra anterior (la primera se
        # compara con el nivel heredado del segmento previo).
        prev = np.empty(n, dtype=np.int8)
        prev[0] = self._level
        prev[1:] = level[:-1]
        rising = ((level == 1) & (prev == 0)).astype(np.int64)

        counts = self._count + np.cumsum(rising)
        self._count = int(counts[-1])
        self._level = int(level[-1])
        return counts

    def _binarize(self, arr: np.ndarray) -> np.ndarray:
        """Nivel lógico 0/1 con histéresis, vectorizado.

        Cada muestra por encima de ``v_high`` fija el nivel a 1 y cada muestra por
        debajo de ``v_low`` lo fija a 0; entre ambos umbrales el nivel se mantiene.
        Eso se resuelve propagando hacia delante la última muestra "decisiva"
        (``maximum.accumulate`` sobre sus posiciones).
        """
        decided = np.where(arr > self._v_high, 1, np.where(arr < self._v_low, 0, -1))
        pos = np.where(decided >= 0, np.arange(arr.shape[0]), -1)
        pos = np.maximum.accumulate(pos)
        held = decided[np.maximum(pos, 0)]
        # Antes de la primera muestra decisiva se arrastra el nivel del segmento previo.
        return np.where(pos >= 0, held, self._level).astype(np.int8)


def motor_rpm_from_step_counts(
    step_counts: np.ndarray,
    dt: float,
    stop_timeout_s: float = STOP_TIMEOUT_S,
    steps_per_rev: int = STEPS_PER_REV,
    min_span_s: float = MIN_SPAN_S,
) -> np.ndarray:
    """RPM del motor por muestra a partir del conteo acumulado de micropasos.

    Para cada flanco se mide el tiempo hasta el primer flanco posterior que esté
    a ``min_span_s`` o más, y la velocidad es ``pasos · 60 / (steps_per_rev · T)``;
    ese valor se mantiene hasta el flanco siguiente. La estimación se refresca en
    **cada** paso, pero promediando sobre un tramo mínimo.

    El tramo mínimo existe porque el periodo se mide en múltiplos del intervalo de
    muestreo: a 120 RPM (3200 pasos/s) un periodo son solo 9.4 muestras a 30 kHz,
    así que medir un único periodo cuantizaría un ±5 %. Promediando ≥5 ms el error
    baja a <1 % en todo el rango 1–120 RPM, y a velocidades bajas (donde un periodo
    ya dura más que el tramo mínimo) la medida sigue siendo exacta paso a paso.

    Si el hueco entre flancos supera ``stop_timeout_s`` se considera el motor
    parado (0 RPM). Los tramos inicial y final —sin flanco a un lado— heredan la
    velocidad contigua mientras no superen el mismo timeout.

    Parameters
    ----------
    step_counts : np.ndarray
        Conteo acumulado de micropasos por muestra (:class:`StepCounter`).
    dt : float
        Intervalo de muestreo en segundos (1/fs).
    stop_timeout_s : float
        Silencio máximo entre flancos antes de declarar el motor parado.
    steps_per_rev : int
        Micropasos por vuelta del motor (espejo de `STEPS_PER_REV` del firmware).
    min_span_s : float
        Tramo mínimo sobre el que promediar para acotar la cuantización.
    """
    if dt <= 0:
        raise ValueError("dt debe ser positivo")
    counts = np.asarray(step_counts, dtype=np.int64)
    n = counts.shape[0]
    out = np.zeros(n, dtype=np.float64)
    if n < 2:
        return out

    # Muestra en la que el conteo aumenta = muestra del flanco de subida.
    edges = np.flatnonzero(np.diff(counts) > 0) + 1
    if edges.size < 2:
        return out

    gaps = np.diff(edges)                       # muestras hasta el flanco siguiente
    rpm = _rpm_per_interval(counts, edges, dt, steps_per_rev, min_span_s)
    rpm[gaps * dt > stop_timeout_s] = 0.0       # silencio largo → motor parado

    out[edges[0]:edges[-1]] = np.repeat(rpm, gaps)

    # Bordes: mantener la velocidad contigua solo si el silencio es corto.
    timeout_samples = max(1, int(round(stop_timeout_s / dt)))
    head = int(edges[0])
    if head:
        out[max(0, head - timeout_samples):head] = rpm[0]
    tail = int(edges[-1])
    if tail < n:
        stop = min(n, tail + timeout_samples)
        out[tail:stop] = rpm[-1]
    return out


def _rpm_per_interval(
    counts: np.ndarray,
    edges: np.ndarray,
    dt: float,
    steps_per_rev: int,
    min_span_s: float,
) -> np.ndarray:
    """RPM asignada a cada intervalo entre flancos consecutivos.

    Para el flanco ``k`` se busca el primer flanco ``m`` tal que
    ``edges[m] − edges[k] ≥ min_span`` y se promedia sobre ese tramo. Cuando no
    existe tal flanco (final de la señal) se usa el último flanco disponible; si
    tampoco sirve, se cae al intervalo simple ``k → k+1``.
    """
    n_int = edges.shape[0] - 1
    min_span = max(1, int(round(min_span_s / dt)))

    # Primer flanco a >= min_span muestras de cada flanco k.
    m = np.searchsorted(edges, edges[:n_int] + min_span, side="left")
    m = np.minimum(m, edges.shape[0] - 1)
    # Garantizar m > k para no dividir por cero en tramos muy cortos.
    m = np.maximum(m, np.arange(1, n_int + 1))
    m = np.minimum(m, edges.shape[0] - 1)

    span = (edges[m] - edges[:n_int]).astype(np.float64) * dt
    steps = (counts[edges[m]] - counts[edges[:n_int]]).astype(np.float64)
    return np.divide(steps * 60.0, float(steps_per_rev) * span,
                     out=np.zeros(n_int, dtype=np.float64), where=span > 0)


def step_train(rpm: float, duration_s: float, dt: float, v_high: float = 3.29) -> np.ndarray:
    """Genera el tren STEP que produciría el firmware a ``rpm``.

    Réplica de la temporización de `loop()`: onda cuadrada de 50 % a
    ``rpm · STEPS_PER_REV / 60`` Hz. Se usa en tests y para comprobar la cadena
    de recuperación sin necesidad de una grabación.
    """
    if dt <= 0:
        raise ValueError("dt debe ser positivo")
    n = max(0, int(round(duration_s / dt)))
    if n == 0 or rpm <= 0:
        return np.zeros(max(n, 0), dtype=np.float64)
    f_step = rpm * STEPS_PER_REV / 60.0
    phase = np.mod(np.arange(n) * dt * f_step, 1.0)
    return np.where(phase < 0.5, v_high, 0.0)
