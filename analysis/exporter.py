"""Exportación por segmentos con las columnas derivadas añadidas.

Reescribe la sesión (tiempo, canales digitales del encoder y electrodos µV)
añadiendo las columnas calculadas a CSV/TXT (tabular, estilo Intan) o HDF5:

  · `angle_<unidad>`  — ángulo del encoder
  · `omega_<unidad>`  — velocidad angular del encoder

y, si la grabación trae el espejo STEP (`ANALOG-IN-2`):

  · `analog_in_2_V`   — la onda cuadrada cruda del espejo STEP
  · `step_count`      — micropasos acumulados
  · `motor_rpm`       — velocidad **comandada** del motor (exacta, ver motor.py)
  · `slip`            — deslizamiento [0,1]: 0 sigue la consigna, 1 eje bloqueado

Escribe segmento a segmento leyendo de
:class:`~analysis.processing.SessionCache`, así la RAM se mantiene plana aunque
la sesión dure mucho.

Nota: no se reescriben las columnas de corriente de estimulación del formato
Intan original; se conservan las señales útiles (tiempo, encoder, electrodos)
más las columnas derivadas.
"""

from __future__ import annotations

import os
from typing import Callable

import h5py
import numpy as np

from .processing import SessionCache
from .units import GEAR_RATIO_DEFAULT, AngleUnit, VelocityUnit

ProgressCb = Callable[[float], None]

_EXPORT_CHUNK = 200_000

# Columnas derivadas del espejo STEP (en orden de salida).
MOTOR_COLS = ("analog_in_2_V", "step_count", "motor_rpm", "slip")


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
    gear_ratio: float = GEAR_RATIO_DEFAULT,
    motor_window_samples: int | None = None,
    sample_range: tuple[int, int] | None = None,
) -> str:
    """Exporta la sesión con las columnas derivadas. Devuelve la ruta escrita.

    Las columnas del motor solo aparecen si la grabación traía el espejo STEP.

    ``sample_range`` limita la exportación a ``[i0, i1)``; por defecto se exporta
    la sesión completa. Acotar importa: la toma de referencia son 437 s × 27
    columnas ≈ 4 GB en CSV, mientras que un tramo de 20 s cabe en ~180 MB.
    """
    fmt = infer_format(out_path)
    names = electrodes if electrodes is not None else list(cache.electrode_names)
    i0, i1 = _resolve_range(cache, sample_range)
    args = (cache, out_path, angle_unit, vel_unit, window_samples, names,
            chunk_samples, progress_cb, gear_ratio,
            motor_window_samples or window_samples, i0, i1)
    if fmt == "hdf5":
        _export_hdf5(*args)
    else:
        _export_tabular(*args)
    if progress_cb:
        progress_cb(1.0)
    return out_path


def _resolve_range(cache: SessionCache, rng: tuple[int, int] | None) -> tuple[int, int]:
    """Recorta el rango pedido a los límites de la sesión y valida que no esté vacío."""
    if rng is None:
        return 0, cache.n_samples
    i0, i1 = cache.clamp(int(rng[0])), cache.clamp(int(rng[1]))
    if i1 <= i0:
        raise ValueError(f"Rango de exportación vacío: [{rng[0]}, {rng[1]})")
    return i0, i1


def _col_names(
    angle_unit: AngleUnit, vel_unit: VelocityUnit, electrodes: list[str], has_motor: bool
) -> list[str]:
    ang = f"angle_{angle_unit.value}"
    omega = f"omega_{vel_unit.value}"
    motor = list(MOTOR_COLS) if has_motor else []
    return ["Time", "DIGITAL-IN-01", "DIGITAL-IN-02", *electrodes, ang, omega, *motor]


def _units_row(
    angle_unit: AngleUnit, vel_unit: VelocityUnit, n_elec: int, has_motor: bool
) -> list[str]:
    motor = ["V", "pasos", "RPM", "frac"] if has_motor else []
    return ["s", "", "", *["uV"] * n_elec, angle_unit.value, vel_unit.value, *motor]


