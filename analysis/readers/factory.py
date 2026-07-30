"""Selección del lector adecuado según la extensión y los magic bytes."""

from __future__ import annotations

import os

from .base import Reader

# Magic number del formato Intan RHS (little-endian 0xac2791d6).
_RHS_MAGIC = bytes([0xAC, 0x27, 0x91, 0xD6])


def _looks_like_rhs(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == _RHS_MAGIC
    except OSError:
        return False


def open_single_reader(path: str) -> Reader:
    """Lector para **un** archivo (txt tabular o binario rhs)."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".rhs" or _looks_like_rhs(path):
        from .rhs_reader import RhsReader
        return RhsReader(path)

    if ext in {".txt", ".csv", ".tsv"}:
        from .txt_reader import TxtReader
        return TxtReader(path)

    raise ValueError(
        f"Formato no soportado: {ext!r}. Se aceptan .txt (export Intan) y .rhs. "
        "Los .smrx/.s2rx (Spike2) no se soportan en este entorno."
    )


def open_reader(path: str, whole_session: bool = False) -> Reader:
    """Devuelve un :class:`Reader` para ``path``.

    Si ``path`` es una **carpeta**, se abre como sesión completa (todos sus `.rhs`
    en orden temporal como una sola grabación continua). Si es un archivo,
    ``whole_session=True`` amplía la lectura a todos sus hermanos de la misma
    carpeta — útil porque Intan parte las tomas largas en archivos de un minuto.
    """
    from .session import SessionReader, session_files

    if os.path.isdir(path):
        files = session_files(path)
        if not files:
            raise ValueError(f"La carpeta no contiene archivos .rhs: {path}")
        return SessionReader.from_paths(files) if len(files) > 1 else open_single_reader(files[0])

    if whole_session:
        files = session_files(path)
        if len(files) > 1:
            return SessionReader.from_paths(files)

    return open_single_reader(path)
