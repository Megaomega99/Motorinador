"""Lector del binario Intan `.rhs` (formato monolítico "header-attached").

Usa `neo.rawio.IntanRawIO`, que mapea el archivo con `np.memmap` y sirve
tramos vía `get_analogsignal_chunk` → la RAM se mantiene plana aunque el
archivo pese 137 MB.

Streams relevantes (verificado sobre datos reales):
  · stream 'RHS2000 amplifier channel'   → electrodos A-0xx (µV)
  · stream 'USB board digital input'     → DIGITAL-IN-01 (A) y DIGITAL-IN-02 (B)
  · stream 'USB board ADC input channel' → ANALOG-IN-2 (V): espejo del pulso STEP
Todos comparten fs = 30 kHz y el mismo número de muestras.

El stream ADC solo existe en las tomas nuevas; si falta, `motor_channel` es None
y la herramienta trabaja igual que antes (solo encoder).
"""

from __future__ import annotations

from typing import Iterator

import numpy as np

from .base import Chunk, Meta, Reader

_AMP_STREAM = "RHS2000 amplifier channel"
_DIG_STREAM = "USB board digital input channel"
_ADC_STREAM = "USB board ADC input channel"
_A_NAME = "DIGITAL-IN-01"
_B_NAME = "DIGITAL-IN-02"
# Canal del espejo STEP. Si no está, se usa el primer canal ADC disponible.
_MOTOR_NAME = "ANALOG-IN-2"


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
        self._adc_idx: int | None = None
        for i, s in enumerate(streams):
            if str(s["name"]) == _AMP_STREAM:
                self._amp_idx = i
            elif str(s["name"]) == _DIG_STREAM:
                self._dig_idx = i
            elif str(s["name"]) == _ADC_STREAM:
                self._adc_idx = i
        if self._dig_idx is None:
            raise ValueError(f"{self.path}: no se encontró el stream digital del encoder")

        ch = self._io.header["signal_channels"]
        amp_id = streams[self._amp_idx]["id"] if self._amp_idx is not None else None
        self._electrode_names = [
            str(c["name"]) for c in ch
            if amp_id is not None and str(c["stream_id"]) == str(amp_id)
            and str(c["units"]).lower() == "uv"
        ]
        self._motor_name = self._resolve_motor_channel(streams, ch)

    def _resolve_motor_channel(self, streams, ch) -> str | None:
        """Nombre del canal ADC con el espejo STEP, o None si no se grabó."""
        if self._adc_idx is None:
            return None
        adc_id = str(streams[self._adc_idx]["id"])
        names = [str(c["name"]) for c in ch if str(c["stream_id"]) == adc_id]
        if not names:
            return None
        return _MOTOR_NAME if _MOTOR_NAME in names else names[0]

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
            motor_channel=self._motor_name,
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

            yield Chunk(t=t, a=a, b=b, electrodes=elec_data,
                        motor=self._read_motor(i0, i1))

    def _read_motor(self, i0: int, i1: int) -> np.ndarray | None:
        """Espejo STEP del tramo [i0,i1) en voltios, o None si no se grabó."""
        if self._adc_idx is None or self._motor_name is None:
            return None
        raw = self._io.get_analogsignal_chunk(
            block_index=0, seg_index=0, i_start=i0, i_stop=i1,
            stream_index=self._adc_idx, channel_names=[self._motor_name],
        )
        volts = self._io.rescale_signal_raw_to_float(
            raw, stream_index=self._adc_idx, channel_names=[self._motor_name],
        )
        return volts[:, 0].astype(np.float64)
