# ui/find_replace_dialog.py
import re
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from logic.metadata_store import save_metadata
from ui.theme import C


def _style(d):
    d.configure(bg=C["bg_panel"])


class FindReplaceDialog(tk.Toplevel):
    """
    Non-modal Find & Replace dialog.

    Always operates on the tab returned by get_tab_fn() at the moment each
    action fires, so switching tabs mid-session naturally targets the
    active dictionary.

    Find searches the currently visible (filtered) rows.
    Replace All operates on ALL entries regardless of any active filter.
    """

    def __init__(self, parent, get_tab_fn):
        super().__init__(parent)
        self.get_tab = get_tab_fn
        self.title("Find & Replace")
        self.resizable(False, False)
        _style(self)
        self.transient(parent)          # sits above main window, not modal

        self._matches:   list = []      # treeview item IDs matching current query
        self._match_idx: int  = -1

        self._build()
        self._position()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build(self):
        f = ttk.Frame(self, padding=14)
        f.pack(fill=tk.BOTH, expand=True)

        kw = {"padx": 8, "pady": 4}

        # Find
        ttk.Label(f, text="Find:", width=9, anchor="e").grid(row=0, column=0, **kw)
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(f, textvariable=self.find_var, width=36)
        self.find_entry.grid(row=0, column=1, columnspan=2, sticky="ew", **kw)
        self.find_var.trace_add("write", lambda *_: self._update_matches())

        # Replace
        ttk.Label(f, text="Replace:", width=9, anchor="e").grid(row=1, column=0, **kw)
        self.replace_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.replace_var, width=36).grid(
            row=1, column=1, columnspan=2, sticky="ew", **kw
        )

        # Options
        ttk.Label(f, text="In:", width=9, anchor="e").grid(row=2, column=0, **kw)
        self.field_var = tk.StringVar(value="Translation")
        ttk.Combobox(
            f, textvariable=self.field_var,
            values=["Translation", "Steno", "Both"],
            state="readonly", width=16,
        ).grid(row=2, column=1, sticky="w", **kw)
        self.field_var.trace_add("write", lambda *_: self._update_matches())

        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f, text="Match case",
            variable=self.case_var,
            command=self._update_matches,
        ).grid(row=2, column=2, sticky="w", **kw)

        # Match count / status
        self.status_label = ttk.Label(f, text="", foreground=C["fg_dim"])
        self.status_label.grid(row=3, column=0, columnspan=3, sticky="w",
                               padx=8, pady=(6, 2))

        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=6, padx=2
        )

        # Buttons
        btn = ttk.Frame(f)
        btn.grid(row=5, column=0, columnspan=3, pady=(0, 2))
        ttk.Button(btn, text="◀ Prev",     command=self._find_prev).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn, text="Next ▶",     command=self._find_next).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn, text="Replace",    command=self._replace).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn, text="Replace All",command=self._replace_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn, text="Close",      command=self._on_close).pack(side=tk.LEFT, padx=(14, 3))

        f.columnconfigure(1, weight=1)

        self.bind("<Return>",       lambda e: self._find_next())
        self.bind("<Shift-Return>", lambda e: self._find_prev())
        self.find_entry.focus_set()

    def _position(self):
        """Place the dialog in the top-right of the main window."""
        self.update_idletasks()
        px = self.master.winfo_rootx()
        py = self.master.winfo_rooty()
        pw = self.master.winfo_width()
        dw = self.winfo_width()
        self.geometry(f"+{px + pw - dw - 20}+{py + 80}")

    def refresh_theme(self):
        """Re-apply colour-dependent settings after a theme switch."""
        try:
            self.configure(bg=C["bg_panel"])
            if hasattr(self, "status_label"):
                self.status_label.configure(foreground=C["fg_dim"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Match logic
    # ------------------------------------------------------------------
    def _update_matches(self):
        tab = self.get_tab()
        if not tab:
            self._clear(tab)
            return

        find_text = self.find_var.get()
        if not find_text:
            self._clear(tab)
            return

        flags   = 0 if self.case_var.get() else re.IGNORECASE
        field   = self.field_var.get()
        pattern = re.compile(re.escape(find_text), flags)

        matches = [
            item for item in tab.tree.get_children()
            if self._row_matches(tab, item, pattern, field)
        ]

        self._matches   = matches
        self._match_idx = -1
        tab.apply_find_highlights(set(matches))

        n = len(matches)
        self.status_label.config(
            text=f"{n} match{'es' if n != 1 else ''}" if n else "No matches"
        )

    def _clear(self, tab):
        if tab:
            tab.clear_find_highlights()
        self._matches   = []
        self._match_idx = -1
        self.status_label.config(text="")

    def _row_matches(self, tab, item, pattern, field):
        row = dict(zip(tab.column_order, tab.tree.item(item, "values")))
        if field in ("Translation", "Both") and pattern.search(row.get("english", "")):
            return True
        if field in ("Steno",       "Both") and pattern.search(row.get("steno", "")):
            return True
        return False

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _find_next(self):
        if not self._matches:
            self._update_matches()
        if not self._matches:
            return
        self._match_idx = (self._match_idx + 1) % len(self._matches)
        self._jump()

    def _find_prev(self):
        if not self._matches:
            self._update_matches()
        if not self._matches:
            return
        self._match_idx = (self._match_idx - 1) % len(self._matches)
        self._jump()

    def _jump(self):
        tab = self.get_tab()
        if not tab or not self._matches:
            return
        item = self._matches[self._match_idx]
        tab.tree.selection_set(item)
        tab.tree.see(item)
        n   = len(self._matches)
        idx = self._match_idx + 1
        self.status_label.config(text=f"{idx} of {n} match{'es' if n != 1 else ''}")

    # ------------------------------------------------------------------
    # Replace (single)
    # ------------------------------------------------------------------
    def _replace(self):
        tab = self.get_tab()
        if not tab:
            return

        find_text    = self.find_var.get()
        replace_text = self.replace_var.get()
        field        = self.field_var.get()
        if not find_text:
            return

        flags   = 0 if self.case_var.get() else re.IGNORECASE
        pattern = re.compile(re.escape(find_text), flags)

        selected = tab.tree.selection()
        if not selected:
            self._find_next()
            return

        item = selected[0]
        entry = tab.entry_for_item(item) if hasattr(tab, "entry_for_item") else None
        if entry is None:
            return
        steno = entry["steno"]
        english = entry.get("english") or ""
        modified = False

        if field in ("Translation", "Both"):
            new_english = pattern.sub(replace_text, english)
            if new_english != english:
                self._update_field(tab, entry, "english", new_english)
                modified = True

        if field in ("Steno", "Both"):
            new_steno = pattern.sub(replace_text, steno)
            if new_steno != steno:
                self._rename_steno(tab, entry, new_steno)
                modified = True

        if modified:
            tab._set_dirty()
            if not self._save_tab_metadata(tab):
                return
            tab._rebuild_conflict_stenos()
            if hasattr(tab, "_refresh_dictionary_header"):
                tab._refresh_dictionary_header()
            tab._apply_filters()
            self._update_matches()

        self._find_next()

    # ------------------------------------------------------------------
    # Replace All
    # ------------------------------------------------------------------
    def _replace_all(self):
        tab = self.get_tab()
        if not tab:
            return

        find_text    = self.find_var.get()
        replace_text = self.replace_var.get()
        field        = self.field_var.get()
        if not find_text:
            return

        flags   = 0 if self.case_var.get() else re.IGNORECASE
        pattern = re.compile(re.escape(find_text), flags)

        # Count matches first so the warning can show a meaningful number
        preview = 0
        for entry in tab.entries:
            if field in ("Translation", "Both") and pattern.search(entry.get("english") or ""):
                preview += 1
            if field in ("Steno", "Both") and pattern.search(entry["steno"]):
                preview += 1

        if preview == 0:
            messagebox.showinfo("Replace All", "No matches found.", parent=self)
            self._update_matches()
            return

        # Replace All is not undoable — warn the user and give them the chance
        # to save first so they have a clean restore point
        proceed = messagebox.askyesno(
            "Replace All — Cannot Be Undone",
            f"Replace All will modify {preview} occurrence"
            f"{'s' if preview != 1 else ''} and cannot be undone.\n\n"
            f"A backup of the current state will be saved automatically "
            f"before continuing.\n\n"
            f"Continue?",
            parent=self,
        )
        if not proceed:
            return

        if not tab.dict_path:
            messagebox.showerror(
                "Replace All",
                "Save this dictionary before using Replace All so a backup can be created.",
                parent=self,
            )
            return

        # If there are already unsaved edits, save them first so the backup
        # taken below reflects the actual current state, not stale disk data.
        if getattr(tab, "_json_dirty", False) and not tab.save_json():
            return

        try:
            from logic.backup_store import backup_dictionary
            ok, msg = backup_dictionary(tab.dict_path, kind="save")
        except Exception as e:
            ok, msg = False, str(e)

        if not ok:
            messagebox.showerror(
                "Backup Failed",
                f"Could not back up the current dictionary:\n\n{msg}",
                parent=self,
            )
            return

        today = date.today().strftime("%Y-%m-%d")
        count = 0

        # Operate on ALL entries (not just the filtered view)
        for entry in list(tab.entries):          # list() because steno rename mutates
            if field in ("Translation", "Both"):
                old = entry.get("english") or ""
                new = pattern.sub(replace_text, old)
                if new != old:
                    entry["english"]  = new
                    entry["modified"] = today
                    if tab.metadata and entry["steno"] in tab.metadata:
                        tab.metadata[entry["steno"]]["modified"] = today
                    count += 1

            if field in ("Steno", "Both"):
                old = entry["steno"]
                new = pattern.sub(replace_text, old)
                if new != old:
                    self._rename_steno(tab, entry, new)
                    count += 1

        if count:
            tab._set_dirty()
            if not self._save_tab_metadata(tab):
                return
            tab._rebuild_conflict_stenos()
            if hasattr(tab, "_refresh_dictionary_header"):
                tab._refresh_dictionary_header()
            tab._apply_filters()
            messagebox.showinfo(
                "Replace All",
                f"Replaced {count} occurrence{'s' if count != 1 else ''}.",
                parent=self,
            )
        else:
            messagebox.showinfo("Replace All", "No matches found.", parent=self)

        self._update_matches()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _update_field(self, tab, entry, field, new_value):
        today = date.today().strftime("%Y-%m-%d")
        steno = entry["steno"]
        entry[field]      = new_value
        entry["modified"] = today
        if tab.metadata and steno in tab.metadata:
            tab.metadata[steno]["modified"] = today

    def _rename_steno(self, tab, entry, new_steno):
        """Rename a steno key: update the entry, metadata, bookmarks, conflicts."""
        today = date.today().strftime("%Y-%m-%d")
        old_steno = entry["steno"]
        entry["steno"]    = new_steno
        entry["modified"] = today
        if tab.metadata and old_steno in tab.metadata:
            m = tab.metadata.pop(old_steno)
            m["modified"] = today
            tab.metadata[new_steno] = m
        if old_steno in tab.bookmarked_stenos:
            tab.bookmarked_stenos.discard(old_steno)
            tab.bookmarked_stenos.add(new_steno)
        tab.conflict_stenos.discard(old_steno)

    def _save_tab_metadata(self, tab) -> bool:
        if not getattr(tab, "dict_path", None) or tab.metadata is None:
            return True
        try:
            save_metadata(tab.dict_path, tab.metadata)
            tab._metadata_dirty = False
            return True
        except Exception as e:
            messagebox.showerror(
                "Metadata Save Error",
                f"Failed to save entry metadata:\n{e}",
                parent=self,
            )
            return False

    def _on_close(self):
        tab = self.get_tab()
        if tab:
            tab.clear_find_highlights()
        self.destroy()
