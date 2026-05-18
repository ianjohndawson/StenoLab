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
        super().__init__(parent, style="Toolbar.TFrame", padding=(8, 6))
        self.callbacks = callbacks or {}
        self._build()

    def _build(self):
        left = ttk.Frame(self, style="ToolbarGroup.TFrame")
        left.pack(side=tk.LEFT)
        ttk.Label(left, text="DICTIONARY", style="ToolbarLabel.TLabel").pack(
            side=tk.LEFT, padx=(2, 8)
        )

        for i, (symbol, key, tip) in enumerate(self._LEFT_BUTTONS):
            style = "Primary.TButton" if key in {"open", "add"} else "Icon.TButton"
            btn = ttk.Button(
                left,
                text=symbol,
                style=style,
                command=lambda k=key: self._trigger(k),
            )
            btn.pack(side=tk.LEFT, padx=(0 if i == 0 else 4, 0), pady=1)
            Tooltip(btn, tip)

        right = ttk.Frame(self, style="ToolbarGroup.TFrame")
        right.pack(side=tk.RIGHT)
        ttk.Label(right, text="HISTORY", style="ToolbarLabel.TLabel").pack(
            side=tk.LEFT, padx=(0, 8)
        )
        for symbol, key, tip, attr in self._RIGHT_BUTTONS:
            btn = ttk.Button(
                right,
                text=symbol,
                style="Icon.TButton",
                command=lambda k=key: self._trigger(k),
                state="disabled",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4), pady=1)
            Tooltip(btn, tip)
            setattr(self, attr, btn)

    def _trigger(self, key):
        if key in self.callbacks and callable(self.callbacks[key]):
            self.callbacks[key]()

    def refresh_undo_redo(self, can_undo: bool, can_redo: bool) -> None:
        """Enable or disable the undo/redo buttons to reflect stack state."""
        self._undo_btn.configure(state="normal" if can_undo else "disabled")
        self._redo_btn.configure(state="normal" if can_redo else "disabled")
