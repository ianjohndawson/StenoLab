# ui/tooltip.py
import tkinter as tk
from ui.theme import C


class Tooltip:
    """Hover tooltip for any Tk widget.  Appears after a short delay."""

    DELAY = 500   # ms before the tip appears

    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self._tip   = None
        self._job   = None
        widget.bind("<Enter>",  self._schedule, add="+")
        widget.bind("<Leave>",  self._cancel,   add="+")
        widget.bind("<Button>", self._cancel,   add="+")

    def update_text(self, text):
        self.text = text

    # ------------------------------------------------------------------
    def _schedule(self, event=None):
        self._cancel()
        self._job = self.widget.after(self.DELAY, self._show)

    def _cancel(self, event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        if self._tip:
            return
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        # Read C at show-time so tooltips always match the current theme,
        # even though Tooltip instances are long-lived.
        tk.Label(
            self._tip,
            text=self.text,
            background=C["bg"],
            foreground=C["fg"],
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=7,
            pady=4,
        ).pack()

    def _hide(self):
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None
