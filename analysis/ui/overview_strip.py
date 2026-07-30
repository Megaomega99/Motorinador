"""Tira de vista general de la sesión, para navegar de un vistazo.

En una sesión real de 7 minutos el motor está parado la mayor parte del tiempo
(en la toma de referencia, 235 s de 437 s). Buscar los tramos en marcha
arrastrando el deslizador a ciegas es el punto más incómodo de la herramienta.

Esta tira dibuja **toda** la sesión decimada —velocidad comandada del motor, o
la del encoder si la grabación no trae el espejo STEP— y sombrea la ventana que
se está viendo. Un clic (o arrastre) mueve la ventana a ese instante.

La serie se calcula UNA vez al cargar y se reutiliza: sobre 13 M de muestras
recalcularla en cada redibujado costaría ~1 s por interacción.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from ..processing import Overview, SessionCache
from ..units import VelocityUnit

_MAX_POINTS = 3000


class OverviewStrip(tk.Frame):
    """Vista general navegable de la sesión completa."""

    def __init__(self, parent: tk.Misc, on_seek: Callable[[float], None]) -> None:
        super().__init__(parent)
        self._on_seek = on_seek
        self._duration = 0.0
        self._span: tuple[float, float] | None = None

        self.fig = Figure(figsize=(7, 1.15), constrained_layout=True)
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_drag)
        self._clear("Vista general de la sesión")

    # ── ciclo de vida ────────────────────────────────────────────
    def _clear(self, title: str) -> None:
        self.ax.clear()
        self.ax.set_title(title, fontsize=8)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw_idle()

    def set_session(self, cache: SessionCache) -> None:
        """Calcula y dibuja la vista general (una vez por sesión)."""
        self._duration = cache.duration_s
        self._span = None
        if cache.has_motor:
            self._series: Overview = cache.motor_rpm_overview(max_points=_MAX_POINTS)
            self._label = "RPM motor (consigna)"
            self._color = "tab:green"
        else:
            self._series = cache.velocity_overview(
                VelocityUnit.RPM, window_samples=max(1, int(0.05 * cache.sample_rate_hz)),
                max_points=_MAX_POINTS,
            )
            self._label = "RPM encoder"
            self._color = "tab:red"
        self._boundaries = cache.n_parts > 1
        self._redraw()

    def set_window(self, t0: float, t1: float) -> None:
        """Sombrea la ventana visible sin recalcular la serie."""
        if self._duration <= 0:
            return
        self._span = (t0, t1)
        self._redraw()

    # ── dibujo ───────────────────────────────────────────────────
    def _redraw(self) -> None:
        if self._duration <= 0:
            return
        self.ax.clear()
        self.ax.plot(self._series.t, self._series.y, color=self._color, linewidth=0.7)
        self.ax.set_xlim(0.0, self._duration)
        self.ax.set_ylabel(self._label, fontsize=7)
        self.ax.tick_params(labelsize=7)
        self.ax.set_yticks([])
        self.ax.set_title(
            "Vista general — clic para saltar a ese instante", fontsize=8
        )
        if self._span is not None:
            t0, t1 = self._span
            # Ventana mínima visible: en una sesión de 437 s, 5 s son ~1 px.
            width = max(t1 - t0, self._duration * 0.004)
            self.ax.axvspan(t0, t0 + width, color="tab:blue", alpha=0.25, zorder=3)
        self.ax.grid(True, axis="x", alpha=0.25)
        self.canvas.draw_idle()

    # ── interacción ──────────────────────────────────────────────
    def _on_click(self, event) -> None:
        self._seek_from(event)

    def _on_drag(self, event) -> None:
        # button == 1 → arrastrando con el botón izquierdo pulsado.
        if getattr(event, "button", None) == 1:
            self._seek_from(event)

    def _seek_from(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or self._duration <= 0:
            return
        self._on_seek(max(0.0, min(float(event.xdata), self._duration)))
