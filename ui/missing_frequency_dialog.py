# ui/missing_frequency_dialog.py
"""
Review frequency-list words that are not present in the active dictionary.

The dialog is intentionally temporary: it does not create a dictionary file.
Completed rows are copied into the active dictionary using the same in-memory
entry and metadata shape as the main editor.
"""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from logic.metadata_store import save_metadata
from logic.settings_store import load_settings, save_settings
from logic.steno_validator import validate_steno
from ui.theme import C


IGNORED_WORDS_KEY = "ignored_frequency_words"


class MissingFrequencyDialog(tk.Toplevel):
    def __init__(self, parent, tab, candidates, source: str, omitted_count: int = 0):
        super().__init__(parent)
        self.title("Missing Frequency Words")
        self.geometry("860x560")
        self.minsize(740, 460)
        self.configure(bg=C["bg_panel"])
        self.transient(parent)

        self.tab = tab
        self.candidates = [
            {
                "word": c["word"],
                "frequency": int(c.get("frequency", 0)),
                "steno": "",
                "status": c.get("status", "Missing"),
                "base_status": c.get("status", "Missing"),
                "note": c.get("note", ""),
            }
            for c in candidates
        ]
        self._by_word = {c["word"]: c for c in self.candidates}
        self._settings = load_settings()
        self._source = source
        self._omitted_count = omitted_count

        self._word_var = tk.StringVar(value="")
        self._freq_var = tk.StringVar(value="")
        self._steno_var = tk.StringVar(value="")
        self._status_var = tk.StringVar(value="")
        self._hide_possible_var = tk.BooleanVar(value=False)
        self._updating_steno = False

        self._build()
        self._refresh_rows()

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._commit_current_steno())

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        top = ttk.Frame(outer)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)

        possible_count = sum(1 for c in self.candidates if c["status"] == "Possibly Covered")
        summary = f"{len(self.candidates):,} review words from {self._source}"
        if possible_count:
            summary += f" ({possible_count:,} possibly covered)"
        if self._omitted_count:
            summary += f" ({self._omitted_count:,} lower-frequency words hidden)"
        ttk.Label(top, text=summary, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            top,
            text="Fill outlines for entries you want to add. Possibly covered words are kept visible unless hidden.",
            foreground=C["fg_dim"],
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        filters = ttk.Frame(outer)
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(
            filters,
            text="Hide possibly covered",
            variable=self._hide_possible_var,
            command=self._refresh_rows,
        ).pack(side=tk.LEFT)

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=("word", "frequency", "steno", "status", "note"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("word", text="Word")
        self.tree.heading("frequency", text="Frequency")
        self.tree.heading("steno", text="Steno")
        self.tree.heading("status", text="Status")
        self.tree.heading("note", text="Note")
        self.tree.column("word", width=190, anchor="w")
        self.tree.column("frequency", width=90, anchor="e")
        self.tree.column("steno", width=150, anchor="w")
        self.tree.column("status", width=130, anchor="w")
        self.tree.column("note", width=240, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        ysb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.tag_configure("ready", foreground=C["bookmark_fg"])
        self.tree.tag_configure("added", foreground=C["fg_dim"])
        self.tree.tag_configure("ignored", foreground=C["fg_dim"])
        self.tree.tag_configure("possible", foreground=C["bookmarked_conflict_fg"])

        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_selected())
        self.tree.bind("<Double-1>", lambda e: self._focus_steno())

        editor = ttk.Frame(outer)
        editor.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        editor.columnconfigure(3, weight=1)

        ttk.Label(editor, text="Word").grid(row=0, column=0, sticky="w")
        ttk.Label(editor, textvariable=self._word_var, font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", padx=(0, 18)
        )
        ttk.Label(editor, text="Frequency").grid(row=0, column=1, sticky="w")
        ttk.Label(editor, textvariable=self._freq_var).grid(
            row=1, column=1, sticky="w", padx=(0, 18)
        )
        ttk.Label(editor, text="Steno").grid(row=0, column=2, sticky="w")
        self._steno_entry = ttk.Entry(editor, textvariable=self._steno_var, width=22)
        self._steno_entry.grid(row=1, column=2, sticky="w", padx=(0, 18))
        self._steno_entry.bind("<Return>", lambda e: self._commit_current_steno())
        self._steno_var.trace_add("write", self._uppercase_steno)

        ttk.Label(editor, textvariable=self._status_var, foreground=C["conflict_fg"]).grid(
            row=1, column=3, sticky="w"
        )

        btn_row = ttk.Frame(outer)
        btn_row.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(btn_row, text="Ignore Selected", command=self._ignore_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_row, text="Restore Selected", command=self._restore_selected).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(
            btn_row, text="Add Selected", style="Primary.TButton",
            command=self._add_selected
        ).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(
            btn_row, text="Add Completed", style="Primary.TButton",
            command=self._add_completed
        ).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _visible_candidates(self):
        if not self._hide_possible_var.get():
            return self.candidates
        return [
            c for c in self.candidates
            if c["status"] != "Possibly Covered"
        ]

    def _refresh_rows(self):
        selected = set(self.tree.selection())
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for c in self._visible_candidates():
            status = c["status"]
            self.tree.insert(
                "",
                tk.END,
                iid=c["word"],
                values=(c["word"], f"{c['frequency']:,}", c["steno"], status, c["note"]),
                tags=self._tags_for(status),
            )

        existing = [iid for iid in selected if self.tree.exists(iid)]
        if existing:
            self.tree.selection_set(existing)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self._load_selected()

    def _load_selected(self):
        selection = self.tree.selection()
        if not selection:
            self._word_var.set("")
            self._freq_var.set("")
            self._steno_var.set("")
            self._status_var.set("")
            return
        word = selection[0]
        c = self._by_word.get(word)
        if not c:
            return
        self._word_var.set(c["word"])
        self._freq_var.set(f"{c['frequency']:,}")
        self._steno_var.set(c["steno"])
        self._status_var.set("")

    def _focus_steno(self):
        self._steno_entry.focus_set()
        self._steno_entry.select_range(0, tk.END)

    def _uppercase_steno(self, *_):
        if self._updating_steno:
            return
        current = self._steno_var.get()
        upper = current.upper()
        if upper != current:
            self._updating_steno = True
            try:
                self._steno_var.set(upper)
            finally:
                self._updating_steno = False

    def _commit_current_steno(self):
        selection = self.tree.selection()
        if not selection:
            return "break"
        word = selection[0]
        c = self._by_word.get(word)
        if not c or c["status"] in {"Added", "Ignored"}:
            return "break"
        steno = self._steno_var.get().strip().upper()
        if steno:
            ok, msg = validate_steno(steno)
            if not ok:
                self._status_var.set(msg)
                self._steno_entry.focus_set()
                return "break"
        c["steno"] = steno
        c["status"] = "Ready" if steno else c["base_status"]
        self._refresh_item(c)
        self._status_var.set("")
        return "break"

    def _refresh_item(self, c):
        if self.tree.exists(c["word"]):
            self.tree.item(
                c["word"],
                values=(c["word"], f"{c['frequency']:,}", c["steno"], c["status"], c["note"]),
                tags=self._tags_for(c["status"]),
            )

    def _tags_for(self, status):
        if status == "Ready":
            return ("ready",)
        if status == "Added":
            return ("added",)
        if status == "Ignored":
            return ("ignored",)
        if status == "Possibly Covered":
            return ("possible",)
        return ()

    def _add_selected(self):
        self._commit_current_steno()
        rows = [self._by_word[iid] for iid in self.tree.selection() if iid in self._by_word]
        self._add_rows(rows)

    def _add_completed(self):
        self._commit_current_steno()
        rows = [
            c for c in self.candidates
            if c["steno"] and c["status"] not in {"Added", "Ignored"}
        ]
        self._add_rows(rows)

    def _add_rows(self, rows):
        rows = [r for r in rows if r.get("steno") and r.get("status") not in {"Added", "Ignored"}]
        if not rows:
            messagebox.showinfo("Missing Frequency Words", "No completed rows to add.", parent=self)
            return

        existing_words = _existing_plain_words(self.tab)
        today = date.today().strftime("%Y-%m-%d")
        added = 0

        for row in rows:
            steno = row["steno"].strip().upper()
            ok, msg = validate_steno(steno)
            if not ok:
                self.tree.selection_set(row["word"])
                self._load_selected()
                self._status_var.set(msg)
                self._steno_entry.focus_set()
                return
            if row["word"].lower() in existing_words:
                row["status"] = "Added"
                continue

            entry = {
                "steno": steno,
                "english": row["word"],
                "modified": today,
                "date_added": today,
            }
            meta = {
                "date_added": today,
                "modified": today,
                "brief": False,
                "comments": "",
                "bookmarked": False,
                "frequency": row["frequency"],
            }
            self.tab.entries.append(entry)
            if self.tab.metadata is not None:
                self.tab.metadata[steno] = copy.deepcopy(meta)
            self.tab._push_undo_frame({
                "op": "add",
                "label": "Add Missing Frequency Word",
                "entry_ref": entry,
                "steno": steno,
                "meta": copy.deepcopy(meta),
            })
            existing_words.add(row["word"].lower())
            row["status"] = "Added"
            added += 1

        if added:
            self.tab._metadata_dirty = True
            if self.tab.dict_path and self.tab.metadata is not None:
                try:
                    save_metadata(self.tab.dict_path, self.tab.metadata)
                except Exception as e:
                    messagebox.showerror(
                        "Metadata Save Error",
                        f"Added entries, but failed to save their metadata:\n{e}",
                        parent=self,
                    )
            self.tab._rebuild_conflict_stenos()
            self.tab._apply_filters()
            if self.tab.on_entries_changed:
                self.tab.on_entries_changed(len(self.tab.entries))
        self._refresh_rows()
        messagebox.showinfo(
            "Missing Frequency Words",
            f"Added {added:,} entr{'y' if added == 1 else 'ies'}.",
            parent=self,
        )

    def _ignore_selected(self):
        words = [iid for iid in self.tree.selection() if iid in self._by_word]
        if not words:
            return
        ignored = set(self._settings.get(IGNORED_WORDS_KEY, []))
        ignored.update(w.lower() for w in words)
        self._settings[IGNORED_WORDS_KEY] = sorted(ignored)
        save_settings(self._settings)
        for word in words:
            self._by_word[word]["status"] = "Ignored"
        self._refresh_rows()

    def _restore_selected(self):
        words = [iid for iid in self.tree.selection() if iid in self._by_word]
        if not words:
            return
        ignored = set(self._settings.get(IGNORED_WORDS_KEY, []))
        for word in words:
            ignored.discard(word.lower())
            c = self._by_word[word]
            if c["status"] == "Ignored":
                c["status"] = "Ready" if c["steno"] else c["base_status"]
        self._settings[IGNORED_WORDS_KEY] = sorted(ignored)
        save_settings(self._settings)
        self._refresh_rows()


class IgnoredFrequencyWordsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Ignored Frequency Words")
        self.geometry("420x460")
        self.minsize(340, 340)
        self.configure(bg=C["bg_panel"])
        self.transient(parent)
        self.grab_set()

        self._settings = load_settings()
        self._words = sorted({
            str(w).strip().lower()
            for w in self._settings.get(IGNORED_WORDS_KEY, [])
            if str(w).strip()
        })
        self._build()
        self._refresh_rows()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="Ignored frequency words", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        frame = ttk.Frame(outer)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            frame,
            selectmode=tk.EXTENDED,
            bg=C["bg_input"],
            fg=C["fg"],
            selectbackground=C["accent"],
            selectforeground="white",
            activestyle="none",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            font=("Segoe UI", 10),
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.listbox.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=ysb.set)

        btn_row = ttk.Frame(outer)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(btn_row, text="Restore Selected", command=self._restore_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_row, text="Clear All", command=self._clear_all).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _refresh_rows(self):
        self.listbox.delete(0, tk.END)
        for word in self._words:
            self.listbox.insert(tk.END, word)

    def _save(self):
        self._settings[IGNORED_WORDS_KEY] = self._words
        save_settings(self._settings)

    def _restore_selected(self):
        selected = set(self.listbox.curselection())
        if not selected:
            return
        self._words = [word for i, word in enumerate(self._words) if i not in selected]
        self._save()
        self._refresh_rows()

    def _clear_all(self):
        if not self._words:
            return
        if not messagebox.askyesno(
            "Clear Ignored Words",
            "Restore all ignored frequency words?",
            parent=self,
        ):
            return
        self._words = []
        self._save()
        self._refresh_rows()


def _existing_plain_words(tab) -> set[str]:
    return {
        (entry.get("english") or "").strip().lower()
        for entry in tab.entries
        if _is_plain_word((entry.get("english") or "").strip())
    }


def _is_plain_word(value: str) -> bool:
    if not value:
        return False
    return all(ch.isalpha() or ch == "'" for ch in value)
