"""Panel de controles: archivo, unidades, ventana de suavizado, electrodos y navegación."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable

from ..units import AngleUnit, VelocityUnit


@dataclass
class ControlCallbacks:
    on_open: Callable[[], None]
    on_settings_changed: Callable[[], None]
    on_navigate: Callable[[], None]
    on_export: Callable[[], None]


class ControlsPanel(tk.Frame):
    def __init__(self, parent: tk.Misc, callbacks: ControlCallbacks) -> None:
        super().__init__(parent, padx=8, pady=8)
        self._cb = callbacks
        self._build_file()
        self._build_units()
        self._build_electrodes()
        self._build_navigation()
        self._build_export()
        self._build_progress()
        self.enable(False)

    # ── secciones ────────────────────────────────────────────────
    def _build_file(self) -> None:
        # El botón de abrir SIEMPRE está habilitado (no depende de datos cargados).
        self._open_btn = tk.Button(self, text="Abrir archivo (.txt / .rhs)...",
                                   command=self._cb.on_open)
        self._open_btn.pack(fill=tk.X)
        self._file_lbl = tk.Label(self, text="Sin archivo", fg="#666", anchor="w", wraplength=240)
        self._file_lbl.pack(fill=tk.X, pady=(2, 8))

    def _build_units(self) -> None:
        self.angle_unit = tk.StringVar(value=AngleUnit.DEG.value)
        self.vel_unit = tk.StringVar(value=VelocityUnit.RPM.value)
        self.window_ms = tk.StringVar(value="50")
        self.wrap = tk.BooleanVar(value=False)

        frm = ttk.LabelFrame(self, text="Unidades y cálculo")
        frm.pack(fill=tk.X, pady=4)

        ttk.Label(frm, text="Ángulo:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Combobox(
            frm, textvariable=self.angle_unit, state="readonly", width=10,
            values=[u.value for u in AngleUnit],
        ).grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Label(frm, text="Velocidad:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Combobox(
            frm, textvariable=self.vel_unit, state="readonly", width=10,
            values=[u.value for u in VelocityUnit],
        ).grid(row=1, column=1, sticky="ew", padx=4)

        ttk.Label(frm, text="Ventana vel. (ms):").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Spinbox(
            frm, from_=1, to=2000, increment=5, textvariable=self.window_ms, width=10,
            command=self._cb.on_settings_changed,
        ).grid(row=2, column=1, sticky="ew", padx=4)

        ttk.Checkbutton(
            frm, text="Envolver ángulo [0, vuelta)", variable=self.wrap,
            command=self._cb.on_settings_changed,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=2)

        frm.columnconfigure(1, weight=1)
        for var in (self.angle_unit, self.vel_unit):
            var.trace_add("write", lambda *_: self._cb.on_settings_changed())
        self.window_ms.trace_add("write", lambda *_: self._cb.on_settings_changed())

    def _build_electrodes(self) -> None:
        frm = ttk.LabelFrame(self, text="Electrodos (elige 3 o mas, Ctrl/Shift)")
        frm.pack(fill=tk.BOTH, expand=True, pady=4)
        self._listbox = tk.Listbox(frm, selectmode=tk.EXTENDED, height=8, exportselection=False)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        sb = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self._listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)
        self._listbox.config(yscrollcommand=sb.set)
        self._listbox.bind("<<ListboxSelect>>", lambda _e: self._cb.on_settings_changed())

    def _build_navigation(self) -> None:
        frm = ttk.LabelFrame(self, text="Navegación por segmentos")
        frm.pack(fill=tk.X, pady=4)

        self.window_len = tk.StringVar(value="5.0")
        ttk.Label(frm, text="Ventana (s):").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Spinbox(
            frm, from_=0.1, to=3600, increment=1.0, textvariable=self.window_len, width=8,
            command=self._on_window_len,
        ).grid(row=0, column=1, sticky="ew", padx=4)
        self.window_len.trace_add("write", lambda *_: self._on_window_len())

        self.start_s = tk.DoubleVar(value=0.0)
        self._scale = ttk.Scale(
            frm, from_=0.0, to=1.0, orient=tk.HORIZONTAL, variable=self.start_s,
            command=lambda _v: self._cb.on_navigate(),
        )
        self._scale.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

        btns = tk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew")
        tk.Button(btns, text="<< Anterior", command=lambda: self._step(-1)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        tk.Button(btns, text="Siguiente >>", command=lambda: self._step(1)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2
        )
        frm.columnconfigure(1, weight=1)
        self._duration = 0.0

    def _build_export(self) -> None:
        tk.Button(self, text="Exportar con angulo y velocidad...", command=self._cb.on_export).pack(
            fill=tk.X, pady=(8, 2)
        )

    def _build_progress(self) -> None:
        self._progress = ttk.Progressbar(self, mode="determinate", maximum=1.0)
        self._progress.pack(fill=tk.X, pady=(4, 0))
        self._status = tk.Label(self, text="", fg="#444", anchor="w")
        self._status.pack(fill=tk.X)

    # ── navegación interna ───────────────────────────────────────
    def _on_window_len(self) -> None:
        self._refresh_scale_range()
        self._cb.on_navigate()

    def _step(self, direction: int) -> None:
        length = self.get_window_len_s()
        new = self.start_s.get() + direction * length
        new = max(0.0, min(new, max(0.0, self._duration - length)))
        self.start_s.set(new)
        self._cb.on_navigate()

    def _refresh_scale_range(self) -> None:
        length = self.get_window_len_s()
        upper = max(0.0, self._duration - length)
        self._scale.config(to=upper if upper > 0 else 0.0001)

    # ── API pública para el controlador ──────────────────────────
    def enable(self, on: bool) -> None:
        state = tk.NORMAL if on else tk.DISABLED
        for w in self._iter_interactive():
            try:
                w.config(state=state)
            except tk.TclError:
                pass

    def _iter_interactive(self):
        for child in self.winfo_children():
            for w in (child, *child.winfo_children()):
                if w is self._open_btn:
                    continue  # el botón de abrir nunca se deshabilita
                if isinstance(w, (ttk.Combobox, ttk.Spinbox, ttk.Scale, tk.Listbox, tk.Button,
                                  ttk.Checkbutton)):
                    yield w

    def set_file_label(self, text: str) -> None:
        self._file_lbl.config(text=text)

    def set_progress(self, frac: float) -> None:
        self._progress["value"] = max(0.0, min(1.0, frac))

    def set_status(self, text: str) -> None:
        self._status.config(text=text)

    def set_electrodes(self, names: list[str]) -> None:
        # El listbox puede estar deshabilitado (estado "ocupado"); se habilita
        # para poblarlo y preseleccionar, si no la inserción/selección se ignora.
        self._listbox.config(state=tk.NORMAL)
        self._listbox.delete(0, tk.END)
        for name in names:
            self._listbox.insert(tk.END, name)
        for i in range(min(3, len(names))):
            self._listbox.selection_set(i)

    def configure_duration(self, duration_s: float) -> None:
        self._duration = duration_s
        self.start_s.set(0.0)
        self._refresh_scale_range()

    # getters -----------------------------------------------------
    def get_angle_unit(self) -> AngleUnit:
        return AngleUnit(self.angle_unit.get())

    def get_vel_unit(self) -> VelocityUnit:
        return VelocityUnit(self.vel_unit.get())

    def get_window_ms(self) -> float:
        return _to_float(self.window_ms.get(), 50.0)

    def get_wrap(self) -> bool:
        return bool(self.wrap.get())

    def get_selected_electrodes(self) -> list[str]:
        return [self._listbox.get(i) for i in self._listbox.curselection()]

    def get_window_len_s(self) -> float:
        return max(0.001, _to_float(self.window_len.get(), 5.0))

    def get_start_s(self) -> float:
        return max(0.0, float(self.start_s.get()))


def _to_float(text: str, default: float) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default
