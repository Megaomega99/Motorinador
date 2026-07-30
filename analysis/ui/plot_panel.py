"""Panel de gráficas embebido (matplotlib) para la ventana visible.

Cuatro sub-gráficas con eje X (tiempo) compartido:

  1. electrodos elegidos (µV)
  2. ángulo del encoder
  3. velocidad angular del encoder
  4. **motor**: RPM comandada (del espejo STEP) frente a RPM medida referida al
     eje del motor (encoder ÷ relación de engranajes). El hueco entre las dos
     curvas *es* el deslizamiento: si el motor pierde pasos o se atasca, la
     medida cae por debajo de la consigna y se ve de un vistazo.

La cuarta gráfica solo aparece si la grabación trae la señal del motor.
Toda traza se decima a ~``max_points`` puntos antes de dibujarse, así una
ventana de cientos de miles de muestras se pinta al instante.
"""

from __future__ import annotations

import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from ..gearing import enc_rpm_to_motor_rpm
from ..processing import SessionCache, decimate_minmax
from ..units import GEAR_RATIO_DEFAULT, AngleUnit, VelocityUnit

_MAX_POINTS = 4000


class PlotPanel(tk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.fig = Figure(figsize=(7, 7.5), constrained_layout=True)
        self.ax_elec = self.fig.add_subplot(4, 1, 1)
        self.ax_ang = self.fig.add_subplot(4, 1, 2, sharex=self.ax_elec)
        self.ax_vel = self.fig.add_subplot(4, 1, 3, sharex=self.ax_elec)
        self.ax_motor = self.fig.add_subplot(4, 1, 4, sharex=self.ax_elec)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        for ax in self._axes():
            ax.clear()
        self.ax_elec.set_title("Abre un archivo (.txt / .rhs) o una carpeta de sesión")
        self.canvas.draw_idle()

    def _axes(self):
        return (self.ax_elec, self.ax_ang, self.ax_vel, self.ax_motor)

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
        gear_ratio: float = GEAR_RATIO_DEFAULT,
        motor_window_samples: int | None = None,
    ) -> None:
        for ax in self._axes():
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

        # ── Velocidad angular del encoder ───────────────────────
        vel = cache.velocity_slice(i0, i1, vel_unit, window_samples)
        dec = decimate_minmax(t, vel, _MAX_POINTS)
        self.ax_vel.plot(dec.t, dec.y, color="tab:red", linewidth=0.8)
        self.ax_vel.set_ylabel(f"Vel. encoder ({vel_unit.value})")

        self._draw_motor(cache, i0, i1, t,
                         motor_window_samples or window_samples, gear_ratio)

        for ax in self._axes():
            ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()

    def _draw_motor(self, cache, i0, i1, t, window_samples, gear_ratio) -> None:
        """Cuarta gráfica: consigna del motor vs medida referida al motor.

        ``window_samples`` es aquí la *ventana de motor* (más larga que la del
        panel del encoder): el tren de engranajes resuena y sin ese promediado la
        curva medida tapa por completo a la consigna.
        """
        self.ax_motor.set_xlabel("Tiempo (s)")
        if not cache.has_motor:
            self.ax_motor.set_ylabel("Motor (RPM)")
            self.ax_motor.text(
                0.5, 0.5, "Esta grabación no incluye ANALOG-IN-2 (espejo STEP)",
                transform=self.ax_motor.transAxes, ha="center", va="center",
                fontsize=9, color="#888",
            )
            return

        cmd = cache.motor_rpm_slice(i0, i1)
        dec = decimate_minmax(t, cmd, _MAX_POINTS)
        self.ax_motor.plot(dec.t, dec.y, color="tab:green", linewidth=1.1,
                           label="Comandada (STEP)")

        # Medida del encoder llevada al eje del motor: comparable con la consigna.
        enc = cache.velocity_slice(i0, i1, VelocityUnit.RPM, window_samples)
        meas = enc_rpm_to_motor_rpm(abs(enc), gear_ratio)
        dec = decimate_minmax(t, meas, _MAX_POINTS)
        self.ax_motor.plot(dec.t, dec.y, color="tab:purple", linewidth=0.8, alpha=0.85,
                           label=f"Medida (encoder ÷ {gear_ratio:g})")

        self.ax_motor.set_ylabel("Motor (RPM)")
        self.ax_motor.legend(loc="upper right", fontsize=8)
