"""Pipeline por segmentos y caché en disco (HDF5) para trabajo con RAM plana.

Al cargar una grabación se hace **una** pasada por segmentos que:
  · decodifica el encoder (X4, stateful) → conteo por muestra, y
  · vuelca conteo + electrodos a un archivo HDF5 chunked.
Después, :class:`SessionCache` sirve tramos (ventana visible), la vista general
decimada y los estadísticos leyendo del HDF5 — nunca los 32 electrodos enteros
en memoria. El conteo del encoder (1 int64/muestra, ~8 MB por millón) sí se
mantiene en RAM porque es barato y de él derivan ángulo y velocidad al vuelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import h5py
import numpy as np

from .encoder import QuadratureDecoder, counts_to_angle_array, velocity_from_counts, wrap_angle
from .readers.base import Reader
from .stats import VelocityStats, describe
from .units import AngleUnit, VelocityUnit

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
    pos = 0
    with h5py.File(cache_path, "w") as h5:
        h5.attrs["sample_rate_hz"] = float(meta.sample_rate_hz)
        h5.attrs["fmt"] = meta.fmt
        h5.attrs["source_path"] = meta.path
        h5.attrs["electrode_names"] = np.array(names, dtype=h5py.string_dtype())

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
        # El conteo cabe holgado en RAM (~8 MB/millón) → base de ángulo/velocidad.
        self.counts: np.ndarray = self._h5["counts"][:]
        self.n_samples = int(self.counts.shape[0])

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
