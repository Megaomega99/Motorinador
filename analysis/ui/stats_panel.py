"""Panel de estadísticos: velocidad de sesión/ventana, motor y engranajes."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..gearing import GearEstimate
from ..stats import MotorSummary, VelocityStats


class StatsPanel(tk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        tk.Label(self, text="Velocidad angular media (sesión)", font=("", 10, "bold")).pack(
            anchor="w", pady=(4, 0)
        )
        self._session_lbl = tk.Label(self, text="—", font=("", 14), fg="#1a5")
        self._session_lbl.pack(anchor="w")

        tk.Label(self, text="Motor · consigna vs medido (ventana)",
                 font=("", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self._motor_lbl = tk.Label(self, text="—", font=("", 12), fg="#176")
        self._motor_lbl.pack(anchor="w")

        self._session_tree = self._make_table("Estadísticos de la sesión")
        self._window_tree = self._make_table("Estadísticos de la ventana visible")
        self._gear_tree = self._make_table("Transmisión medida", height=6)

    def _make_table(self, title: str, height: int = 7) -> ttk.Treeview:
        tk.Label(self, text=title, font=("", 10, "bold")).pack(anchor="w", pady=(10, 0))
        tree = ttk.Treeview(self, columns=("val",), show="tree", height=height)
        tree.column("#0", width=170, anchor="w")
        tree.column("val", width=140, anchor="e")
        tree.pack(fill=tk.X)
        return tree

    @staticmethod
    def _fill(tree: ttk.Treeview, rows: list[tuple[str, str]]) -> None:
        tree.delete(*tree.get_children())
        for label, value in rows:
            tree.insert("", "end", text=label, values=(value,))

    def update_session(self, stats: VelocityStats) -> None:
        self._session_lbl.config(text=f"{stats.mean:.3f} {stats.unit}")
        self._fill(self._session_tree, stats.as_rows())

    def update_window(self, stats: VelocityStats) -> None:
        self._fill(self._window_tree, stats.as_rows())

    def update_motor(self, summary: MotorSummary | None) -> None:
        """Resumen del motor en la ventana visible (None = grabación sin la señal).

        Se resalta en rojo si el deslizamiento pasa del 10 %: eso significa que el
        motor no está siguiendo la consigna (pasos perdidos o atasco).
        """
        if summary is None:
            self._motor_lbl.config(text="sin señal de motor", fg="#888")
            return
        self._motor_lbl.config(
            text=summary.as_text(),
            fg="#a33" if (summary.slip_pct or 0.0) > 10.0 else "#176",
        )

    def update_gearing(self, est: GearEstimate | None) -> None:
        self._fill(self._gear_tree, est.as_rows() if est else [])

    def reset(self) -> None:
        self._session_lbl.config(text="—")
        self._motor_lbl.config(text="—", fg="#176")
        for tree in (self._session_tree, self._window_tree, self._gear_tree):
            tree.delete(*tree.get_children())
