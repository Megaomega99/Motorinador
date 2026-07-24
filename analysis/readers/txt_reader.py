"""Lector del export tabular de Intan (`textform.txt`).

Formato (separado por tabuladores):
    fila 0 : nombres de columna, p. ej.  "Time"  "66 DIGITAL-IN-02"  "64 A-031" ...
    fila 1 : unidades,            p. ej.  "Units" ""                 "A" "uV" ...
    fila 2+: datos numéricos.

Cada electrodo aparece en DOS columnas (corriente en "A" y señal en "uV");
nos quedamos con la de "uV". Las señales del encoder son las columnas
DIGITAL-IN-01 (canal A) y DIGITAL-IN-02 (canal B).
"""

from __future__ import annotations

import os
import re
from typing import Iterator

import numpy as np
import pandas as pd

from .base import Chunk, Meta, Reader

_ELECTRODE_RE = re.compile(r"(A-\d+)")


def toggles_to_levels(pulses: np.ndarray, parity0: int) -> tuple[np.ndarray, int]:
    """Reconstruye el nivel digital a partir de una señal de conmutación.

    En el ``textform.txt`` de este proyecto las columnas DIGITAL-IN NO son el
    nivel del canal, sino un **pulso de una muestra en cada flanco** (toggle).
    El nivel real es la paridad acumulada de esos pulsos:
        nivel[i] = (parity0 + Σ pulsos[0..i]) mod 2
    Verificado al 100 % contra los niveles del binario `.rhs` de la misma sesión.

    Es *stateful*: devuelve también la paridad final para encadenar segmentos.
    """
    lvl = (parity0 + np.cumsum(pulses.astype(np.int64))) % 2
    parity_end = int(lvl[-1]) if lvl.size else parity0
    return lvl.astype(np.float64), parity_end


def _split_line(line: str) -> list[str]:
    return [c.strip().strip('"') for c in line.rstrip("\n").split("\t")]


