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
        row.pack(fill="x", padx=12, pady=7)

        self.meta_label = ttk.Label(row, style="StatusBar.TLabel", anchor="w")
        self.meta_label.pack(side="left", fill="x", expand=True)

        self.unsaved_chip = ttk.Label(row, style="HeaderChip.TLabel")
        self.unsaved_chip.pack(side="right", padx=(8, 0))

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
            f"{self.entry_count:,} entries   |   "
            f"{self.dict_count} open   |   "
            f"Active: {self.active_dict or '-'}   |   "
            f"Saved: {self.last_saved}"
        )
        self.meta_label.configure(text=text)
        if self.unsaved_count:
            self.unsaved_chip.configure(
                text=f"{self.unsaved_count} unsaved",
                style="HeaderWarning.TLabel",
            )
        else:
            self.unsaved_chip.configure(text="All saved", style="HeaderSuccess.TLabel")
        self.save_all_btn.configure(state="normal" if self.unsaved_count > 0 else "disabled")

    def _save_all(self):
        if callable(self._on_save_all):
            self._on_save_all()
