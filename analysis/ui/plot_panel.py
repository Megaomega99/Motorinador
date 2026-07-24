"""Panel de gráficas embebido (matplotlib) para la ventana visible.

Tres sub-gráficas con eje X (tiempo) compartido: electrodos elegidos, ángulo y
velocidad angular. Toda traza se decima a ~``max_points`` puntos antes de
dibujarse, así una ventana de cientos de miles de muestras se pinta al instante.
"""

from __future__ import annotations

import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from ..processing import SessionCache, decimate_minmax
from ..units import AngleUnit, VelocityUnit

_MAX_POINTS = 4000


class PlotPanel(tk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.fig = Figure(figsize=(7, 6), constrained_layout=True)
        self.ax_elec = self.fig.add_subplot(3, 1, 1)
        self.ax_ang = self.fig.add_subplot(3, 1, 2, sharex=self.ax_elec)
        self.ax_vel = self.fig.add_subplot(3, 1, 3, sharex=self.ax_elec)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        for ax in (self.ax_elec, self.ax_ang, self.ax_vel):
            ax.clear()
        self.ax_elec.set_title("Abre un archivo (.txt o .rhs) para empezar")
        self.canvas.draw_idle()

    def draw_window(
        self,
        cache: SessionCache,
        i0: int,
        i1: int,
        electrodes: list[str],
        angle_unit: AngleUnit,
        vel_unit: VelocityUnit,
        window_samples: int,
        wrap_angle: bool = False,
    ) -> None:
        for ax in (self.ax_elec, self.ax_ang, self.ax_vel):
            ax.clear()

        t = cache.time_slice(i0, i1)

        # ── Electrodos ──────────────────────────────────────────
        for name in electrodes:
            y = cache.electrode_slice(name, i0, i1)
            dec = decimate_minmax(t, y, _MAX_POINTS)
            self.ax_elec.plot(dec.t, dec.y, linewidth=0.7, label=name)
        self.ax_elec.set_ylabel("Electrodos (µV)")
        if electrodes:
            self.ax_elec.legend(loc="upper right", fontsize=8, ncol=max(1, len(electrodes) // 2))

        # ── Ángulo ──────────────────────────────────────────────
        ang = cache.angle_slice(i0, i1, angle_unit, wrap=wrap_angle)
        dec = decimate_minmax(t, ang, _MAX_POINTS)
        self.ax_ang.plot(dec.t, dec.y, color="tab:blue", linewidth=0.8)
        self.ax_ang.set_ylabel(f"Ángulo ({angle_unit.value})")

        # ── Velocidad angular ───────────────────────────────────
        vel = cache.velocity_slice(i0, i1, vel_unit, window_samples)
        dec = decimate_minmax(t, vel, _MAX_POINTS)
        self.ax_vel.plot(dec.t, dec.y, color="tab:red", linewidth=0.8)
        self.ax_vel.set_ylabel(f"Velocidad ({vel_unit.value})")
        self.ax_vel.set_xlabel("Tiempo (s)")

        for ax in (self.ax_elec, self.ax_ang, self.ax_vel):
            ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()
