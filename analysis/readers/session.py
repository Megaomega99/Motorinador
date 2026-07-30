"""Varios archivos de una misma toma leídos como una grabación continua.

El software de Intan parte las sesiones largas en archivos de un minuto: la toma
de referencia `intento serio 2_260729_142804` son **8 archivos** `.rhs` de ~165 MB.
Sin esto la herramienta solo puede mirar un minuto a la vez, que para una sesión
de 7 minutos con arranques y paradas no sirve de nada.

Los cortes de Intan son en frontera exacta de muestra y sin hueco, así que
concatenar es correcto: el decodificador de cuadratura y el contador de pasos
arrastran su estado a través de la frontera igual que entre dos segmentos del
mismo archivo.
"""

from __future__ import annotations

import os
from typing import Iterator, Sequence

import numpy as np

from .base import Chunk, Meta, Reader

# Extensiones que forman una sesión multiarchivo (el export tabular no se parte).
_SESSION_EXTS = (".rhs", ".rhd")


def session_files(path: str) -> list[str]:
    """Archivos de la sesión a la que pertenece ``path``, en orden temporal.

    ``path`` puede ser la carpeta de la toma o cualquiera de sus archivos. El
    nombre que genera Intan lleva la marca de tiempo (`..._143004.rhs`), así que
    el orden alfabético **es** el cronológico.
    """
    folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(
        os.path.join(folder, n) for n in names
        if os.path.splitext(n)[1].lower() in _SESSION_EXTS
    )


class SessionReader(Reader):
    """Presenta una secuencia de lectores como una única grabación.

    Se construye con lectores ya abiertos (así es testeable sin archivos reales);
    :meth:`from_paths` es el atajo para abrirlos desde rutas.
    """

    def __init__(self, readers: Sequence[Reader], path: str | None = None) -> None:
        if not readers:
            raise ValueError("Una sesión necesita al menos un archivo")
        self._readers = list(readers)
        self._metas = [r.metadata() for r in self._readers]
        self.path = path or os.path.dirname(self._metas[0].path)
        self._meta = self._build_meta()

    @classmethod
    def from_paths(cls, paths: Sequence[str]) -> "SessionReader":
        """Abre cada ruta con el lector que le corresponda y las une."""
        from .factory import open_single_reader

        if not paths:
            raise ValueError("Una sesión necesita al menos un archivo")
        return cls([open_single_reader(p) for p in paths],
                   path=os.path.dirname(os.path.abspath(paths[0])))

    def _build_meta(self) -> Meta:
        rates = {m.sample_rate_hz for m in self._metas}
        if len(rates) > 1:
            raise ValueError(
                f"Los archivos de la sesión no comparten frecuencia de muestreo: {sorted(rates)}"
            )
        # Solo los electrodos presentes en TODOS los archivos: si uno falta, la
        # columna tendría un hueco a mitad de sesión.
        common = set(self._metas[0].electrode_names)
        for m in self._metas[1:]:
            common &= set(m.electrode_names)
        names = [n for n in self._metas[0].electrode_names if n in common]

        has_motor = all(m.has_motor for m in self._metas)
        return Meta(
            path=self.path,
            sample_rate_hz=self._metas[0].sample_rate_hz,
            n_samples=sum(m.n_samples for m in self._metas),
            electrode_names=names,
            digital_names=list(self._metas[0].digital_names),
            fmt="session",
            motor_channel=self._metas[0].motor_channel if has_motor else None,
            n_parts=len(self._readers),
        )

    def metadata(self) -> Meta:
        return self._meta

    def part_boundaries_s(self) -> list[float]:
        """Instantes (s) en los que empieza cada archivo, para marcarlos en las gráficas."""
        dt = self._meta.dt
        out: list[float] = []
        pos = 0
        for m in self._metas:
            out.append(pos * dt)
            pos += m.n_samples
        return out

    def iter_chunks(
        self,
        chunk_samples: int,
        electrodes: list[str] | None = None,
    ) -> Iterator[Chunk]:
        elec = electrodes or []
        for name in elec:
            if name not in self._meta.electrode_names:
                raise ValueError(f"Electrodo desconocido en la sesión: {name}")

        dt = self._meta.dt
        offset = 0
        for reader in self._readers:
            for chunk in reader.iter_chunks(chunk_samples, electrodes=elec):
                length = len(chunk)
                if length == 0:
                    continue
                # El tiempo de cada lector arranca en 0 → se recoloca en la sesión.
                t = (np.arange(offset, offset + length, dtype=np.float64) * dt)
                yield Chunk(
                    t=t,
                    a=chunk.a,
                    b=chunk.b,
                    electrodes=chunk.electrodes,
                    motor=chunk.motor if self._meta.has_motor else None,
                )
                offset += length
