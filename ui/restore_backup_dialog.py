# ui/restore_backup_dialog.py
"""
Modal dialog letting the user restore a previous backup of a dictionary.

Layout:
- Brief description of which dictionary is being restored
- A list of available backups (newest first), each showing timestamp,
  rough size, and whether a matching metadata sidecar is available
- Restore / Cancel buttons

The actual file replacement happens in the caller (main.py) via the
selected_backup attribute - the dialog itself only collects the choice,
following the same pattern as save_changes_dialog.py.
"""
import os
import json
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from ui.theme import C
from logic.backup_store import list_backups


class RestoreBackupDialog(tk.Toplevel):
    """
    Open the dialog modally.  After wait_window() returns, check
    `selected_backup`: it's the chosen backup dict (see logic.backup_store
    for shape) when the user clicked Restore, or None for Cancel / close.
    """

    def __init__(self, parent, dict_path: str):
        super().__init__(parent)
        self.title("Restore Backup")
        self.configure(bg=C["bg_panel"])
        self.transient(parent)
        self.grab_set()

        self.dict_path        = dict_path
        self.dict_basename    = os.path.basename(dict_path) if dict_path else ""
        self.backups          = list_backups(dict_path) if dict_path else []
        self.selected_backup  = None   # filled in on Restore

        self._build()
        self._position(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())

    # ------------------------------------------------------------------
    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        # Heading
        ttk.Label(
            outer,
            text=f"Restore a previous version of {self.dict_basename}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        if not self.backups:
            ttk.Label(
                outer,
                text="No backups available for this dictionary yet. Backups "
                     "are created automatically when a dictionary is opened "
                     "and before every save.",
                wraplength=460,
                foreground=C["fg_dim"],
            ).pack(anchor="w", pady=(2, 12))

            btn_row = ttk.Frame(outer)
            btn_row.pack(fill=tk.X, pady=(8, 0))
            ttk.Button(btn_row, text="Close",
                       command=self._on_cancel).pack(side=tk.RIGHT)
            return

        ttk.Label(
            outer,
            text="Select a backup to restore. The dictionary file will be "
                 "replaced and the tab reloaded. Your current state will "
                 "itself be backed up first, so this is reversible.",
            wraplength=460,
            foreground=C["fg_dim"],
        ).pack(anchor="w", pady=(2, 10))

        # Backup list as a Treeview
        list_frame = ttk.Frame(outer)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        columns = ("when", "entries", "metadata")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings",
            selectmode="browse", height=min(12, len(self.backups)),
        )
        self.tree.heading("when",     text="When")
        self.tree.heading("entries",  text="Entries")
        self.tree.heading("metadata", text="Metadata")
        self.tree.column("when",     width=240, anchor="w",  stretch=True)
        self.tree.column("entries",  width=70,  anchor="e",  stretch=False)
        self.tree.column("metadata", width=90,  anchor="center", stretch=False)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Populate
        for idx, backup in enumerate(self.backups):
            kind_label = {"open": "Opened", "save": "Saved", "legacy": "Saved"}.get(
                backup.get("kind", "legacy"), "Saved"
            )
            self.tree.insert(
                "", "end",
                iid=str(idx),
                values=(
                    f"[{kind_label}]  {_format_when(backup['timestamp'], backup['mtime'])}",
                    _count_entries(backup["dict_path"]),
                    "✓" if backup["metadata_path"] else "—",
                ),
            )

        # Auto-select the newest
        self.tree.selection_set("0")
        self.tree.focus("0")

        # Double-click = restore
        self.tree.bind("<Double-1>", lambda e: self._on_restore())
        self.tree.bind("<Return>",   lambda e: self._on_restore())

        # Buttons
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="Cancel",
                   command=self._on_cancel).pack(side=tk.LEFT)
        restore_btn = ttk.Button(btn_row, text="Restore Selected",
                                 command=self._on_restore)
        restore_btn.pack(side=tk.RIGHT)
        restore_btn.focus_set()

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
    def _on_restore(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self.selected_backup = self.backups[idx]
        self.destroy()

    def _on_cancel(self):
        self.selected_backup = None
        self.destroy()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_when(timestamp: str, mtime: float) -> str:
    """
    Turn the filename timestamp '2026-04-30_14-32-08-241' into something
    a person can read at a glance, and append a relative hint.
    """
    # The timestamp is for display - parsing the raw string is robust to
    # filesystem mtime drift (e.g. if files are copied between machines).
    try:
        # Drop millis if present, parse the rest
        base = timestamp[:19]   # YYYY-MM-DD_HH-MM-SS
        dt = datetime.strptime(base, "%Y-%m-%d_%H-%M-%S")
        when = dt.strftime("%a %d %b %Y, %H:%M:%S")
    except ValueError:
        when = timestamp

    # Relative hint based on actual file mtime
    try:
        delta = datetime.now() - datetime.fromtimestamp(mtime)
        secs = int(delta.total_seconds())
        if secs < 60:
            rel = "just now"
        elif secs < 3600:
            rel = f"{secs // 60}m ago"
        elif secs < 86400:
            rel = f"{secs // 3600}h ago"
        elif secs < 86400 * 7:
            rel = f"{secs // 86400}d ago"
        else:
            rel = ""
    except (OSError, OverflowError, ValueError):
        rel = ""

    return f"{when}   ({rel})" if rel else when


def _count_entries(backup_path: str) -> str:
    """Cheap entry count, '?' on any failure.

    Uses object_pairs_hook so duplicate steno keys are counted individually
    rather than being silently collapsed by the standard JSON parser.
    """
    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            pairs = json.loads(f.read(), object_pairs_hook=lambda p: p)
        if isinstance(pairs, list):
            return str(len(pairs))
    except (OSError, ValueError):
        pass
    return "?"
