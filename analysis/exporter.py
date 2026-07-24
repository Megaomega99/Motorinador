"""Exportación por segmentos con columnas de ángulo y velocidad añadidas.

Reescribe la sesión (tiempo, canales digitales del encoder y electrodos µV)
añadiendo dos columnas nuevas —ángulo y velocidad angular en las unidades
elegidas— a CSV/TXT (tabular, estilo Intan) o HDF5. Escribe segmento a segmento
leyendo de :class:`~analysis.processing.SessionCache`, así la RAM se mantiene
plana aunque la sesión dure mucho.

Nota: no se reescriben las columnas de corriente de estimulación del formato
Intan original; se conservan las señales útiles (tiempo, encoder, electrodos)
más las dos columnas derivadas.
"""

from __future__ import annotations

import os
from typing import Callable

import h5py
import numpy as np

from .processing import SessionCache
from .units import AngleUnit, VelocityUnit

ProgressCb = Callable[[float], None]

_EXPORT_CHUNK = 200_000


def infer_format(path: str) -> str:
    """Devuelve "hdf5" o "tabular" según la extensión del destino."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".h5", ".hdf5", ".he5"):
        return "hdf5"
    return "tabular"


def _sep_for(path: str) -> str:
    return "," if os.path.splitext(path)[1].lower() == ".csv" else "\t"


def export(
    cache: SessionCache,
    out_path: str,
    angle_unit: AngleUnit,
    vel_unit: VelocityUnit,
    window_samples: int,
    electrodes: list[str] | None = None,
    chunk_samples: int = _EXPORT_CHUNK,
    progress_cb: ProgressCb | None = None,
) -> str:
    """Exporta la sesión con ángulo y velocidad. Devuelve la ruta escrita."""
    fmt = infer_format(out_path)
    names = electrodes if electrodes is not None else list(cache.electrode_names)
    if fmt == "hdf5":
        _export_hdf5(cache, out_path, angle_unit, vel_unit, window_samples, names,
                     chunk_samples, progress_cb)
    else:
        _export_tabular(cache, out_path, angle_unit, vel_unit, window_samples, names,
                        chunk_samples, progress_cb)
    if progress_cb:
        progress_cb(1.0)
    return out_path


def _col_names(angle_unit: AngleUnit, vel_unit: VelocityUnit, electrodes: list[str]) -> list[str]:
    ang = f"angle_{angle_unit.value}"
    omega = f"omega_{vel_unit.value}"
    return ["Time", "DIGITAL-IN-01", "DIGITAL-IN-02", *electrodes, ang, omega]


def _export_tabular(cache, out_path, angle_unit, vel_unit, window_samples, names,
                    chunk_samples, progress_cb) -> None:
    import pandas as pd

    sep = _sep_for(out_path)
    cols = _col_names(angle_unit, vel_unit, names)
    units_row = ["s", "", "", *["uV"] * len(names), angle_unit.value, vel_unit.value]
    n = cache.n_samples

    with open(out_path, "w", encoding="ascii", newline="") as fh:
        fh.write(sep.join(f'"{c}"' for c in cols) + "\n")
        fh.write(sep.join(f'"{u}"' for u in units_row) + "\n")
        for i0 in range(0, n, chunk_samples):
            i1 = min(i0 + chunk_samples, n)
            data = _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples, names)
            frame = pd.DataFrame(data, columns=cols)
            frame.to_csv(fh, sep=sep, header=False, index=False,
                         float_format="%.6f", lineterminator="\n")
            if progress_cb:
                progress_cb(i1 / n)


def _export_hdf5(cache, out_path, angle_unit, vel_unit, window_samples, names,
                 chunk_samples, progress_cb) -> None:
    n = cache.n_samples
    with h5py.File(out_path, "w") as h5:
        h5.attrs["angle_unit"] = angle_unit.value
        h5.attrs["velocity_unit"] = vel_unit.value
        h5.attrs["sample_rate_hz"] = cache.sample_rate_hz
        time_ds = h5.create_dataset("time", (n,), dtype=np.float64, chunks=(min(chunk_samples, n),))
        a_ds = h5.create_dataset("DIGITAL-IN-01", (n,), dtype=np.uint8)
        b_ds = h5.create_dataset("DIGITAL-IN-02", (n,), dtype=np.uint8)
        ang_ds = h5.create_dataset(f"angle_{angle_unit.value}", (n,), dtype=np.float32)
        om_ds = h5.create_dataset(f"omega_{vel_unit.value}", (n,), dtype=np.float32)
        grp = h5.create_group("electrodes")
        elec_ds = {name: grp.create_dataset(name, (n,), dtype=np.float32) for name in names}

        for i0 in range(0, n, chunk_samples):
            i1 = min(i0 + chunk_samples, n)
            blk = _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples, names)
            time_ds[i0:i1] = blk["Time"]
            a_ds[i0:i1] = blk["DIGITAL-IN-01"]
            b_ds[i0:i1] = blk["DIGITAL-IN-02"]
            ang_ds[i0:i1] = blk[f"angle_{angle_unit.value}"]
            om_ds[i0:i1] = blk[f"omega_{vel_unit.value}"]
            for name in names:
                elec_ds[name][i0:i1] = blk[name]
            if progress_cb:
                progress_cb(i1 / n)


def _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples, names) -> dict:
    """Construye el bloque de columnas [i0,i1) leyendo de la caché."""
    a, b = cache.digital_slice(i0, i1)
    block = {
        "Time": cache.time_slice(i0, i1),
        "DIGITAL-IN-01": a.astype(np.uint8),
        "DIGITAL-IN-02": b.astype(np.uint8),
        f"angle_{angle_unit.value}": cache.angle_slice(i0, i1, angle_unit),
        f"omega_{vel_unit.value}": cache.velocity_slice(i0, i1, vel_unit, window_samples),
    }
    for name in names:
        block[name] = cache.electrode_slice(name, i0, i1)
    return block