def _sample_rate_from_settings(path: str) -> float | None:
    """Lee SampleRateHertz de un settings.xml de Intan junto al archivo."""
    folder = os.path.dirname(os.path.abspath(path))
    settings = os.path.join(folder, "settings.xml")
    if not os.path.isfile(settings):
        return None
    try:
        with open(settings, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
        m = re.search(r'SampleRateHertz="([\d.]+)"', head)
        return float(m.group(1)) if m else None
    except OSError:
        return None


def _read_last_time(path: str, time_col: int) -> float:
    """Lee el valor de tiempo de la última fila con datos (seek al final)."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        block = min(size, 65536)
        fh.seek(size - block)
        tail = fh.read().decode("ascii", errors="replace")
    for line in reversed(tail.splitlines()):
        if not line.strip():
            continue
        parts = line.split("\t")
        try:
            return float(parts[time_col])
        except (ValueError, IndexError):
            continue
    return 0.0


class TxtReader(Reader):
    """Lector del export tabular de Intan.

    Parameters
    ----------
    path : str
        Ruta al archivo tabular.
    digital_mode : {"toggle", "level"}
        Interpretación de las columnas DIGITAL-IN. "toggle" (por defecto) trata
        cada columna como pulsos de flanco y reconstruye el nivel (formato real
        de este proyecto, ver :func:`toggles_to_levels`); "level" las usa tal
        cual como nivel 0/1.
    """

    def __init__(self, path: str, digital_mode: str = "toggle") -> None:
        if digital_mode not in ("toggle", "level"):
            raise ValueError("digital_mode debe ser 'toggle' o 'level'")
        self.digital_mode = digital_mode
        self.path = path
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            header = fh.readline()
            units = fh.readline()
        self._labels = _split_line(header)
        self._units = _split_line(units)
        self._resolve_columns()
        self._meta = self._build_meta()

    # ── configuración de columnas ────────────────────────────────
    def _resolve_columns(self) -> None:
        self._time_col: int | None = None
        self._a_col: int | None = None
        self._b_col: int | None = None
        self._electrode_cols: dict[str, int] = {}

        for i, label in enumerate(self._labels):
            unit = self._units[i] if i < len(self._units) else ""
            if label == "Time":
                self._time_col = i
            elif "DIGITAL-IN-01" in label:
                self._a_col = i
            elif "DIGITAL-IN-02" in label:
                self._b_col = i
            elif unit == "uV":
                m = _ELECTRODE_RE.search(label)
                if m:
                    self._electrode_cols[m.group(1)] = i

        missing = [n for n, v in (("Time", self._time_col), ("DIGITAL-IN-01", self._a_col),
                                  ("DIGITAL-IN-02", self._b_col)) if v is None]
        if missing:
            raise ValueError(f"Columnas requeridas ausentes en {self.path}: {missing}")

    def _build_meta(self) -> Meta:
        # dt a partir de las dos primeras filas de datos; fs = 1/dt.
        t0 = t1 = 0.0
        with open(self.path, "r", encoding="ascii", errors="replace") as fh:
            fh.readline()  # cabecera
            fh.readline()  # unidades
            row0 = fh.readline().split("\t")
            row1 = fh.readline().split("\t")
        try:
            t0 = float(row0[self._time_col])
            t1 = float(row1[self._time_col])
        except (ValueError, IndexError):
            pass
        # La columna Time está truncada a 8 decimales, así que inferir fs de
        # ella es aproximado (~0.01 %). Si hay un settings.xml de Intan junto
        # al archivo, su SampleRateHertz es la fuente exacta.
        fs_xml = _sample_rate_from_settings(self.path)
        if fs_xml:
            fs = fs_xml
        else:
            dt_est = (t1 - t0) if t1 > t0 else 1.0 / 30000.0
            fs = 1.0 / dt_est
        dt = 1.0 / fs
        last_t = _read_last_time(self.path, self._time_col)
        n = int(round((last_t - t0) / dt)) + 1 if last_t > t0 else 0
        return Meta(
            path=self.path,
            sample_rate_hz=fs,
            n_samples=n,
            electrode_names=sorted(self._electrode_cols),
            digital_names=["DIGITAL-IN-01", "DIGITAL-IN-02"],
            fmt="txt",
        )

    def metadata(self) -> Meta:
        return self._meta

    # ── iteración por segmentos ──────────────────────────────────
    def iter_chunks(
        self,
        chunk_samples: int,
        electrodes: list[str] | None = None,
    ) -> Iterator[Chunk]:
        elec = electrodes or []
        for name in elec:
            if name not in self._electrode_cols:
                raise ValueError(f"Electrodo desconocido: {name}")

        usecols = [self._time_col, self._a_col, self._b_col]
        usecols += [self._electrode_cols[n] for n in elec]

        # pandas asigna `names` a las columnas en ORDEN DE ARCHIVO (no en el
        # orden de `usecols`); por eso nombramos cada columna con su índice
        # ordenado, de modo que frame[str(col)] siempre apunte a esa columna.
        names = [str(c) for c in sorted(usecols)]
        reader = pd.read_csv(
            self.path,
            sep="\t",
            header=None,
            skiprows=2,
            usecols=usecols,
            names=names,
            chunksize=chunk_samples,
            dtype=np.float64,
            engine="c",
            na_filter=False,
        )
        tcol, acol, bcol = (str(self._time_col), str(self._a_col), str(self._b_col))
        parity_a = parity_b = 0  # paridad acumulada para el modo "toggle"
        for frame in reader:
            t = frame[tcol].to_numpy(dtype=np.float64)
            a = frame[acol].to_numpy(dtype=np.float64)
            b = frame[bcol].to_numpy(dtype=np.float64)
            if self.digital_mode == "toggle":
                a, parity_a = toggles_to_levels(a, parity_a)
                b, parity_b = toggles_to_levels(b, parity_b)
            elec_data = {
                n: frame[str(self._electrode_cols[n])].to_numpy(dtype=np.float64)
                for n in elec
            }
            yield Chunk(t=t, a=a, b=b, electrodes=elec_data)
