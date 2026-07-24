"""Lector falso para tests: entrega segmentos con A/B y electrodos conocidos."""

from __future__ import annotations

from typing import Iterator

import numpy as np

from analysis.readers.base import Chunk, Meta


class FakeReader:
    def __init__(self, a, b, electrodes, fs=30000.0, chunk=None):
        self.a = np.asarray(a, dtype=np.float64)
        self.b = np.asarray(b, dtype=np.float64)
        self.elec = {k: np.asarray(v, dtype=np.float64) for k, v in electrodes.items()}
        self.fs = fs
        self.n = self.a.shape[0]

    def metadata(self) -> Meta:
        return Meta(
            path="<fake>",
            sample_rate_hz=self.fs,
            n_samples=self.n,
            electrode_names=sorted(self.elec),
            digital_names=["DIGITAL-IN-01", "DIGITAL-IN-02"],
            fmt="txt",
        )

    def iter_chunks(self, chunk_samples: int, electrodes=None) -> Iterator[Chunk]:
        names = electrodes or []
        for i0 in range(0, self.n, chunk_samples):
            i1 = min(i0 + chunk_samples, self.n)
            t = np.arange(i0, i1, dtype=np.float64) / self.fs
            ed = {n: self.elec[n][i0:i1] for n in names}
            yield Chunk(t=t, a=self.a[i0:i1], b=self.b[i0:i1], electrodes=ed)


def spinning_quadrature(cycles: int, samples_per_state: int = 100):
    """Genera A/B de una rotación uniforme en sentido +.

    Devuelve (a, b) con `cycles` ciclos eléctricos, cada estado mantenido
    `samples_per_state` muestras → señal de nivel (no toggle).
    """
    seq = [(0, 0), (0, 1), (1, 1), (1, 0)]  # sentido + (00→01→11→10)
    a: list[int] = []
    b: list[int] = []
    for _ in range(cycles):
        for sa, sb in seq:
            a += [sa] * samples_per_state
            b += [sb] * samples_per_state
    return np.array(a, dtype=np.float64), np.array(b, dtype=np.float64)
