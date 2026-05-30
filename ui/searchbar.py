# ui/searchbar.py
"""Two-axis search inputs.

Owns just the text+steno+scope inputs and the search config plumbing.
It does NOT own a disclosure / collapse header any more — the unified
``Search & Filters`` bar in ``dictionary_tab.py`` is responsible for
collapsing the whole panel.  This keeps the two-row layout from feeling
like two separate tools stacked on top of each other.
"""
import tkinter as tk
from tkinter import ttk

STENO_METHODS = ["Contains", "Begins With", "Ends With"]
TEXT_METHODS = ["Contains", "Begins With", "Ends With"]

# Shared combobox width so method and scope dropdowns line up and the
# query fields start at the same horizontal position on every row.
COMBO_WIDTH = 17

# Grid columns: label | method/scope | query (expands) | trailing option
_COL_LABEL = 0
_COL_METHOD = 1
_COL_ENTRY = 2
_COL_OPTION = 3

# Milliseconds to wait after the last keystroke before triggering a
# filter pass.  Filtering 100k+ entries per keystroke is wasteful; this
# coalesces rapid typing into a single update.  Combobox / checkbox
# changes bypass the debounce so they react immediately.
DEBOUNCE_MS = 160


class SearchBar(ttk.Frame):
    def __init__(self, parent, on_search=None):
        super().__init__(parent)

        self.on_search = on_search

        self.steno_query_var = tk.StringVar()
        self.steno_method_var = tk.StringVar(value="Contains")
        self.steno_whole_strokes_var = tk.BooleanVar(value=False)
        self.text_query_var = tk.StringVar()
        self.text_method_var = tk.StringVar(value="Begins With")
        self.text_match_case_var = tk.BooleanVar(value=False)
        self.scope_var = tk.StringVar(value="Current Dictionary")

        self._steno_upcasing = False
        self._suppress_change = False
        self._debounce_job = None

        self._build()
        self._bind_events()

    # ------------------------------------------------------------------
    def _build(self):
        self.columnconfigure(_COL_ENTRY, weight=1)
        self.columnconfigure(_COL_LABEL, minsize=54)
        self.columnconfigure(_COL_METHOD, minsize=136)
        self.columnconfigure(_COL_OPTION, minsize=148)

        row_pad = (4, 4)
        label_pad = (10, 8)
        inner_pad = (0, 8)

        ttk.Label(self, text="Text:").grid(
            row=0, column=_COL_LABEL, sticky="e",
            padx=label_pad, pady=row_pad,
        )
        self.text_method_box = ttk.Combobox(
            self, textvariable=self.text_method_var,
            values=TEXT_METHODS, state="readonly", width=COMBO_WIDTH,
        )
        self.text_method_box.grid(
            row=0, column=_COL_METHOD, sticky="w",
            padx=inner_pad, pady=row_pad,
        )
        self.text_entry = ttk.Entry(self, textvariable=self.text_query_var)
        self.text_entry.grid(
            row=0, column=_COL_ENTRY, sticky="ew",
            padx=(0, 8), pady=row_pad,
        )
        self.match_case_check = ttk.Checkbutton(
            self, text="Match case", variable=self.text_match_case_var,
            style="UnifiedBar.TCheckbutton",
        )
        self.match_case_check.grid(
            row=0, column=_COL_OPTION, sticky="w",
            padx=(0, 10), pady=row_pad,
        )

        ttk.Label(self, text="Steno:").grid(
            row=1, column=_COL_LABEL, sticky="e",
            padx=label_pad, pady=row_pad,
        )
        self.steno_method_box = ttk.Combobox(
            self, textvariable=self.steno_method_var,
            values=STENO_METHODS, state="readonly", width=COMBO_WIDTH,
        )
        self.steno_method_box.grid(
            row=1, column=_COL_METHOD, sticky="w",
            padx=inner_pad, pady=row_pad,
        )
        self.steno_entry = ttk.Entry(self, textvariable=self.steno_query_var)
        self.steno_entry.grid(
            row=1, column=_COL_ENTRY, sticky="ew",
            padx=(0, 8), pady=row_pad,
        )
        self.whole_strokes_check = ttk.Checkbutton(
            self, text="Whole strokes only", variable=self.steno_whole_strokes_var,
            style="UnifiedBar.TCheckbutton",
        )
        self.whole_strokes_check.grid(
            row=1, column=_COL_OPTION, sticky="w",
            padx=(0, 10), pady=row_pad,
        )

        ttk.Label(self, text="Scope:").grid(
            row=2, column=_COL_LABEL, sticky="e",
            padx=label_pad, pady=(row_pad[0], 8),
        )
        self.scope_box = ttk.Combobox(
            self,
            textvariable=self.scope_var,
            values=["Current Dictionary", "All Dictionaries"],
            state="readonly",
            width=COMBO_WIDTH,
        )
        self.scope_box.grid(
            row=2, column=_COL_METHOD, sticky="w",
            padx=inner_pad, pady=(row_pad[0], 8),
        )
        ttk.Button(
            self, text="Clear", style="Compact.TButton",
            command=self.clear,
        ).grid(
            row=2, column=_COL_OPTION, sticky="e",
            padx=(0, 10), pady=(row_pad[0], 8),
        )

    # ------------------------------------------------------------------
    def _bind_events(self):
        # Text + Steno query vars debounce; everything else fires immediately.
        self.steno_query_var.trace_add(
            "write", lambda *_: self._schedule_change(debounce=True),
        )
        self.text_query_var.trace_add(
            "write", lambda *_: self._schedule_change(debounce=True),
        )
        for var in (
            self.steno_method_var,
            self.text_method_var,
            self.steno_whole_strokes_var,
            self.text_match_case_var,
            self.scope_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_change(debounce=False))

        # Auto-uppercase the steno input as the user types.
        def upcase(*_):
            if self._steno_upcasing:
                return
            current = self.steno_query_var.get()
            upper = current.upper()
            if upper != current:
                self._steno_upcasing = True
                try:
                    self.steno_query_var.set(upper)
                finally:
                    self._steno_upcasing = False

        self.steno_query_var.trace_add("write", upcase)

    def _schedule_change(self, *, debounce: bool):
        """Trigger a search; coalesces rapid keystrokes into one filter pass."""
        if self._suppress_change:
            return
        if self._debounce_job is not None:
            try:
                self.after_cancel(self._debounce_job)
            except tk.TclError:
                pass
            self._debounce_job = None
        if debounce:
            self._debounce_job = self.after(DEBOUNCE_MS, self._fire_change)
        else:
            self._fire_change()

    def _fire_change(self):
        self._debounce_job = None
        if callable(self.on_search):
            self.on_search(self.get_config())

    def flush_pending(self):
        """Force any debounced change to apply immediately.  Used when the
        unified bar is collapsing or focus is leaving the inputs."""
        if self._debounce_job is not None:
            try:
                self.after_cancel(self._debounce_job)
            except tk.TclError:
                pass
            self._debounce_job = None
            self._fire_change()

    # ------------------------------------------------------------------
    def focus_text_entry(self, append_char=None):
        self.text_entry.focus_set()
        if append_char:
            self.text_entry.insert(tk.END, append_char)
        self.text_entry.icursor(tk.END)

    def focus_steno_entry(self, append_char=None):
        self.steno_entry.focus_set()
        if append_char:
            self.steno_entry.insert(tk.END, append_char)
        self.steno_entry.icursor(tk.END)

    def clear(self):
        self.steno_query_var.set("")
        self.text_query_var.set("")

    def set_scope(self, scope: str):
        if scope in ("Current Dictionary", "All Dictionaries"):
            self.scope_var.set(scope)

    def set_config_quietly(self, config: dict):
        """Mirror an external search config without re-emitting on_search."""
        if not isinstance(config, dict):
            return
        self._suppress_change = True
        try:
            self.steno_query_var.set(config.get("steno_query", ""))
            self.steno_method_var.set(config.get("steno_method", "Contains"))
            self.steno_whole_strokes_var.set(bool(config.get("steno_whole_strokes", False)))
            self.text_query_var.set(config.get("text_query", ""))
            self.text_method_var.set(config.get("text_method", "Begins With"))
            self.text_match_case_var.set(bool(config.get("text_match_case", False)))
        finally:
            self._suppress_change = False

    def get_config(self) -> dict:
        return {
            "steno_query": self.steno_query_var.get().strip(),
            "steno_method": self.steno_method_var.get(),
            "steno_whole_strokes": self.steno_whole_strokes_var.get(),
            "text_query": self.text_query_var.get().strip(),
            "text_method": self.text_method_var.get(),
            "text_match_case": self.text_match_case_var.get(),
            "scope": self.scope_var.get(),
        }

    def chip_defs(self):
        """Active-search chip definitions for the unified header."""
        chips = []
        text_query = self.text_query_var.get().strip()
        steno_query = self.steno_query_var.get().strip()
        if text_query:
            chips.append((f'Text: "{text_query}"', lambda: self.text_query_var.set("")))
        if steno_query:
            chips.append((f'Steno: "{steno_query}"', lambda: self.steno_query_var.set("")))
        if self.scope_var.get() == "All Dictionaries":
            chips.append(("All dictionaries", lambda: self.scope_var.set("Current Dictionary")))
        if self.text_match_case_var.get():
            chips.append(("Match case", lambda: self.text_match_case_var.set(False)))
        if self.steno_whole_strokes_var.get():
            chips.append(("Whole strokes", lambda: self.steno_whole_strokes_var.set(False)))
        return chips
