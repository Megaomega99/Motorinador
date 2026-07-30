"""Interfaz común de los lectores de grabaciones.

Un lector expone metadatos y permite iterar la señal **por segmentos**
(chunks) sin cargar el archivo completo en RAM. Las dos señales digitales
del encoder (A = DIGITAL-IN-01, B = DIGITAL-IN-02) siempre están presentes;
los electrodos se incluyen solo si se piden, para no mover 32 canales cuando
solo hace falta reconstruir el ángulo.

Desde la toma `intento serio 2_260729_142804` hay además una entrada analógica
(`ANALOG-IN-2`) con el espejo del pulso STEP del firmware, de la que sale la
velocidad **comandada** del motor (ver analysis/motor.py). Es opcional: las
grabaciones anteriores no la tienen y siguen funcionando con
``motor_channel = None`` / ``Chunk.motor = None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class Meta:
    """Metadatos de una grabación."""

    path: str
    sample_rate_hz: float
    n_samples: int
    electrode_names: list[str]  # p. ej. ["A-000", ..., "A-031"]
    digital_names: list[str]    # p. ej. ["DIGITAL-IN-01", "DIGITAL-IN-02"]
    fmt: str                    # "txt" | "rhs" | "session"
    motor_channel: str | None = None   # p. ej. "ANALOG-IN-2"; None si no se grabó
    n_parts: int = 1                   # >1 en una sesión de varios archivos

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate_hz if self.sample_rate_hz else 0.0

    @property
    def dt(self) -> float:
        return 1.0 / self.sample_rate_hz if self.sample_rate_hz else 0.0

    @property
    def has_motor(self) -> bool:
        """True si la grabación trae el espejo STEP (velocidad del motor)."""
        return self.motor_channel is not None


@dataclass
class Chunk:
    """Un segmento contiguo de muestras."""

    t: np.ndarray                                  # tiempo (s)
    a: np.ndarray                                  # canal A (0/1)
    b: np.ndarray                                  # canal B (0/1)
    electrodes: dict[str, np.ndarray] = field(default_factory=dict)  # nombre → µV
    motor: np.ndarray | None = None                # espejo STEP (V), None si no hay

    def __len__(self) -> int:
        return int(self.t.shape[0])


@runtime_checkable
class Reader(Protocol):
    """Contrato de un lector de grabaciones."""

    def metadata(self) -> Meta: ...

    def iter_chunks(
        self,
        chunk_samples: int,
        electrodes: list[str] | None = None,
    ) -> Iterator[Chunk]:
        """Itera la señal por segmentos de ``chunk_samples`` muestras.

        Si ``electrodes`` es None solo se devuelven tiempo + A/B (pasada
        barata); si es una lista de nombres, se incluyen esos electrodos.
        """
        ...
