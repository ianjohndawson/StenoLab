# ui/searchbar.py
"""Collapsible two-axis search panel with contextual actions."""
import tkinter as tk
from tkinter import ttk

from ui.theme import C

ANIMATION_DURATION = 180
ANIMATION_STEPS = 12

STENO_METHODS = ["Contains", "Begins With", "Ends With"]
TEXT_METHODS = ["Contains", "Begins With", "Ends With"]


class SearchBar(ttk.Frame):
    def __init__(self, parent, on_search=None, on_collapse_changed=None,
                 initially_collapsed=True):
        super().__init__(parent)

        self.on_search = on_search
        self.on_collapse_changed = on_collapse_changed

        self.steno_query_var = tk.StringVar()
        self.steno_method_var = tk.StringVar(value="Contains")
        self.steno_whole_strokes_var = tk.BooleanVar(value=False)
        self.text_query_var = tk.StringVar()
        self.text_method_var = tk.StringVar(value="Begins With")
        self.text_match_case_var = tk.BooleanVar(value=False)
        self.scope_var = tk.StringVar(value="Current Dictionary")

        self.expanded = not initially_collapsed
        self.content_height = 0
        self._count_suffix = ""
        self._no_match_actions = []
        self._steno_upcasing = False

        self._build()
        self._bind_events()

        if self.expanded:
            self.after_idle(self._open_immediately)
        else:
            self.after_idle(self.body.pack_forget)

    def _build(self):
        self.header = ttk.Frame(self)
        self.header.pack(fill=tk.X)
        self.header.bind("<Button-1>", self._toggle)

        arrow = "▼" if self.expanded else "▶"
        self.header_label = ttk.Label(self.header, text=f"{arrow} Search", padding=6)
        self.header_label.pack(side=tk.LEFT)
        self.header_label.bind("<Button-1>", self._toggle)

        self.active_search_frame = ttk.Frame(self.header)
        self.active_search_frame.pack(side=tk.LEFT, padx=(6, 0))

        self.active_hint = ttk.Label(
            self.header, text="", foreground=C["fg_dim"], padding=(0, 6)
        )
        self.active_hint.pack(side=tk.RIGHT, padx=12)
        self.active_hint.bind("<Button-1>", self._toggle)

        self.no_match_actions = ttk.Frame(self.header)
        self.no_match_actions.pack(side=tk.RIGHT, padx=(0, 8))
        self.no_match_actions.pack_forget()

        self.body = ttk.Frame(self)
        self.body.pack(fill=tk.X)

        for col, weight in [(0, 0), (1, 0), (2, 0), (3, 1), (4, 0)]:
            self.body.columnconfigure(col, weight=weight)

        pad_y = 3

        ttk.Label(self.body, text="Text:").grid(row=0, column=0, sticky="w", padx=(8, 6), pady=pad_y)
        self.text_method_box = ttk.Combobox(
            self.body, textvariable=self.text_method_var, values=TEXT_METHODS, state="readonly", width=12
        )
        self.text_method_box.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=pad_y)
        self.text_entry = ttk.Entry(self.body, textvariable=self.text_query_var)
        self.text_entry.grid(row=0, column=3, sticky="ew", padx=(0, 6), pady=pad_y)
        self.match_case_check = ttk.Checkbutton(self.body, text="Match case", variable=self.text_match_case_var)
        self.match_case_check.grid(row=0, column=4, sticky="w", padx=(0, 8), pady=pad_y)

        ttk.Label(self.body, text="Steno:").grid(row=1, column=0, sticky="w", padx=(8, 6), pady=pad_y)
        self.steno_method_box = ttk.Combobox(
            self.body, textvariable=self.steno_method_var, values=STENO_METHODS, state="readonly", width=12
        )
        self.steno_method_box.grid(row=1, column=1, sticky="w", padx=(0, 6), pady=pad_y)
        self.steno_entry = ttk.Entry(self.body, textvariable=self.steno_query_var)
        self.steno_entry.grid(row=1, column=3, sticky="ew", padx=(0, 6), pady=pad_y)
        self.whole_strokes_check = ttk.Checkbutton(
            self.body, text="Whole strokes only", variable=self.steno_whole_strokes_var
        )
        self.whole_strokes_check.grid(row=1, column=4, sticky="w", padx=(0, 8), pady=pad_y)

        ttk.Label(self.body, text="Scope:").grid(row=2, column=0, sticky="w", padx=(8, 6), pady=(pad_y, 6))
        self.scope_box = ttk.Combobox(
            self.body,
            textvariable=self.scope_var,
            values=["Current Dictionary", "All Dictionaries"],
            state="readonly",
            width=20,
        )
        self.scope_box.grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 6), pady=(pad_y, 6))
        ttk.Button(self.body, text="Clear", style="Secondary.TButton", command=self.clear).grid(
            row=2, column=4, sticky="e", padx=(0, 8), pady=(pad_y, 6)
        )

        self.body.pack_propagate(False)
        self.body.grid_propagate(False)
        self.body.configure(height=0)

    def _bind_events(self):
        for var in (
            self.steno_query_var,
            self.text_query_var,
            self.steno_method_var,
            self.text_method_var,
            self.steno_whole_strokes_var,
            self.text_match_case_var,
            self.scope_var,
        ):
            var.trace_add("write", lambda *_: self._on_change())

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

    def _on_change(self):
        self._update_active_hint()
        if callable(self.on_search):
            self.on_search(self.get_config())

    def _update_active_hint(self):
        self.active_hint.configure(text=self._count_suffix)
        self._refresh_search_chips()
        self._refresh_no_match_actions()

    def _search_chip_defs(self):
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

    def _refresh_search_chips(self):
        if not hasattr(self, "active_search_frame"):
            return
        for child in self.active_search_frame.winfo_children():
            child.destroy()
        chips = self._search_chip_defs()
        if not chips:
            return
        for label, callback in chips:
            ttk.Button(
                self.active_search_frame,
                text=f"{label}  x",
                style="Link.TButton",
                command=callback,
            ).pack(side=tk.LEFT, padx=(0, 6))

    def set_count_hint(self, suffix: str):
        self._count_suffix = suffix or ""
        self._update_active_hint()

    def set_no_match_actions(self, actions):
        self._no_match_actions = list(actions or [])
        self._refresh_no_match_actions()

    def _refresh_no_match_actions(self):
        show = (not self.expanded) and bool(self._count_suffix) and bool(self._no_match_actions)

        for child in self.no_match_actions.winfo_children():
            child.destroy()

        if not show:
            if self.no_match_actions.winfo_ismapped():
                self.no_match_actions.pack_forget()
            return

        if not self.no_match_actions.winfo_ismapped():
            self.no_match_actions.pack(side=tk.RIGHT, padx=(0, 8))

        for i, (label, callback) in enumerate(self._no_match_actions):
            if i > 0:
                ttk.Label(self.no_match_actions, text="·", foreground=C["fg_dim"]).pack(side=tk.LEFT, padx=4)
            ttk.Button(
                self.no_match_actions,
                text=label,
                style="Link.TButton",
                command=callback,
            ).pack(side=tk.LEFT)

    def _toggle(self, event=None):
        if self.expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self, focus_field=None, append_char=None):
        if not self.expanded:
            self.expanded = True
            self.header_label.config(text="▼ Search")
            if not self.body.winfo_ismapped():
                self.body.pack(fill=tk.X)
            if self.content_height == 0:
                self.body.pack_propagate(True)
                self.body.grid_propagate(True)
                self.body.update_idletasks()
                h = self.body.winfo_reqheight()
                self.content_height = h if h > 0 else 110
                self.body.pack_propagate(False)
                self.body.grid_propagate(False)
            self._animate(True, on_done=lambda: self._after_expand(focus_field, append_char))
            self._update_active_hint()
            if callable(self.on_collapse_changed):
                self.on_collapse_changed(False)
        elif focus_field:
            self._after_expand(focus_field, append_char)

    def collapse(self):
        if not self.expanded:
            return
        self.expanded = False
        self.header_label.config(text="▶ Search")

        def _hide_body():
            self.body.pack_forget()

        self._animate(False, on_done=_hide_body)
        self._update_active_hint()
        if callable(self.on_collapse_changed):
            self.on_collapse_changed(True)

    def is_expanded(self) -> bool:
        return self.expanded

    def _open_immediately(self):
        self.body.pack_propagate(True)
        self.body.grid_propagate(True)
        self.body.update_idletasks()
        h = self.body.winfo_reqheight()
        self.content_height = h if h > 0 else 110
        self.body.pack_propagate(False)
        self.body.grid_propagate(False)
        self.body.configure(height=self.content_height)
        self.header_label.config(text="▼ Search")
        self._update_active_hint()

    def _animate(self, opening, on_done=None):
        start = self.body.winfo_height()
        end = self.content_height if opening else 0
        delta = (end - start) / ANIMATION_STEPS

        def step(i=0):
            self.body.configure(height=int(start + delta * i))
            if i < ANIMATION_STEPS:
                self.after(ANIMATION_DURATION // ANIMATION_STEPS, step, i + 1)
            else:
                self.body.configure(height=end)
                if callable(on_done):
                    on_done()

        self.body.pack_propagate(False)
        self.body.grid_propagate(False)
        step()

    def _after_expand(self, focus_field, append_char=None):
        if focus_field == "text":
            self.text_entry.focus_set()
            if append_char:
                self.text_entry.insert(tk.END, append_char)
            self.text_entry.icursor(tk.END)
        elif focus_field == "steno":
            self.steno_entry.focus_set()
            if append_char:
                self.steno_entry.insert(tk.END, append_char)
            self.steno_entry.icursor(tk.END)

    def focus_text_entry(self, append_char=None):
        if not self.expanded:
            self.expand(focus_field="text", append_char=append_char)
        else:
            self.text_entry.focus_set()
            if append_char:
                self.text_entry.insert(tk.END, append_char)
            self.text_entry.icursor(tk.END)

    def clear(self):
        self.steno_query_var.set("")
        self.text_query_var.set("")

    def set_scope(self, scope: str):
        if scope in ("Current Dictionary", "All Dictionaries"):
            self.scope_var.set(scope)

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

    def refresh_theme(self):
        try:
            self.active_hint.configure(foreground=C["fg_dim"])
        except tk.TclError:
            pass
