# ui/display_limit_dialog.py
"""
Single-input dialog for the maximum number of dictionary rows shown in the
table at once.  Reachable via Tools → Set Display Limit.

Plain number input.  No hint, no warning - this is a hidden setting that
anyone changing it has already thought about.

Returns the new value via .new_value (None if Cancel).
"""
import tkinter as tk
from tkinter import ttk

from ui.theme import C


class DisplayLimitDialog(tk.Toplevel):
    def __init__(self, parent, current_value: int):
        super().__init__(parent)
        self.title("Display Limit")
        self.resizable(False, False)
        self.configure(bg=C["bg_panel"])
        self.transient(parent)
        self.grab_set()

        self.new_value = None

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Maximum rows displayed:").pack(
            anchor="w", pady=(0, 6))

        self._var = tk.StringVar(value=str(current_value))
        entry = ttk.Entry(outer, textvariable=self._var, width=12)
        entry.pack(anchor="w", pady=(0, 4))
        entry.select_range(0, tk.END)
        entry.focus_set()

        # Inline error slot - shown if the input is non-numeric or out of
        # range.  Empty by default.
        self._error_var = tk.StringVar(value="")
        ttk.Label(
            outer, textvariable=self._error_var,
            foreground=C["conflict_fg"], font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 8))

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="Cancel",
                   command=self._on_cancel).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="OK",
                   command=self._on_ok).pack(side=tk.RIGHT)

        self.bind("<Return>",  lambda e: self._on_ok())
        self.bind("<Escape>",  lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Centre on parent
        self.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            dw, dh = self.winfo_width(),   self.winfo_height()
            self.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        except tk.TclError:
            pass

    def _on_ok(self):
        raw = self._var.get().strip()
        try:
            n = int(raw)
        except ValueError:
            self._error_var.set("Enter a whole number.")
            return
        if n < 1:
            self._error_var.set("Must be at least 1.")
            return
        self.new_value = n
        self.destroy()

    def _on_cancel(self):
        self.new_value = None
        self.destroy()


def ask_display_limit(parent, current_value: int):
    """Open the dialog modally and return the chosen integer, or None."""
    dlg = DisplayLimitDialog(parent, current_value)
    dlg.wait_window()
    return dlg.new_value
