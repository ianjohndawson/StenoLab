# ui/statusbar.py
"""
Bottom status bar.

Layout (left → right):

    [📖 N entries] [🗂 N open] [● Active: name] [💾 Saved hh:mm]   …   [chip] [Save All]

Each segment is its own ``ttk.Label`` so we can give them subtle dividers
and let long values truncate naturally without stretching the row.  All
labels share the ``StatusBar.TLabel`` style so a theme switch reaches them
through the live palette.
"""
import tkinter as tk
from tkinter import ttk

from ui.theme import C


class StatusBar(ttk.Frame):
    """Bottom status bar with compact metrics and quick actions."""

    def __init__(self, parent, on_save_all=None):
        super().__init__(parent, style="StatusBar.TFrame")

        self.entry_count = 0
        self.dict_count = 0
        self.active_dict = ""
        self.last_saved = "-"
        self.unsaved_count = 0
        self._on_save_all = on_save_all

        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        # Thin top divider so the bar reads as a distinct surface.
        divider = ttk.Frame(self, style="StatusBarDivider.TFrame", height=1)
        divider.pack(fill="x", side="top")

        row = ttk.Frame(self, style="StatusBar.TFrame")
        row.pack(fill="x", padx=12, pady=4)

        # Metric segments
        self.entries_label = self._segment(row)
        self.dicts_label = self._segment(row, with_divider=True)
        self.active_label = self._segment(row, with_divider=True)
        self.saved_label = self._segment(row, with_divider=True)

        # Right side actions
        self.save_all_btn = ttk.Button(
            row,
            text="Save All",
            style="Compact.TButton",
            command=self._save_all,
        )

        self.unsaved_chip = ttk.Label(row, style="StatusBar.TLabel")
        self.unsaved_chip.pack(side="right")

        self._render()

    def _segment(self, parent, with_divider: bool = False) -> ttk.Label:
        if with_divider:
            ttk.Label(
                parent,
                text="·",
                style="StatusBarDivider.TLabel",
            ).pack(side="left", padx=8)
        label = ttk.Label(parent, style="StatusBar.TLabel", anchor="w")
        label.pack(side="left")
        return label

    # ------------------------------------------------------------------
    def update_status(self, *, entries=None, dictionaries=None, active=None,
                      saved=None, unsaved=None):
        if entries is not None:
            self.entry_count = entries
        if dictionaries is not None:
            self.dict_count = dictionaries
        if active is not None:
            self.active_dict = active
        if saved is not None:
            self.last_saved = saved
        if unsaved is not None:
            self.unsaved_count = unsaved

        self._render()

    def _render(self):
        entries = self.entry_count
        dicts = self.dict_count
        self.entries_label.configure(
            text=f"{entries:,} entr{'y' if entries == 1 else 'ies'}"
        )
        self.dicts_label.configure(text=f"{dicts} open")
        active = self.active_dict.strip() if self.active_dict else ""
        self.active_label.configure(text=f"Active: {active or '—'}")
        saved = (self.last_saved or "—").strip() or "—"
        self.saved_label.configure(text=f"Saved: {saved}")

        if self.unsaved_count:
            if self.unsaved_chip.winfo_ismapped():
                self.unsaved_chip.pack_forget()
            if self.save_all_btn.winfo_ismapped():
                self.save_all_btn.pack_forget()
            self.save_all_btn.pack(side="right")
            self.unsaved_chip.pack(side="right", padx=(0, 8))
            self.unsaved_chip.configure(
                text=f"{self.unsaved_count} unsaved",
                style="HeaderWarning.TLabel",
            )
            self.save_all_btn.configure(state="normal")
        else:
            if self.save_all_btn.winfo_ismapped():
                self.save_all_btn.pack_forget()
            if not self.unsaved_chip.winfo_ismapped():
                self.unsaved_chip.pack(side="right")
            self.unsaved_chip.configure(
                text="Saved",
                style="StatusBar.TLabel",
            )
            self.unsaved_chip.pack_configure(padx=(0, 0))
            self.save_all_btn.configure(state="disabled")

    def _save_all(self):
        if callable(self._on_save_all):
            self._on_save_all()

    # ------------------------------------------------------------------
    def refresh_theme(self):
        """Re-pull palette colours after a runtime theme switch."""
        try:
            for child in self.winfo_children():
                self._restyle_recursive(child)
        except tk.TclError:
            pass

    def _restyle_recursive(self, widget):
        try:
            widget.configure(background=C["bg"])
        except tk.TclError:
            pass
        try:
            for child in widget.winfo_children():
                self._restyle_recursive(child)
        except tk.TclError:
            pass
