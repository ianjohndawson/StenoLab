# ui/statusbar.py
from tkinter import ttk


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

    def _build(self):
        row = ttk.Frame(self, style="StatusBar.TFrame")
        row.pack(fill="x", padx=10, pady=6)

        self.meta_label = ttk.Label(row, style="StatusBar.TLabel", anchor="w")
        self.meta_label.pack(side="left", fill="x", expand=True)

        self.save_all_btn = ttk.Button(
            row,
            text="Save All",
            style="Primary.TButton",
            command=self._save_all,
        )
        self.save_all_btn.pack(side="right")

        self._render()

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
        text = (
            f"Entries {self.entry_count:,}   ·   "
            f"Open {self.dict_count}   ·   "
            f"Unsaved {self.unsaved_count}   ·   "
            f"Active {self.active_dict or '-'}   ·   "
            f"Saved {self.last_saved}"
        )
        self.meta_label.configure(text=text)
        self.save_all_btn.configure(state="normal" if self.unsaved_count > 0 else "disabled")

    def _save_all(self):
        if callable(self._on_save_all):
            self._on_save_all()