def _export_tabular(cache, out_path, angle_unit, vel_unit, window_samples, names,
                    chunk_samples, progress_cb, gear_ratio, motor_window,
                    start, stop) -> None:
    import pandas as pd

    sep = _sep_for(out_path)
    cols = _col_names(angle_unit, vel_unit, names, cache.has_motor)
    units_row = _units_row(angle_unit, vel_unit, len(names), cache.has_motor)
    total = stop - start

    with open(out_path, "w", encoding="ascii", newline="") as fh:
        fh.write(sep.join(f'"{c}"' for c in cols) + "\n")
        fh.write(sep.join(f'"{u}"' for u in units_row) + "\n")
        for i0 in range(start, stop, chunk_samples):
            i1 = min(i0 + chunk_samples, stop)
            data = _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples,
                                names, gear_ratio, motor_window)
            frame = pd.DataFrame(data, columns=cols)
            frame.to_csv(fh, sep=sep, header=False, index=False,
                         float_format="%.6f", lineterminator="\n")
            if progress_cb:
                progress_cb((i1 - start) / total)


def _export_hdf5(cache, out_path, angle_unit, vel_unit, window_samples, names,
                 chunk_samples, progress_cb, gear_ratio, motor_window,
                 start, stop) -> None:
    n = stop - start
    with h5py.File(out_path, "w") as h5:
        h5.attrs["angle_unit"] = angle_unit.value
        h5.attrs["velocity_unit"] = vel_unit.value
        h5.attrs["sample_rate_hz"] = cache.sample_rate_hz
        h5.attrs["has_motor"] = bool(cache.has_motor)
        h5.attrs["t_start_s"] = start * cache.dt
        h5.attrs["t_stop_s"] = stop * cache.dt
        if cache.has_motor:
            h5.attrs["gear_ratio"] = float(gear_ratio)
        time_ds = h5.create_dataset("time", (n,), dtype=np.float64, chunks=(min(chunk_samples, n),))
        a_ds = h5.create_dataset("DIGITAL-IN-01", (n,), dtype=np.uint8)
        b_ds = h5.create_dataset("DIGITAL-IN-02", (n,), dtype=np.uint8)
        ang_ds = h5.create_dataset(f"angle_{angle_unit.value}", (n,), dtype=np.float32)
        om_ds = h5.create_dataset(f"omega_{vel_unit.value}", (n,), dtype=np.float32)
        motor_ds = {}
        if cache.has_motor:
            motor_ds = {
                "analog_in_2_V": h5.create_dataset("analog_in_2_V", (n,), dtype=np.float32),
                "step_count": h5.create_dataset("step_count", (n,), dtype=np.int64),
                "motor_rpm": h5.create_dataset("motor_rpm", (n,), dtype=np.float32),
                "slip": h5.create_dataset("slip", (n,), dtype=np.float32),
            }
        grp = h5.create_group("electrodes")
        elec_ds = {name: grp.create_dataset(name, (n,), dtype=np.float32) for name in names}

        for i0 in range(start, stop, chunk_samples):
            i1 = min(i0 + chunk_samples, stop)
            blk = _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples,
                               names, gear_ratio, motor_window)
            # Índices relativos al inicio del rango exportado.
            o0, o1 = i0 - start, i1 - start
            time_ds[o0:o1] = blk["Time"]
            a_ds[o0:o1] = blk["DIGITAL-IN-01"]
            b_ds[o0:o1] = blk["DIGITAL-IN-02"]
            ang_ds[o0:o1] = blk[f"angle_{angle_unit.value}"]
            om_ds[o0:o1] = blk[f"omega_{vel_unit.value}"]
            for key, ds in motor_ds.items():
                ds[o0:o1] = blk[key]
            for name in names:
                elec_ds[name][o0:o1] = blk[name]
            if progress_cb:
                progress_cb(o1 / n)


def _build_block(cache, i0, i1, angle_unit, vel_unit, window_samples, names,
                 gear_ratio, motor_window) -> dict:
    """Construye el bloque de columnas [i0,i1) leyendo de la caché."""
    a, b = cache.digital_slice(i0, i1)
    block = {
        "Time": cache.time_slice(i0, i1),
        "DIGITAL-IN-01": a.astype(np.uint8),
        "DIGITAL-IN-02": b.astype(np.uint8),
        f"angle_{angle_unit.value}": cache.angle_slice(i0, i1, angle_unit),
        f"omega_{vel_unit.value}": cache.velocity_slice(i0, i1, vel_unit, window_samples),
    }
    if cache.has_motor:
        block["analog_in_2_V"] = cache.motor_voltage_slice(i0, i1)
        block["step_count"] = cache.step_counts[i0:i1]
        block["motor_rpm"] = cache.motor_rpm_slice(i0, i1)
        block["slip"] = cache.slip_slice(i0, i1, gear_ratio, motor_window)
    for name in names:
        block[name] = cache.electrode_slice(name, i0, i1)
    return block
