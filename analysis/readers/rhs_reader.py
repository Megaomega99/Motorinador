"""Lector del binario Intan `.rhs` (formato monolítico "header-attached").

Usa `neo.rawio.IntanRawIO`, que mapea el archivo con `np.memmap` y sirve
tramos vía `get_analogsignal_chunk` → la RAM se mantiene plana aunque el
archivo pese 137 MB.

Streams relevantes (verificado sobre datos reales):
  · stream 'RHS2000 amplifier channel' → 32 electrodos A-000..A-031 (µV)
  · stream 'USB board digital input'   → DIGITAL-IN-01 (A) y DIGITAL-IN-02 (B)
Ambos comparten fs = 30 kHz y el mismo número de muestras.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np

from .base import Chunk, Meta, Reader

_AMP_STREAM = "RHS2000 amplifier channel"
_DIG_STREAM = "USB board digital input channel"
_A_NAME = "DIGITAL-IN-01"
_B_NAME = "DIGITAL-IN-02"


class RhsReader(Reader):
    def __init__(self, path: str) -> None:
        from neo.rawio import IntanRawIO  # import perezoso: neo solo si se usa .rhs

        self.path = path
        self._io = IntanRawIO(filename=path)
        self._io.parse_header()
        self._resolve_streams()
        self._meta = self._build_meta()

    def _resolve_streams(self) -> None:
        streams = self._io.header["signal_streams"]
        self._amp_idx: int | None = None
        self._dig_idx: int | None = None
        for i, s in enumerate(streams):
            if str(s["name"]) == _AMP_STREAM:
                self._amp_idx = i
            elif str(s["name"]) == _DIG_STREAM:
                self._dig_idx = i
        if self._dig_idx is None:
            raise ValueError(f"{self.path}: no se encontró el stream digital del encoder")

        ch = self._io.header["signal_channels"]
        amp_id = streams[self._amp_idx]["id"] if self._amp_idx is not None else None
        self._electrode_names = [
            str(c["name"]) for c in ch
            if amp_id is not None and str(c["stream_id"]) == str(amp_id)
            and str(c["units"]).lower() == "uv"
        ]

    def _build_meta(self) -> Meta:
        fs = float(self._io.get_signal_sampling_rate(stream_index=self._dig_idx))
        n = int(self._io.get_signal_size(block_index=0, seg_index=0, stream_index=self._dig_idx))
        return Meta(
            path=self.path,
            sample_rate_hz=fs,
            n_samples=n,
            electrode_names=list(self._electrode_names),
            digital_names=[_A_NAME, _B_NAME],
            fmt="rhs",
        )

    def metadata(self) -> Meta:
        return self._meta

    def iter_chunks(
        self,
        chunk_samples: int,
        electrodes: list[str] | None = None,
    ) -> Iterator[Chunk]:
        elec = electrodes or []
        for name in elec:
            if name not in self._electrode_names:
                raise ValueError(f"Electrodo desconocido: {name}")

        n = self._meta.n_samples
        dt = self._meta.dt
        step = max(1, int(chunk_samples))
        for i0 in range(0, n, step):
            i1 = min(i0 + step, n)
            dig = self._io.get_analogsignal_chunk(
                block_index=0, seg_index=0, i_start=i0, i_stop=i1,
                stream_index=self._dig_idx, channel_names=[_A_NAME, _B_NAME],
            )
            a = dig[:, 0].astype(np.float64)
            b = dig[:, 1].astype(np.float64)
            t = np.arange(i0, i1, dtype=np.float64) * dt

            elec_data: dict[str, np.ndarray] = {}
            if elec and self._amp_idx is not None:
                raw = self._io.get_analogsignal_chunk(
                    block_index=0, seg_index=0, i_start=i0, i_stop=i1,
                    stream_index=self._amp_idx, channel_names=elec,
                )
                scaled = self._io.rescale_signal_raw_to_float(
                    raw, stream_index=self._amp_idx, channel_names=elec,
                )
                for j, name in enumerate(elec):
                    elec_data[name] = scaled[:, j].astype(np.float64)

            yield Chunk(t=t, a=a, b=b, electrodes=elec_data)
