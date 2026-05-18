# ui/save_changes_dialog.py
"""
Modal dialog asking the user how to handle unsaved dictionary changes.

Used in two contexts:
- Closing a single tab when that tab has unsaved JSON changes.
- Closing the application when one or more open tabs are dirty.

The dialog is built around the same component for both: when there is one
dirty file the checkboxes are omitted; when there are several, each appears
as a checkbox so the user can pick which to save.
"""
import os
import tkinter as tk
from tkinter import ttk

from ui.theme import C


# Result codes
RESULT_SAVE    = "save"
RESULT_DISCARD = "discard"
RESULT_CANCEL  = "cancel"


def ask_save_changes(parent, dirty_paths, *, context: str = "exit"):
    """
    Open the dialog modally.

    Args:
        parent: window to anchor against.
        dirty_paths: list of file paths with unsaved JSON changes.
        context: 'exit' (closing the whole app) or 'close' (closing one tab).

    Returns:
        (result, paths_to_save) where:
            result is RESULT_SAVE / RESULT_DISCARD / RESULT_CANCEL
            paths_to_save is the subset the user wants saved.  Always [] for
            DISCARD or CANCEL; equal to the dirty paths the user ticked for
            SAVE.
    """
    if not dirty_paths:
        # Nothing to ask about
        return RESULT_DISCARD, []

    dlg = SaveChangesDialog(parent, dirty_paths, context=context)
    dlg.wait_window()
    return dlg.result, dlg.paths_to_save


class SaveChangesDialog(tk.Toplevel):
    def __init__(self, parent, dirty_paths, *, context):
        super().__init__(parent)
        self.title("Unsaved Changes")
        self.resizable(False, False)
        self.configure(bg=C["bg_panel"])
        self.transient(parent)
        self.grab_set()

        self.dirty_paths    = list(dirty_paths)
        self.context        = context
        self.result         = RESULT_CANCEL
        self.paths_to_save  = []

        # Per-path tk.BooleanVar, all ticked by default
        self._vars = {p: tk.BooleanVar(value=True) for p in self.dirty_paths}

        self._build()
        self._position(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.bind("<Return>", lambda e: self._on_save())

    # ------------------------------------------------------------------
    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        n = len(self.dirty_paths)
        verb = "exit" if self.context == "exit" else "close"

        if n == 1:
            heading = "Save changes before closing?"
            body    = (f"\"{os.path.basename(self.dirty_paths[0])}\" has "
                       f"unsaved changes.")
        else:
            heading = f"Save changes to {n} dictionaries before {verb}?"
            body    = ("These dictionaries have unsaved changes. Tick the "
                       "ones you want to save:")

        ttk.Label(outer, text=heading,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(outer, text=body, wraplength=420).pack(
            anchor="w", pady=(0, 10))

        # File list (only when 2+ dirty files)
        if n > 1:
            list_frame = ttk.Frame(outer)
            list_frame.pack(fill=tk.X, pady=(0, 8))
            for path in self.dirty_paths:
                cb = ttk.Checkbutton(
                    list_frame,
                    text=os.path.basename(path),
                    variable=self._vars[path],
                )
                cb.pack(anchor="w", pady=2)

        # Buttons
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        # Order: Cancel (left) | Discard | Save (right, default)
        ttk.Button(btn_row, text="Cancel",
                   command=self._on_cancel).pack(side=tk.LEFT)
        ttk.Button(btn_row, text=("Discard & " + verb.capitalize()),
                   command=self._on_discard).pack(side=tk.RIGHT, padx=(6, 0))
        save_btn = ttk.Button(btn_row, text=("Save & " + verb.capitalize()),
                              command=self._on_save)
        save_btn.pack(side=tk.RIGHT)
        save_btn.focus_set()

    def _position(self, parent):
        self.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            dw, dh = self.winfo_width(),   self.winfo_height()
            self.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _on_save(self):
        self.paths_to_save = [p for p, v in self._vars.items() if v.get()]
        self.result = RESULT_SAVE
        self.destroy()

    def _on_discard(self):
        self.paths_to_save = []
        self.result = RESULT_DISCARD
        self.destroy()

    def _on_cancel(self):
        self.paths_to_save = []
        self.result = RESULT_CANCEL
        self.destroy()
