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

from ui.theme import C

STENO_METHODS = ["Contains", "Begins With", "Ends With"]
TEXT_METHODS = ["Contains", "Begins With", "Ends With"]

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
        # Columns: [label][method-combo][gap][query-entry (expands)][option-check]
        for col, weight in [(0, 0), (1, 0), (2, 0), (3, 1), (4, 0)]:
            self.columnconfigure(col, weight=weight)

        pad_y = 4
        label_pad = (10, 8)

        ttk.Label(self, text="Text:").grid(
            row=0, column=0, sticky="w", padx=label_pad, pady=pad_y,
        )
        self.text_method_box = ttk.Combobox(
            self, textvariable=self.text_method_var,
            values=TEXT_METHODS, state="readonly", width=12,
        )
        self.text_method_box.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=pad_y)
        self.text_entry = ttk.Entry(self, textvariable=self.text_query_var)
        self.text_entry.grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=pad_y)
        self.match_case_check = ttk.Checkbutton(
            self, text="Match case", variable=self.text_match_case_var,
        )
        self.match_case_check.grid(row=0, column=4, sticky="w", padx=(0, 10), pady=pad_y)

        ttk.Label(self, text="Steno:").grid(
            row=1, column=0, sticky="w", padx=label_pad, pady=pad_y,
        )
        self.steno_method_box = ttk.Combobox(
            self, textvariable=self.steno_method_var,
            values=STENO_METHODS, state="readonly", width=12,
        )
        self.steno_method_box.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=pad_y)
        self.steno_entry = ttk.Entry(self, textvariable=self.steno_query_var)
        self.steno_entry.grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=pad_y)
        self.whole_strokes_check = ttk.Checkbutton(
            self, text="Whole strokes only", variable=self.steno_whole_strokes_var,
        )
        self.whole_strokes_check.grid(row=1, column=4, sticky="w", padx=(0, 10), pady=pad_y)

        ttk.Label(self, text="Scope:").grid(
            row=2, column=0, sticky="w", padx=label_pad, pady=(pad_y, 8),
        )
        self.scope_box = ttk.Combobox(
            self,
            textvariable=self.scope_var,
            values=["Current Dictionary", "All Dictionaries"],
            state="readonly",
            width=20,
        )
        self.scope_box.grid(row=2, column=1, columnspan=2, sticky="w",
                            padx=(0, 8), pady=(pad_y, 8))
        ttk.Button(
            self, text="Clear", style="Secondary.TButton",
            command=self.clear,
        ).grid(row=2, column=4, sticky="e", padx=(0, 10), pady=(pad_y, 8))

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
