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


def open_reader(path: str) -> Reader:
    """Devuelve un :class:`Reader` para ``path`` (txt tabular o binario rhs)."""
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
