"""Pipeline por segmentos y caché en disco (HDF5) para trabajo con RAM plana.

Al cargar una grabación se hace **una** pasada por segmentos que:
  · decodifica el encoder (X4, stateful) → conteo por muestra,
  · cuenta los micropasos del espejo STEP (si la grabación lo trae) → conteo de
    pasos por muestra, de donde sale la velocidad **comandada** del motor, y
  · vuelca ambos conteos + electrodos + la tensión cruda del espejo STEP a un
    archivo HDF5 chunked.
Después, :class:`SessionCache` sirve tramos (ventana visible), la vista general
decimada y los estadísticos leyendo del HDF5 — nunca todos los electrodos enteros
en memoria. Los dos conteos (1 int64/muestra, ~8 MB por millón) sí se mantienen
en RAM porque son baratos y de ellos derivan ángulo, velocidad y deslizamiento
al vuelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import h5py
import numpy as np

from .encoder import QuadratureDecoder, counts_to_angle_array, velocity_from_counts, wrap_angle
from .gearing import GearEstimate, estimate_gear_ratio, slip_fraction
from .motor import STOP_TIMEOUT_S, StepCounter, motor_rpm_from_step_counts
from .readers.base import Reader
from .stats import MotorSummary, VelocityStats, describe, summarize_motor
from .units import GEAR_RATIO_DEFAULT, AngleUnit, VelocityUnit

ProgressCb = Callable[[float], None]

_CHUNK = 200_000  # muestras por segmento (≈ 1.6 MB de conteo; bajo consumo)


def build_cache(
    reader: Reader,
    cache_path: str,
    chunk_samples: int = _CHUNK,
    progress_cb: ProgressCb | None = None,
) -> str:
    """Construye el HDF5 de caché a partir de un lector. Devuelve la ruta.

    Procesa por segmentos: la RAM usada es ~1 segmento de electrodos, no la
    sesión completa.
    """
    meta = reader.metadata()
    names = list(meta.electrode_names)
    n_hint = max(meta.n_samples, 1)

    decoder = QuadratureDecoder()
    steps = StepCounter()
    pos = 0
    with h5py.File(cache_path, "w") as h5:
        h5.attrs["sample_rate_hz"] = float(meta.sample_rate_hz)
        h5.attrs["fmt"] = meta.fmt
        h5.attrs["source_path"] = meta.path
        h5.attrs["electrode_names"] = np.array(names, dtype=h5py.string_dtype())
        h5.attrs["motor_channel"] = meta.motor_channel or ""
        h5.attrs["n_parts"] = int(meta.n_parts)

        counts_ds = h5.create_dataset(
            "counts", shape=(0,), maxshape=(None,), dtype=np.int64, chunks=(chunk_samples,)
        )
        # Niveles digitales normalizados (0/1) del encoder, para reexportar.
        diga_ds = h5.create_dataset(
            "digital_a", shape=(0,), maxshape=(None,), dtype=np.uint8, chunks=(chunk_samples,)
        )
        digb_ds = h5.create_dataset(
            "digital_b", shape=(0,), maxshape=(None,), dtype=np.uint8, chunks=(chunk_samples,)
        )
        # Espejo STEP: conteo acumulado de micropasos + tensión cruda (para poder
        # ver la onda cuadrada al hacer zoom y reexportarla).
        step_ds = motor_ds = None
        if meta.has_motor:
            step_ds = h5.create_dataset(
                "step_counts", shape=(0,), maxshape=(None,), dtype=np.int64,
                chunks=(chunk_samples,),
            )
            motor_ds = h5.create_dataset(
                "motor_v", shape=(0,), maxshape=(None,), dtype=np.float32,
                chunks=(chunk_samples,),
            )
        grp = h5.create_group("electrodes")
        elec_ds = {
            name: grp.create_dataset(
                name, shape=(0,), maxshape=(None,), dtype=np.float32, chunks=(chunk_samples,)
            )
            for name in names
        }

        for chunk in reader.iter_chunks(chunk_samples, electrodes=names):
            length = len(chunk)
            if length == 0:
                continue
            c = decoder.process(chunk.a, chunk.b)
            new = pos + length
            counts_ds.resize((new,))
            counts_ds[pos:new] = c
            diga_ds.resize((new,))
            diga_ds[pos:new] = (chunk.a != 0).astype(np.uint8)
            digb_ds.resize((new,))
            digb_ds[pos:new] = (chunk.b != 0).astype(np.uint8)
            if step_ds is not None and motor_ds is not None:
                # Si un segmento llegara sin la señal se rellena con reposo (0 V):
                # el contador no avanza y la sesión no se rompe.
                mv = chunk.motor if chunk.motor is not None else np.zeros(length)
                step_ds.resize((new,))
                step_ds[pos:new] = steps.process(mv)
                motor_ds.resize((new,))
                motor_ds[pos:new] = mv.astype(np.float32)
            for name in names:
                arr = chunk.electrodes.get(name)
                if arr is None:
                    continue
                ds = elec_ds[name]
                ds.resize((new,))
                ds[pos:new] = arr.astype(np.float32)
            pos = new
            if progress_cb:
                progress_cb(min(1.0, pos / n_hint))

    if progress_cb:
        progress_cb(1.0)
    return cache_path


@dataclass(frozen=True)
class Overview:
    """Serie decimada (envolvente min/max) para la vista general."""

    t: np.ndarray
    y: np.ndarray


def decimate_minmax(t: np.ndarray, y: np.ndarray, max_points: int) -> Overview:
    """Decima preservando la envolvente (min y max por bucket).

    Reduce a ~``max_points`` puntos manteniendo los extremos de cada tramo, de
    modo que picos y ruido no desaparecen al graficar millones de muestras.
    """
    n = y.shape[0]
    if n <= max_points or max_points < 4:
        return Overview(t=t, y=y)
    buckets = max_points // 2
    edges = np.linspace(0, n, buckets + 1, dtype=np.int64)
    ts: list[float] = []
    ys: list[float] = []
    for k in range(buckets):
        lo, hi = int(edges[k]), int(edges[k + 1])
        if hi <= lo:
            continue
        seg = y[lo:hi]
        imin = lo + int(np.argmin(seg))
        imax = lo + int(np.argmax(seg))
        # Emitir en orden temporal para no cruzar la línea.
        for idx in sorted((imin, imax)):
            ts.append(float(t[idx]))
            ys.append(float(y[idx]))
    return Overview(t=np.asarray(ts), y=np.asarray(ys))


class SessionCache:
    """Acceso de solo lectura al HDF5 de caché con RAM plana."""

    def __init__(self, cache_path: str) -> None:
        self._h5 = h5py.File(cache_path, "r")
        self.sample_rate_hz = float(self._h5.attrs["sample_rate_hz"])
        self.electrode_names = [
            s.decode() if isinstance(s, bytes) else str(s)
            for s in self._h5.attrs["electrode_names"]
        ]
        raw_ch = self._h5.attrs.get("motor_channel", "")
        if isinstance(raw_ch, bytes):
            raw_ch = raw_ch.decode()
        self.motor_channel: str | None = str(raw_ch) or None
        self.n_parts = int(self._h5.attrs.get("n_parts", 1))
        # Los conteos caben holgados en RAM (~8 MB/millón) → base de ángulo,
        # velocidad, velocidad de motor y deslizamiento.
        self.counts: np.ndarray = self._h5["counts"][:]
        self.step_counts: np.ndarray | None = (
            self._h5["step_counts"][:] if "step_counts" in self._h5 else None
        )
        self.n_samples = int(self.counts.shape[0])

    @property
    def has_motor(self) -> bool:
        """True si la grabación traía el espejo STEP (velocidad del motor)."""
        return self.step_counts is not None

    def _require_motor(self) -> np.ndarray:
        if self.step_counts is None:
            raise ValueError(
                "La grabación no incluye la señal del motor (ANALOG-IN-2): "
                "no se puede calcular la velocidad comandada."
            )
        return self.step_counts

    # ── ciclo de vida ────────────────────────────────────────────
    def close(self) -> None:
        self._h5.close()

    def __enter__(self) -> "SessionCache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── propiedades temporales ───────────────────────────────────
    @property
    def dt(self) -> float:
        return 1.0 / self.sample_rate_hz if self.sample_rate_hz else 0.0

    @property
    def duration_s(self) -> float:
        return self.n_samples * self.dt

    def clamp(self, i: int) -> int:
        return max(0, min(self.n_samples, i))

    def sample_at(self, t: float) -> int:
        return self.clamp(int(round(t / self.dt))) if self.dt else 0

    # ── tramos (ventana visible) ─────────────────────────────────
    def time_slice(self, i0: int, i1: int) -> np.ndarray:
        return np.arange(i0, i1, dtype=np.float64) * self.dt

    def angle_slice(self, i0: int, i1: int, unit: AngleUnit, wrap: bool = False) -> np.ndarray:
        ang = counts_to_angle_array(self.counts[i0:i1], unit)
        return wrap_angle(ang, unit) if wrap else ang

    def velocity_slice(
        self, i0: int, i1: int, unit: VelocityUnit, window_samples: int
    ) -> np.ndarray:
        """Velocidad de la ventana [i0,i1) con relleno para la ventana móvil."""
        pad = max(1, int(window_samples))
        lo = self.clamp(i0 - pad)
        hi = self.clamp(i1 + pad)
        v = velocity_from_counts(self.counts[lo:hi], self.dt, window_samples, unit)
        off = i0 - lo
        return v[off:off + (i1 - i0)]

    def electrode_slice(self, name: str, i0: int, i1: int) -> np.ndarray:
        return self._h5["electrodes"][name][i0:i1]

    def digital_slice(self, i0: int, i1: int) -> tuple[np.ndarray, np.ndarray]:
        return self._h5["digital_a"][i0:i1], self._h5["digital_b"][i0:i1]

    # ── señal del motor (espejo STEP) ────────────────────────────
    def motor_voltage_slice(self, i0: int, i1: int) -> np.ndarray:
        """Tensión cruda del espejo STEP (V) — la onda cuadrada tal cual."""
        self._require_motor()
        return self._h5["motor_v"][i0:i1]

    def motor_rpm_slice(self, i0: int, i1: int) -> np.ndarray:
        """RPM comandada del motor en [i0,i1).

        Se lee con relleno a ambos lados porque el estimador necesita el flanco
        anterior y el posterior: así el valor de una ventana coincide con el de
        la serie completa y navegar no altera los números.
        """
        steps = self._require_motor()
        pad = max(1, int(round(STOP_TIMEOUT_S / self.dt))) if self.dt else 1
        lo = self.clamp(i0 - pad)
        hi = self.clamp(i1 + pad)
        rpm = motor_rpm_from_step_counts(steps[lo:hi], self.dt)
        off = i0 - lo
        return rpm[off:off + (i1 - i0)]

    def motor_rpm_overview(self, max_points: int = 4000) -> Overview:
        steps = self._require_motor()
        t = np.arange(self.n_samples, dtype=np.float64) * self.dt
        y = motor_rpm_from_step_counts(steps, self.dt)
        return decimate_minmax(t, y, max_points)

    def slip_slice(
        self, i0: int, i1: int, gear_ratio: float = GEAR_RATIO_DEFAULT,
        window_samples: int = 1500,
    ) -> np.ndarray:
        """Deslizamiento por muestra en [i0,i1): 0 = sigue la consigna, 1 = bloqueado.

        La velocidad del encoder se suaviza con ``window_samples`` (50 ms por
        defecto a 30 kHz) para no confundir el rizado de cuadratura con
        pérdida de paso.
        """
        self._require_motor()
        motor = self.motor_rpm_slice(i0, i1)
        enc = self.velocity_slice(i0, i1, VelocityUnit.RPM, window_samples)
        return slip_fraction(motor, enc, gear_ratio)

    def gear_estimate(self, window_s: float | None = None) -> GearEstimate:
        """Estima la relación de engranajes con las dos señales de la grabación.

        Con ``window_s=None`` la ventana se adapta: 1 s en grabaciones largas y
        hasta 1/8 de la duración en las cortas, porque el criterio de "consigna
        estable" compara cada ventana con sus vecinas y hacen falta varias.
        """
        steps = self._require_motor()
        if window_s is None:
            window_s = min(1.0, self.duration_s / 8.0) if self.duration_s > 0 else 1.0
        return estimate_gear_ratio(steps, self.counts, self.dt, window_s=max(window_s, self.dt))

    def motor_stats(self, i0: int, i1: int) -> VelocityStats:
        """Estadísticos de la velocidad comandada del motor en [i0,i1)."""
        self._require_motor()
        return describe(self.motor_rpm_slice(i0, i1), VelocityUnit.RPM.value)

    def motor_summary(
        self, i0: int, i1: int, gear_ratio: float = GEAR_RATIO_DEFAULT,
        window_samples: int = 1500,
    ) -> MotorSummary:
        """Consigna, medida referida al motor y deslizamiento en [i0,i1).

        Todo se calcula sobre las muestras con el motor comandado — ver
        :class:`~analysis.stats.MotorSummary`.
        """
        self._require_motor()
        cmd = self.motor_rpm_slice(i0, i1)
        enc = self.velocity_slice(i0, i1, VelocityUnit.RPM, window_samples)
        return summarize_motor(cmd, enc, gear_ratio)

    # ── vista general (decimada) ─────────────────────────────────
    def angle_overview(self, unit: AngleUnit, max_points: int = 4000) -> Overview:
        t = np.arange(self.n_samples, dtype=np.float64) * self.dt
        y = counts_to_angle_array(self.counts, unit)
        return decimate_minmax(t, y, max_points)

    def velocity_overview(
        self, unit: VelocityUnit, window_samples: int, max_points: int = 4000
    ) -> Overview:
        t = np.arange(self.n_samples, dtype=np.float64) * self.dt
        y = velocity_from_counts(self.counts, self.dt, window_samples, unit)
        return decimate_minmax(t, y, max_points)

    # ── estadísticos ─────────────────────────────────────────────
    def session_stats(self, unit: VelocityUnit, window_samples: int) -> VelocityStats:
        v = velocity_from_counts(self.counts, self.dt, window_samples, unit)
        return describe(v, unit.value)

    def window_stats(
        self, i0: int, i1: int, unit: VelocityUnit, window_samples: int
    ) -> VelocityStats:
        v = self.velocity_slice(i0, i1, unit, window_samples)
        return describe(v, unit.value)
