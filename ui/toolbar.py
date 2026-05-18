# ui/toolbar.py
import tkinter as tk
from tkinter import ttk
from ui.tooltip import Tooltip


class Toolbar(ttk.Frame):
    """
    Icon toolbar.  Left side: action buttons.  Right side: undo/redo.
    Each button shows a Unicode symbol; a tooltip carries the full label
    and keyboard shortcut.
    """

    _LEFT_BUTTONS = [
        # (symbol,  callback-key,  tooltip text)
        ("⊞",  "open",      "Open Dictionary  (Ctrl+O)"),
        ("＋",  "add",       "Add Entry  (Ctrl+N)"),
        ("✎",  "edit",      "Edit Entry  (Ctrl+E)"),
        ("⌕",  "find",      "Find & Replace"),
        ("★",  "bookmarks", "Toggle Bookmark  (Ctrl+B)"),
    ]

    _RIGHT_BUTTONS = [
        # (symbol,  callback-key,  tooltip text,  attr-name)
        ("↺",  "undo",  "Undo  (Ctrl+Z)",         "_undo_btn"),
        ("↻",  "redo",  "Redo  (Ctrl+Y)",          "_redo_btn"),
    ]

    def __init__(self, parent, callbacks=None):
        super().__init__(parent)
        self.callbacks = callbacks or {}
        self._build()

    def _build(self):
        for symbol, key, tip in self._LEFT_BUTTONS:
            btn = ttk.Button(
                self,
                text=symbol,
                style="Icon.TButton",
                command=lambda k=key: self._trigger(k),
            )
            btn.pack(side=tk.LEFT, padx=3, pady=4)
            Tooltip(btn, tip)

        for symbol, key, tip, attr in self._RIGHT_BUTTONS:
            btn = ttk.Button(
                self,
                text=symbol,
                style="Icon.TButton",
                command=lambda k=key: self._trigger(k),
                state="disabled",
            )
            btn.pack(side=tk.RIGHT, padx=3, pady=4)
            Tooltip(btn, tip)
            setattr(self, attr, btn)

    def _trigger(self, key):
        if key in self.callbacks and callable(self.callbacks[key]):
            self.callbacks[key]()

    def refresh_undo_redo(self, can_undo: bool, can_redo: bool) -> None:
        """Enable or disable the undo/redo buttons to reflect stack state."""
        self._undo_btn.configure(state="normal" if can_undo else "disabled")
        self._redo_btn.configure(state="normal" if can_redo else "disabled")
