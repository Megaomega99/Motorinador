"""Validación cruzada sobre los datos reales de intento_260724_104300.

Se salta automáticamente si los archivos grandes no están presentes (p. ej.
en CI). Comprueba que el ángulo reconstruido desde el `.txt` (columnas de
flanco) coincide con el del binario `.rhs` (niveles nativos) de la misma sesión.
"""

from __future__ import annotations

import os

import pytest

from analysis.encoder import QuadratureDecoder
from analysis.readers.factory import open_reader

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "intento_260724_104300",
)
_TXT = os.path.join(_DIR, "textform.txt")
_RHS = os.path.join(_DIR, "intento_260724_104300.rhs")

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(_TXT) and os.path.isfile(_RHS)),
    reason="Datos reales no disponibles",
)


def _net_count(path: str) -> int:
    dec = QuadratureDecoder()
    last = 0
    for ch in open_reader(path).iter_chunks(chunk_samples=200_000):
        last = int(dec.process(ch.a, ch.b)[-1])
    return last


def test_txt_and_rhs_agree_on_net_count():
    assert _net_count(_TXT) == _net_count(_RHS)


def test_rhs_metadata_matches_expected():
    m = open_reader(_RHS).metadata()
    assert m.sample_rate_hz == 30000.0
    assert m.n_samples == 1070848
    assert len(m.electrode_names) == 32
