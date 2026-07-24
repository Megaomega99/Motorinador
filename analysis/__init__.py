"""Herramienta offline de análisis de encoder y electrodos.

Reconstruye el ángulo y la velocidad angular del motor a partir de las dos
señales digitales de cuadratura (DIGITAL-IN-01/02) grabadas junto a los
electrodos, procesando por segmentos para no saturar la RAM. Ver README.md.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
