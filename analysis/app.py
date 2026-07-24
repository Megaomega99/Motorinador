"""Punto de entrada de la GUI de análisis de encoder.

Uso:
    python -m analysis.app
"""

from __future__ import annotations

import matplotlib

matplotlib.use("TkAgg")  # backend embebible en Tkinter (antes de importar la UI)

from .ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
