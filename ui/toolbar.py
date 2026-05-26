# ui/toolbar.py
"""
Top toolbar.

All buttons are the same: square icon-only buttons with a clear hover
background, grouped left-to-right and separated by a thin vertical rule.
Tooltips supply the full label + keyboard shortcut so the toolbar stays
compact even on small windows.

Layout:

    [📂] [💾]   |   [+] [✎] [⌕] [★]   …spacer…   [↶] [↷]
     open save     add edit find bm                 undo redo
"""
import tkinter as tk
from tkinter import ttk

from ui.tooltip import Tooltip


# (icon, callback_key, tooltip, [optional attr_name to expose on toolbar])
_FILE_GROUP = [
    ("📂", "open", "Open Dictionary  (Ctrl+O)", None),
    ("💾", "save", "Save Dictionary  (Ctrl+S)", "_save_btn"),
]
_ACTION_GROUP = [
    ("＋", "add",       "Add Entry  (Ctrl+N)",        None),
    ("✎",  "edit",      "Edit Entry  (Ctrl+E)",       None),
    ("⌕",  "find",      "Find & Replace  (Ctrl+F)",   None),
    ("★",  "bookmarks", "Toggle Bookmark  (Ctrl+B)",  None),
]
_HISTORY_GROUP = [
    ("↶", "undo", "Undo  (Ctrl+Z)", "_undo_btn"),
    ("↷", "redo", "Redo  (Ctrl+Y)", "_redo_btn"),
]


class Toolbar(ttk.Frame):
    def __init__(self, parent, callbacks=None):
        super().__init__(parent, style="Toolbar.TFrame", padding=(8, 6))
        self.callbacks = callbacks or {}
        self._build()

    def _build(self):
        self._add_group(_FILE_GROUP, side=tk.LEFT, first=True)
        self._add_separator(side=tk.LEFT)
        self._add_group(_ACTION_GROUP, side=tk.LEFT)

        # History pinned to the right
        self._add_group(_HISTORY_GROUP, side=tk.RIGHT, first=True)

    def _add_group(self, definitions, *, side, first=False):
        group = ttk.Frame(self, style="ToolbarGroup.TFrame")
        group.pack(side=side, padx=(0 if first else 0, 0))
        for i, (icon, key, tip, attr) in enumerate(definitions):
            btn = ttk.Button(
                group,
                text=icon,
                style="ToolbarIcon.TButton",
                command=lambda k=key: self._trigger(k),
                takefocus=False,
            )
            btn.pack(side=tk.LEFT, padx=(0 if i == 0 else 2, 0))
            Tooltip(btn, tip)
            if attr:
                setattr(self, attr, btn)
                # Save / Undo / Redo all start disabled — main.py drives them.
                btn.configure(state="disabled")

    def _add_separator(self, *, side):
        sep = ttk.Frame(self, width=1, style="ToolbarSeparator.TFrame")
        sep.pack(side=side, padx=8, pady=4, fill=tk.Y)

    # ------------------------------------------------------------------
    def _trigger(self, key):
        fn = self.callbacks.get(key)
        if callable(fn):
            fn()

    def refresh_undo_redo(self, can_undo: bool, can_redo: bool) -> None:
        self._undo_btn.configure(state="normal" if can_undo else "disabled")
        self._redo_btn.configure(state="normal" if can_redo else "disabled")

    def set_save_enabled(self, enabled: bool) -> None:
        if hasattr(self, "_save_btn"):
            self._save_btn.configure(state="normal" if enabled else "disabled")
