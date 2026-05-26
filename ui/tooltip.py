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
        # Use a raised/inverted surface so the tip clearly floats above
        # whatever it sits next to.  In dark mode the parent is already
        # dark, so using C["bg"] alone made the tip nearly invisible.
        self._tip.configure(background=C["border"])
        tk.Label(
            self._tip,
            text=self.text,
            background=C["bg_raised"],
            foreground=C["fg"],
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 9),
            padx=9,
            pady=5,
        ).pack(padx=1, pady=1)

    def _hide(self):
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class TreeHeadingTooltip:
    """Tooltip that follows the cursor over Treeview column headings.

    Treeview headings aren't real Tk widgets so the normal Tooltip class
    can't bind to them.  This helper watches the cursor on the parent
    Treeview and, when the user pauses over a heading, shows a tooltip
    whose text is pulled from a column → text map.
    """

    DELAY = 500

    def __init__(self, tree, texts: dict):
        self.tree = tree
        self.texts = dict(texts or {})
        self._tip = None
        self._job = None
        self._current_column = None
        tree.bind("<Motion>", self._on_motion, add="+")
        tree.bind("<Leave>",  self._on_leave,  add="+")
        tree.bind("<Button>", self._on_leave,  add="+")

    def set_texts(self, texts: dict):
        self.texts = dict(texts or {})

    def _on_motion(self, event):
        try:
            region = self.tree.identify("region", event.x, event.y)
        except tk.TclError:
            return
        if region != "heading":
            self._cancel()
            return
        col_id = self.tree.identify_column(event.x)
        try:
            col_index = int(col_id.lstrip("#")) - 1
            cols = list(self.tree["columns"])
            col_name = cols[col_index] if 0 <= col_index < len(cols) else None
        except (ValueError, IndexError, tk.TclError):
            col_name = None
        if col_name == self._current_column and self._tip:
            return
        self._cancel()
        self._current_column = col_name
        text = self.texts.get(col_name) if col_name else None
        if not text:
            return
        x = self.tree.winfo_rootx() + event.x + 12
        y = self.tree.winfo_rooty() + event.y + 18
        self._job = self.tree.after(self.DELAY,
                                    lambda x=x, y=y, t=text: self._show(x, y, t))

    def _on_leave(self, _event=None):
        self._cancel()

    def _cancel(self):
        if self._job:
            try:
                self.tree.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None
        self._current_column = None

    def _show(self, x, y, text):
        if self._tip:
            return
        self._tip = tk.Toplevel(self.tree)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.configure(background=C["border"])
        tk.Label(
            self._tip,
            text=text,
            background=C["bg_raised"],
            foreground=C["fg"],
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 9),
            padx=9,
            pady=5,
        ).pack(padx=1, pady=1)
