"""Ventana principal: orquesta lectura, caché, gráficas y estadísticos.

La construcción de la caché y la exportación corren en hilos de fondo para no
congelar la interfaz; el progreso se comunica por una cola y se vuelca a la UI
desde el hilo principal con ``after`` (Tkinter no es thread-safe).
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox


from ..exporter import export
from ..gearing import GearEstimate
from ..processing import SessionCache, build_cache
from ..readers.factory import open_reader
from .controls import ControlCallbacks, ControlsPanel
from .overview_strip import OverviewStrip
from .plot_panel import PlotPanel
from .stats_panel import StatsPanel


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Análisis de encoder, motor y electrodos")
        self.geometry("1280x820")

        self._cache: SessionCache | None = None
        self._cache_path: str | None = None
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._gear_est: GearEstimate | None = None

        callbacks = ControlCallbacks(
            on_open=self._on_open,
            on_settings_changed=self._on_settings_changed,
            on_navigate=self._redraw,
            on_export=self._on_export,
            on_open_session=self._on_open_session,
            on_estimate_ratio=self._on_estimate_ratio,
        )
        self.controls = ControlsPanel(self, callbacks)
        self.controls.pack(side=tk.LEFT, fill=tk.Y)

        self.stats = StatsPanel(self)
        self.stats.pack(side=tk.RIGHT, fill=tk.Y, padx=6)

        # Zona central: tira de vista general arriba + gráficas de la ventana.
        center = tk.Frame(self)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.overview = OverviewStrip(center, on_seek=self._on_seek)
        self.overview.pack(side=tk.TOP, fill=tk.X)
        self.plot = PlotPanel(center)
        self.plot.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── abrir archivo ────────────────────────────────────────────
    def _on_open(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Seleccionar grabación",
            filetypes=[("Grabaciones", "*.txt *.rhs"), ("Todos", "*.*")],
        )
        if path:
            self._start_build(path, whole_session=False)

    def _on_open_session(self) -> None:
        """Abre una carpeta con varios `.rhs` como una única grabación continua."""
        if self._busy:
            return
        folder = filedialog.askdirectory(title="Seleccionar carpeta de la sesión")
        if folder:
            self._start_build(folder, whole_session=True)

    def _start_build(self, path: str, whole_session: bool) -> None:
        label = os.path.basename(path.rstrip(os.sep)) or path
        self._set_busy(True, f"Procesando {label}...")
        self.controls.set_file_label(label)
        threading.Thread(target=self._worker_build, args=(path, whole_session),
                         daemon=True).start()
        self.after(100, self._poll_build)

    def _worker_build(self, path: str, whole_session: bool = False) -> None:
        try:
            reader = open_reader(path, whole_session=whole_session)
            fd, cache_path = tempfile.mkstemp(suffix=".h5", prefix="encoder_cache_")
            os.close(fd)
            build_cache(reader, cache_path, progress_cb=lambda f: self._queue.put(("progress", f)))
            self._queue.put(("done", cache_path))
        except Exception as exc:  # noqa: BLE001 — se reporta al usuario en la UI
            self._queue.put(("error", str(exc)))

    def _poll_build(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.controls.set_progress(payload)
                elif kind == "done":
                    self._on_cache_ready(payload)
                    return
                elif kind == "error":
                    self._set_busy(False, "")
                    messagebox.showerror("Error al procesar", payload)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_build)

    def _on_cache_ready(self, cache_path: str) -> None:
        self._close_cache()
        self._cache_path = cache_path
        self._cache = SessionCache(cache_path)
        self.controls.set_electrodes(self._cache.electrode_names)
        self.controls.configure_duration(self._cache.duration_s)
        parts = (f" - {self._cache.n_parts} archivos" if self._cache.n_parts > 1 else "")
        motor = " - con señal de motor" if self._cache.has_motor else " - SIN señal de motor"
        self._set_busy(
            False,
            f"{self._cache.n_samples} muestras - {self._cache.duration_s:.2f} s{parts}{motor}",
        )
        # Con las dos señales la relación se mide, no se supone: se estima al
        # cargar y se adopta como valor de trabajo.
        self._gear_est = None
        if self._cache.has_motor:
            self._on_estimate_ratio(adopt=True)
        else:
            self.controls.set_ratio_info("Sin ANALOG-IN-2: no se puede medir.")
        self.stats.update_gearing(self._gear_est)
        self.overview.set_session(self._cache)
        self._update_session_stats()
        self._redraw()

    # ── ajustes / navegación ─────────────────────────────────────
    def _on_settings_changed(self) -> None:
        if self._cache is None:
            return
        self._update_session_stats()
        self._redraw()

    def _on_seek(self, t: float) -> None:
        """Salto desde la tira de vista general: centra la ventana en ``t``."""
        if self._cache is None:
            return
        half = self.controls.get_window_len_s() / 2.0
        start = max(0.0, min(t - half, max(0.0, self._cache.duration_s - 2 * half)))
        self.controls.start_s.set(start)
        self._redraw()

    def _on_estimate_ratio(self, adopt: bool = False) -> None:
        """Mide la relación de engranajes con las dos señales de la grabación."""
        if self._cache is None or not self._cache.has_motor:
            self.controls.set_ratio_info("Sin ANALOG-IN-2: no se puede medir.")
            return
        est = self._cache.gear_estimate()
        self._gear_est = est
        self.stats.update_gearing(est)
        if est.ratio is None:
            self.controls.set_ratio_info("Sin tramos con consigna estable para medir.")
            return
        if adopt:
            self.controls.set_gear_ratio(est.ratio)
        self.controls.set_ratio_info(
            f"Medido: {est.ratio:.4f} en {est.n_steady} ventanas; "
            f"pérdida de paso en {est.n_stall} ({est.stall_pct:.1f} %)."
        )

    def _window_samples(self) -> int:
        assert self._cache is not None
        return max(1, int(round(self.controls.get_window_ms() / 1000.0 * self._cache.sample_rate_hz)))

    def _motor_window_samples(self) -> int:
        """Ventana de suavizado para comparar la medida con la consigna del motor."""
        assert self._cache is not None
        ms = self.controls.get_motor_window_ms()
        return max(1, int(round(ms / 1000.0 * self._cache.sample_rate_hz)))

    def _update_session_stats(self) -> None:
        assert self._cache is not None
        stats = self._cache.session_stats(self.controls.get_vel_unit(), self._window_samples())
        self.stats.update_session(stats)

    def _redraw(self) -> None:
        if self._cache is None:
            return
        c = self._cache
        i0 = c.sample_at(self.controls.get_start_s())
        i1 = c.clamp(i0 + int(round(self.controls.get_window_len_s() * c.sample_rate_hz)))
        if i1 <= i0:
            return
        win = self._window_samples()
        motor_win = self._motor_window_samples()
        vel_unit = self.controls.get_vel_unit()
        ratio = self.controls.get_gear_ratio()
        self.plot.draw_window(
            c, i0, i1,
            electrodes=self.controls.get_selected_electrodes(),
            angle_unit=self.controls.get_angle_unit(),
            vel_unit=vel_unit,
            window_samples=win,
            wrap_angle=self.controls.get_wrap(),
            gear_ratio=ratio,
            motor_window_samples=motor_win,
        )
        self.stats.update_window(c.window_stats(i0, i1, vel_unit, win))
        self._update_motor_summary(i0, i1, motor_win, ratio)
        self.overview.set_window(i0 * c.dt, i1 * c.dt)

    def _update_motor_summary(self, i0: int, i1: int, motor_win: int, ratio: float) -> None:
        """Consigna, medida referida al motor y deslizamiento de la ventana visible.

        Usa la misma ventana que la gráfica del motor para que las cifras y la
        curva cuenten lo mismo.
        """
        c = self._cache
        assert c is not None
        self.stats.update_motor(
            c.motor_summary(i0, i1, ratio, motor_win) if c.has_motor else None
        )

    # ── exportar ─────────────────────────────────────────────────
    def _on_export(self) -> None:
        if self._cache is None or self._busy:
            return
        out = filedialog.asksaveasfilename(
            title="Exportar sesión",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Texto (TSV)", "*.txt"), ("HDF5", "*.h5")],
        )
        if not out:
            return
        self._set_busy(True, f"Exportando a {os.path.basename(out)}...")
        args = (
            out, self.controls.get_angle_unit(), self.controls.get_vel_unit(),
            self._window_samples(), self.controls.get_gear_ratio(),
            self._motor_window_samples(),
        )
        threading.Thread(target=self._worker_export, args=args, daemon=True).start()
        self.after(100, self._poll_export)

    def _worker_export(self, out, angle_unit, vel_unit, window_samples, gear_ratio,
                       motor_window_samples) -> None:
        try:
            export(
                self._cache, out, angle_unit, vel_unit, window_samples,
                gear_ratio=gear_ratio, motor_window_samples=motor_window_samples,
                progress_cb=lambda f: self._queue.put(("progress", f)),
            )
            self._queue.put(("export_done", out))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("error", str(exc)))

    def _poll_export(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.controls.set_progress(payload)
                elif kind == "export_done":
                    self._set_busy(False, f"Exportado: {os.path.basename(payload)}")
                    messagebox.showinfo("Exportación completa", f"Archivo escrito:\n{payload}")
                    return
                elif kind == "error":
                    self._set_busy(False, "")
                    messagebox.showerror("Error al exportar", payload)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_export)

    # ── utilidades ───────────────────────────────────────────────
    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        self.controls.enable(not busy)
        self.controls.set_status(status)
        if not busy:
            self.controls.set_progress(0.0)

    def _close_cache(self) -> None:
        if self._cache is not None:
            self._cache.close()
            self._cache = None
        if self._cache_path and os.path.exists(self._cache_path):
            try:
                os.remove(self._cache_path)
            except OSError:
                pass
        self._cache_path = None

    def _on_close(self) -> None:
        self._close_cache()
        self.destroy()
