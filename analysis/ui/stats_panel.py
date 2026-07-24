"""Panel de estadísticos: velocidad media de sesión, tabla y media de ventana."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..stats import VelocityStats


class StatsPanel(tk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        tk.Label(self, text="Velocidad angular media (sesión)", font=("", 10, "bold")).pack(
            anchor="w", pady=(4, 0)
        )
        self._session_lbl = tk.Label(self, text="—", font=("", 14), fg="#1a5")
        self._session_lbl.pack(anchor="w")

        self._session_tree = self._make_table("Estadísticos de la sesión")
        self._window_tree = self._make_table("Estadísticos de la ventana visible")

    def _make_table(self, title: str) -> ttk.Treeview:
        tk.Label(self, text=title, font=("", 10, "bold")).pack(anchor="w", pady=(10, 0))
        tree = ttk.Treeview(self, columns=("val",), show="tree", height=7)
        tree.column("#0", width=170, anchor="w")
        tree.column("val", width=140, anchor="e")
        tree.pack(fill=tk.X)
        return tree

    @staticmethod
    def _fill(tree: ttk.Treeview, stats: VelocityStats) -> None:
        tree.delete(*tree.get_children())
        for label, value in stats.as_rows():
            tree.insert("", "end", text=label, values=(value,))

    def update_session(self, stats: VelocityStats) -> None:
        self._session_lbl.config(text=f"{stats.mean:.3f} {stats.unit}")
        self._fill(self._session_tree, stats)

    def update_window(self, stats: VelocityStats) -> None:
        self._fill(self._window_tree, stats)

    def reset(self) -> None:
        self._session_lbl.config(text="—")
        self._session_tree.delete(*self._session_tree.get_children())
        self._window_tree.delete(*self._window_tree.get_children())
