# ui/dictionary_tab.py
import copy
import os
import re
import json
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from logic.settings_store import load_settings, save_settings
from logic.metadata_store import save_metadata, ensure_metadata
from logic.undo_stack import UndoStack
from ui.theme import C


MAX_COMMENT_CHARS  = 40
ANIMATION_DURATION = 180   # ms
ANIMATION_STEPS    = 12

# Cap the number of rows actually inserted into the Treeview.  Tk's Treeview
# is designed for hundreds of rows, not hundreds of thousands - inserting
# 100k rows takes ~5 seconds and every keystroke triggers a full rebuild.
# Capping at this many rows keeps every operation fast; users find what they
# want by typing in the search bar rather than scrolling, so the cap is
# rarely felt.  When more matches exist than fit, a hint near the table
# tells the user how many were hidden.
MAX_DISPLAY_ROWS = 500

WRITTEN_NUMBERS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "trillion",
})

# Pre-compiled regexes used in the per-entry filter loop.  Compiling once at
# module load saves ~half the work for each filter pass on a large dictionary.
_DIGIT_RE = re.compile(r"\d")
_WORD_RE  = re.compile(r"[a-z]+")
_PUNCT_RE = re.compile(
    r"[\.,;:!\?\-\u2014\u2013'\"\(\)\[\]\{\}/\\&\*@#%\$\^\+=<>~\|`]"
)


def center_on_parent(dialog, parent):
    dialog.update_idletasks()
    pw, ph = parent.winfo_width(),  parent.winfo_height()
    px, py = parent.winfo_rootx(),  parent.winfo_rooty()
    dw, dh = dialog.winfo_width(),  dialog.winfo_height()
    dialog.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")


def _style_dialog(dialog):
    dialog.configure(bg=C["bg_panel"])


class DictionaryTab(ttk.Frame):
    """Main dictionary workspace."""

    HEADINGS = {
        "steno":    "Steno",
        "english":  "Translation",
        "S":        "S",
        "W":        "W",
        "B":        "B",
        "F":        "F",
        "added":    "Added",
        "modified": "Modified",
        "comments": "Comments",
    }

    DEFAULT_WIDTHS = {
        "steno":    160,
        "english":  340,
        "S":        40,
        "W":        40,
        "B":        30,
        "F":        70,
        "added":    90,
        "modified": 90,
        "comments": 300,
    }

    # F (frequency) is not listed here — it is inserted after B dynamically
    # when the user enables "Show frequency column" in the filter panel.
    VIEW_COLUMNS = ["steno", "english", "S", "W"]
    EDIT_COLUMNS = ["steno", "english", "S", "W", "B", "added", "modified", "comments"]

    def __init__(self, parent, name="Dictionary",
                 on_entries_changed=None,
                 on_filter_count_changed=None):
        super().__init__(parent)
        self.name = name
        self.on_entries_changed   = on_entries_changed
        self._on_filter_count_changed = on_filter_count_changed

        # Data
        self.entries          = []
        self.filtered_entries = []
        self.dict_path        = None
        self.metadata         = {}
        self._metadata_dirty  = False
        self._json_dirty      = False   # tracks unsaved edits; shown as * on tab title

        # Session-only state
        self.bookmarked_stenos: set = set()
        self.conflict_stenos:   set = set()
        self._page: int = 0   # current page for paginated treeview display

        # Undo / redo
        self._undo_stack = UndoStack()

        # Sorting
        self.sort_column  = "english"
        self.sort_reverse = False

        # Filters
        self.filter_has_comments        = tk.BooleanVar(value=False)
        self.filter_is_brief            = tk.BooleanVar(value=False)
        self.filter_bookmarked          = tk.BooleanVar(value=False)
        self.filter_capitalised         = tk.BooleanVar(value=False)
        self.filter_has_digits          = tk.BooleanVar(value=False)
        self.filter_has_written_numbers = tk.BooleanVar(value=False)
        self.filter_has_punctuation     = tk.BooleanVar(value=False)
        self.filter_conflicts           = tk.BooleanVar(value=False)

        # Settings (loaded once here; refreshed on tab activation)
        self.settings      = load_settings()
        self.column_widths = self.settings.get("column_widths", {})

        # Frequency filters
        self.filter_has_frequency  = tk.BooleanVar(value=False)
        self.filter_top_freq       = tk.BooleanVar(value=False)
        self.filter_top_freq_n_var = tk.StringVar(value="500")
        self.filter_top_freq_n_var.trace_add("write", lambda *_: self._apply_filters())
        # Frequency column display toggle (persisted in settings)
        show_freq = self.settings.get("show_freq_column", False)
        self.show_freq_column = tk.BooleanVar(value=show_freq)

        # Build the active column order, inserting F when the toggle is on
        self.column_order = self._make_column_order(show_freq)

        # Filter panel state
        self.filters_expanded      = False
        self.filter_content_height = 0

        # Build
        self._build_dictionary_header()
        self._build_filter_panel()
        self._build_tree()
        self._sort_by("english", remember=False)
        self.bind("<<DictionaryTabActivated>>", self._on_activated)

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------
    def _on_activated(self, event=None):
        """Tab switch: sync column widths only — no row rebuild."""
        self.settings      = load_settings()
        self.column_widths = self.settings.get("column_widths", {})
        for col in self.column_order:
            self.tree.column(col, width=self.column_widths.get(col, self.DEFAULT_WIDTHS[col]))
        self._update_sort_headings()

    # ------------------------------------------------------------------
    # Column order helpers
    # ------------------------------------------------------------------
    @classmethod
    def _make_column_order(cls, show_freq: bool) -> list:
        """Return the active column list, inserting F after B when requested."""
        cols = list(cls.EDIT_COLUMNS)
        if show_freq:
            cols.insert(cols.index("B") + 1, "F")
        return cols

    def _configure_columns(self):
        """Apply column headers, widths, and anchors for the current column_order."""
        self.tree.configure(columns=self.column_order)
        for col in self.column_order:
            self.tree.heading(
                col, text=self.HEADINGS[col],
                command=lambda c=col: self._sort_by(c),
            )
            width  = self.column_widths.get(col, self.DEFAULT_WIDTHS[col])
            anchor = "w" if col in ("steno", "english", "comments") else "center"
            self.tree.column(col, width=width, anchor=anchor)

    def _toggle_freq_column(self):
        """Show or hide the F column; sync to all other open tabs and persist."""
        show = self.show_freq_column.get()

        # Persist
        settings = load_settings()
        settings["show_freq_column"] = show
        save_settings(settings)

        # Apply to this tab
        self._apply_freq_column(show)

        # Sync every other open tab so all tabs stay consistent
        app = self.winfo_toplevel()
        if hasattr(app, "tabs"):
            for tab in app.tabs.values():
                if tab is not self and hasattr(tab, "show_freq_column"):
                    tab.show_freq_column.set(show)
                    tab._apply_freq_column(show)

    def _apply_freq_column(self, show: bool):
        """Rebuild column_order and reconfigure the Treeview accordingly."""
        self.column_order = self._make_column_order(show)
        self._configure_columns()
        self._configure_tree_tags()
        self._update_sort_headings()
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Dirty / unsaved-changes indicator
    # ------------------------------------------------------------------
    def _set_dirty(self, dirty: bool = True):
        """Mark the tab as having unsaved changes and update the tab title."""
        if dirty == self._json_dirty:
            return
        self._json_dirty = dirty
        try:
            nb    = self.nametowidget(self.winfo_parent())
            title = self.name + (" *" if dirty else "")
            nb.tab(self, text=title)
        except Exception:
            pass
        self._refresh_dictionary_header()

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------
    def _rebuild_conflict_stenos(self):
        """Flag steno keys that appear more than once within this dictionary."""
        counts: dict = {}
        for e in self.entries:
            counts[e["steno"]] = counts.get(e["steno"], 0) + 1
        self.conflict_stenos = {s for s, n in counts.items() if n > 1}

    # ------------------------------------------------------------------
    # Find highlight support (used by FindReplaceDialog)
    # ------------------------------------------------------------------
    def apply_find_highlights(self, item_ids: set):
        """Add or remove the find_match tag from all visible rows."""
        for item in self.tree.get_children():
            tags = [t for t in self.tree.item(item, "tags") if t != "find_match"]
            if item in item_ids:
                tags.append("find_match")
            self.tree.item(item, tags=tags)

    def clear_find_highlights(self):
        """Remove find_match tag from all rows."""
        for item in self.tree.get_children():
            tags = [t for t in self.tree.item(item, "tags") if t != "find_match"]
            self.tree.item(item, tags=tags)

    # ------------------------------------------------------------------
    # Dictionary header
    # ------------------------------------------------------------------
    def _build_dictionary_header(self):
        self.header_frame = ttk.Frame(self, style="DictionaryHeader.TFrame")
        self.header_frame.pack(fill=tk.X, pady=(0, 8))

        self.header_accent = ttk.Frame(
            self.header_frame, width=4, style="HeaderAccent.TFrame"
        )
        self.header_accent.pack(side=tk.LEFT, fill=tk.Y)

        body = ttk.Frame(self.header_frame)
        body.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=9)

        title_row = ttk.Frame(body)
        title_row.pack(fill=tk.X)

        self.header_title_var = tk.StringVar(value=self.name)
        self.header_title = ttk.Label(
            title_row,
            textvariable=self.header_title_var,
            style="HeaderTitle.TLabel",
        )
        self.header_title.pack(side=tk.LEFT)

        self.header_state_var = tk.StringVar(value="Saved")
        self.header_state = ttk.Label(
            title_row,
            textvariable=self.header_state_var,
            style="HeaderSuccess.TLabel",
        )
        self.header_state.pack(side=tk.RIGHT, padx=(8, 0))

        self.header_path_var = tk.StringVar(value="")
        self.header_path = ttk.Label(
            body,
            textvariable=self.header_path_var,
            style="HeaderSubtle.TLabel",
        )
        self.header_path.pack(fill=tk.X, pady=(2, 7))

        metrics = ttk.Frame(body)
        metrics.pack(fill=tk.X)

        self.header_entries_var = tk.StringVar(value="0 entries")
        self.header_conflicts_var = tk.StringVar(value="0 conflicts")
        self.header_briefs_var = tk.StringVar(value="0 briefs")
        self.header_frequency_var = tk.StringVar(value="0% frequency")

        self.header_entries = ttk.Label(
            metrics, textvariable=self.header_entries_var, style="HeaderInfo.TLabel"
        )
        self.header_conflicts = ttk.Label(
            metrics, textvariable=self.header_conflicts_var, style="HeaderChip.TLabel"
        )
        self.header_briefs = ttk.Label(
            metrics, textvariable=self.header_briefs_var, style="HeaderChip.TLabel"
        )
        self.header_frequency = ttk.Label(
            metrics, textvariable=self.header_frequency_var, style="HeaderChip.TLabel"
        )

        for widget in (
            self.header_entries,
            self.header_conflicts,
            self.header_briefs,
            self.header_frequency,
        ):
            widget.pack(side=tk.LEFT, padx=(0, 7), pady=(0, 1))

        self._refresh_dictionary_header()

    def _refresh_dictionary_header(self):
        if not hasattr(self, "header_title_var"):
            return

        total = len(self.entries)
        metadata = self.metadata or {}
        conflict_count = len(self.conflict_stenos)
        brief_count = sum(
            1 for entry in self.entries
            if metadata.get(entry["steno"], {}).get("brief", False)
        )
        freq_count = sum(
            1 for entry in self.entries
            if metadata.get(entry["steno"], {}).get("frequency", 0)
        )
        freq_pct = round((freq_count / total) * 100) if total else 0

        self.header_title_var.set(self.name or "Dictionary")
        self.header_path_var.set(self._short_header_path(self.dict_path))
        self.header_entries_var.set(f"{total:,} entr{'y' if total == 1 else 'ies'}")
        self.header_conflicts_var.set(
            f"{conflict_count:,} conflict{'s' if conflict_count != 1 else ''}"
        )
        self.header_briefs_var.set(
            f"{brief_count:,} brief{'s' if brief_count != 1 else ''}"
        )
        self.header_frequency_var.set(f"{freq_pct}% frequency matched")

        if self._json_dirty:
            self.header_state_var.set("Unsaved")
            self.header_state.configure(style="HeaderWarning.TLabel")
        else:
            self.header_state_var.set("Saved")
            self.header_state.configure(style="HeaderSuccess.TLabel")

        self.header_conflicts.configure(
            style="HeaderDanger.TLabel" if conflict_count else "HeaderChip.TLabel"
        )
        self.header_frequency.configure(
            style="HeaderSuccess.TLabel" if freq_pct >= 75 else "HeaderChip.TLabel"
        )

    def _short_header_path(self, path: str | None) -> str:
        if not path:
            return "Unsaved dictionary"
        if len(path) <= 96:
            return path
        drive, tail = os.path.splitdrive(path)
        folder, filename = os.path.split(tail)
        parts = [p for p in folder.split(os.sep) if p]
        if len(parts) >= 2:
            return os.path.join(drive + os.sep, parts[0], "...", parts[-1], filename)
        return os.path.join(drive + os.sep, "...", filename)

    # ------------------------------------------------------------------
    # Filter Panel (animated)
    # ------------------------------------------------------------------
    def _build_filter_panel(self):
        self.filter_container = ttk.Frame(self)
        self.filter_container.pack(fill=tk.X)

        # Header row (toggle + entry count)
        self.filter_header = ttk.Frame(self.filter_container)
        self.filter_header.pack(fill=tk.X)
        self.filter_header.bind("<Button-1>", self._toggle_filters)

        self.filter_label = ttk.Label(self.filter_header, text="▶ Filters", padding=6)
        self.filter_label.pack(side=tk.LEFT)
        self.filter_label.bind("<Button-1>", self._toggle_filters)

        self.count_label = ttk.Label(
            self.filter_header, text="", foreground=C["fg_dim"], padding=(0, 6)
        )
        self.count_label.pack(side=tk.RIGHT, padx=12)

        # Content (two rows of checkboxes)
        self.filter_content = ttk.Frame(self.filter_container)
        self.filter_content.pack(fill=tk.X)

        # Row 1: entry-level state
        row1 = ttk.Frame(self.filter_content)
        row1.pack(fill=tk.X, padx=4)
        for text, var in [
            ("Has comments", self.filter_has_comments),
            ("Is brief",     self.filter_is_brief),
            ("Bookmarked",   self.filter_bookmarked),
            ("Conflicts",    self.filter_conflicts),
        ]:
            ttk.Checkbutton(row1, text=text, variable=var,
                            command=self._apply_filters).pack(side=tk.LEFT, padx=10, pady=4)

        # Row 2: content predicates (what's IN the translation)
        row2 = ttk.Frame(self.filter_content)
        row2.pack(fill=tk.X, padx=4)
        for text, var in [
            ("Capitalised",       self.filter_capitalised),
            ("Numbers (0–9)",     self.filter_has_digits),
            ("Numbers (written)", self.filter_has_written_numbers),
            ("Punctuation",       self.filter_has_punctuation),
        ]:
            ttk.Checkbutton(row2, text=text, variable=var,
                            command=self._apply_filters).pack(side=tk.LEFT, padx=10, pady=4)

        # Row 3: frequency controls
        row3 = ttk.Frame(self.filter_content)
        row3.pack(fill=tk.X, padx=4)
        ttk.Checkbutton(
            row3, text="Has frequency", variable=self.filter_has_frequency,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=10, pady=4)

        ttk.Checkbutton(
            row3, text="Top", variable=self.filter_top_freq,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=(16, 2), pady=4)
        ttk.Entry(row3, textvariable=self.filter_top_freq_n_var, width=6).pack(
            side=tk.LEFT, pady=4,
        )
        ttk.Label(row3, text="entries by frequency").pack(side=tk.LEFT, padx=(4, 16), pady=4)

        ttk.Checkbutton(
            row3, text="Show frequency column",
            variable=self.show_freq_column,
            command=self._toggle_freq_column,
        ).pack(side=tk.LEFT, padx=10, pady=4)

        self.filter_content.pack_propagate(False)
        self.filter_content.configure(height=0)

    def _toggle_filters(self, event=None):
        self.filters_expanded = not self.filters_expanded
        if self.filters_expanded:
            self.filter_label.config(text="▼ Filters")
            if self.filter_content_height == 0:
                self.filter_content.pack_propagate(True)
                self.filter_content.update_idletasks()
                h = self.filter_content.winfo_reqheight()
                self.filter_content_height = h if h > 0 else 68
                self.filter_content.pack_propagate(False)
            self._animate_filter(opening=True)
        else:
            self.filter_label.config(text="▶ Filters")
            self._animate_filter(opening=False)

    def _animate_filter(self, opening):
        start = self.filter_content.winfo_height()
        end   = self.filter_content_height if opening else 0
        delta = (end - start) / ANIMATION_STEPS

        def step(i=0):
            self.filter_content.configure(height=int(start + delta * i))
            if i < ANIMATION_STEPS:
                self.after(ANIMATION_DURATION // ANIMATION_STEPS, step, i + 1)
            else:
                self.filter_content.configure(height=end)

        self.filter_content.pack_propagate(False)
        step()

    # ------------------------------------------------------------------
    # Treeview
    # ------------------------------------------------------------------
    def _build_tree(self):
        # Conflict warning banner - hidden until a conflict is detected on
        # add/edit/receive.  Sits above the tree, can be dismissed.
        self._conflict_banner = ttk.Frame(self)
        self._conflict_banner_label = ttk.Label(
            self._conflict_banner,
            text="",
            anchor="w",
            padding=(10, 5),
        )
        self._conflict_banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._conflict_banner_close = ttk.Label(
            self._conflict_banner,
            text="✕",
            cursor="hand2",
            padding=(8, 5),
        )
        self._conflict_banner_close.pack(side=tk.RIGHT)
        self._conflict_banner_close.bind(
            "<Button-1>", lambda e: self._hide_conflict_banner()
        )
        # Don't pack the banner itself - shown on demand by _show_conflict_banner

        # Pagination bar — hidden until filtered_entries exceed MAX_DISPLAY_ROWS.
        # Shows "Showing X–Y of Z" plus Prev / Next buttons.
        self._pagination_frame = ttk.Frame(self)
        self._prev_btn = ttk.Button(
            self._pagination_frame, text="◀ Prev",
            style="Secondary.TButton",
            command=self._go_prev_page,
        )
        self._prev_btn.pack(side=tk.LEFT, padx=(8, 4), pady=4)
        self._page_label_var = tk.StringVar(value="")
        ttk.Label(
            self._pagination_frame,
            textvariable=self._page_label_var,
            foreground=C["fg_dim"],
            anchor="center",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)
        self._next_btn = ttk.Button(
            self._pagination_frame, text="Next ▶",
            style="Secondary.TButton",
            command=self._go_next_page,
        )
        self._next_btn.pack(side=tk.RIGHT, padx=(4, 8), pady=4)
        # Don't pack initially — shown on demand by _update_pagination

        # Wrap tree+scrollbar in a frame so they sit side-by-side without
        # interfering with the bottom-anchored pagination bar.
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=self.column_order,
            show="headings",
            selectmode="extended",
        )

        self._configure_columns()

        # --- Tags (later tags take priority when multiple are applied) ---
        # Colours pulled from the live palette so they update on theme switch.
        self._configure_tree_tags()

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.bind("<ButtonRelease-1>", self._save_column_widths, add="+")
        self.tree.bind("<Double-1>",        self._on_double_click)
        self.tree.bind("<Return>",          self._on_enter)
        self.tree.bind("<Control-e>",       self._on_ctrl_e)
        self.tree.bind("<Delete>",          lambda e: self.delete_selected())
        self.tree.bind("<Button-3>",        self._on_right_click)

    def _configure_tree_tags(self):
        """Apply tree row tags from the live palette.  Re-callable on theme switch."""
        self.tree.tag_configure("row_even", background=C["bg_panel"])
        self.tree.tag_configure("row_odd",  background=C["bg_alt"])
        self.tree.tag_configure(
            "bookmarked",
            background=C["bookmark_bg"], foreground=C["bookmark_fg"]
        )
        self.tree.tag_configure(
            "conflict",
            background=C["conflict_bg"], foreground=C["conflict_fg"]
        )
        self.tree.tag_configure(
            "bookmarked_conflict",
            background=C["bookmarked_conflict_bg"],
            foreground=C["bookmarked_conflict_fg"]
        )
        self.tree.tag_configure(
            "find_match",
            background=C["find_match_bg"], foreground=C["find_match_fg"]
        )

    def refresh_theme(self):
        """Re-apply colour-dependent settings after a theme switch."""
        if hasattr(self, "tree"):
            self._configure_tree_tags()
        # Filter-header count label uses fg_dim explicitly
        if hasattr(self, "count_label"):
            try:
                self.count_label.configure(foreground=C["fg_dim"])
            except (tk.TclError, AttributeError):
                pass
        # Conflict banner uses palette colours; recolour if currently shown
        if hasattr(self, "_conflict_banner_label"):
            try:
                self._conflict_banner_label.configure(
                    background=C["conflict_bg"], foreground=C["conflict_fg"])
                self._conflict_banner_close.configure(
                    background=C["conflict_bg"], foreground=C["conflict_fg"])
            except (tk.TclError, AttributeError):
                pass
        # Pagination label uses fg_dim
        if hasattr(self, "_pagination_frame"):
            try:
                for child in self._pagination_frame.winfo_children():
                    if isinstance(child, ttk.Label):
                        child.configure(foreground=C["fg_dim"])
            except (tk.TclError, AttributeError):
                pass
        self._refresh_dictionary_header()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_mode(self, edit_mode: bool):
        pass   # kept for compatibility

    def load_entries(self, entries, metadata=None):
        self.entries = entries
        self.metadata = ensure_metadata(entries, metadata or {})
        self._metadata_dirty = False
        self._rebuild_conflict_stenos()
        self._undo_stack.clear()
        self._refresh_dictionary_header()
        # Note: we don't call _apply_filters() here.  The caller almost always
        # follows up with apply_search() (main.py does), and that triggers
        # _apply_filters internally — running it twice on a 100k-entry
        # dictionary doubles the load time for no benefit.  The one path
        # that doesn't is direct test-harness usage; tests call _apply_filters
        # explicitly when they need it.
        self.filtered_entries = list(entries)

    def add_entry(self, entry):
        before = set(self.conflict_stenos)
        self.entries.append(entry)
        self._set_dirty()
        self._rebuild_conflict_stenos()
        new_conflicts = self._detect_new_conflicts(before, self.conflict_stenos)
        if new_conflicts:
            self._show_conflict_banner(new_conflicts)
        self._refresh_dictionary_header()
        self._apply_filters()

    def edit_selected_entry(self, updated_entry):
        selected = self.tree.selection()
        if not selected:
            return
        # Locate the exact entry by matching iid order to filtered_entries
        children = self.tree.get_children()
        try:
            idx = children.index(selected[0])
        except ValueError:
            return
        if idx >= len(self.filtered_entries):
            return
        target = self.filtered_entries[idx]
        old_steno = target["steno"]
        before = set(self.conflict_stenos)
        target.update(updated_entry)
        # If the steno key changed, conflicts and metadata may need adjustment
        if updated_entry.get("steno") and updated_entry["steno"] != old_steno:
            self._rebuild_conflict_stenos()
            new_conflicts = self._detect_new_conflicts(before, self.conflict_stenos)
            if new_conflicts:
                self._show_conflict_banner(new_conflicts)
        self._refresh_dictionary_header()
        self._apply_filters()

    def apply_search(self, config):
        self.search_config = config
        self._apply_filters()

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------
    def save_json(self) -> bool:
        """Write steno→english pairs back to the .json file (no metadata).

        Before writing, snapshot the existing on-disk file into the backup
        folder so the previous version is recoverable if this save turns
        out to be wrong.
        """
        if not self.dict_path:
            return False

        # Pre-save backup.  If it fails, ask the user whether to proceed -
        # they may not want to overwrite a known-good file when the safety
        # net is unavailable.
        try:
            from logic.backup_store import backup_dictionary
            ok, msg = backup_dictionary(self.dict_path, kind="save")
        except Exception as e:
            ok, msg = False, str(e)

        if not ok:
            proceed = messagebox.askyesno(
                "Backup Failed",
                f"Could not write a backup of "
                f"{os.path.basename(self.dict_path)}:\n\n{msg}\n\n"
                f"Save anyway?",
            )
            if not proceed:
                return False

        # Preserve duplicate steno keys by writing object members manually
        # rather than collapsing into a Python dict.
        pieces = []
        for entry in self.entries:
            k = json.dumps(entry["steno"], ensure_ascii=False)
            v = json.dumps(entry["english"], ensure_ascii=False)
            pieces.append(f"  {k}: {v}")
        serialized = "{\n" + ",\n".join(pieces) + "\n}" if pieces else "{}"

        try:
            with open(self.dict_path, "w", encoding="utf-8") as f:
                f.write(serialized)
            self._set_dirty(False)
            self._undo_stack.mark_saved()
            return True
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save dictionary:\n{e}")
            return False

    # ------------------------------------------------------------------
    # Bookmarks (session-only)
    # ------------------------------------------------------------------
    def toggle_bookmark_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        stenos = self._stenos_for_items(selected)
        all_bm = all(s in self.bookmarked_stenos for s in stenos)
        if all_bm:
            self.bookmarked_stenos -= stenos
        else:
            self.bookmarked_stenos |= stenos
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete_selected(self, confirm=True):
        selected = self.tree.selection()
        if not selected:
            return
        if confirm:
            n     = len(selected)
            label = (f'"{dict(zip(self.column_order, self.tree.item(selected[0], "values")))["steno"]}"'
                     if n == 1 else f"{n} selected entries")
            if not messagebox.askyesno("Delete", f"Delete {label}?"):
                return

        # Identify entries by Python object identity rather than by
        # (steno, english) pair.  When two entries genuinely share the
        # same steno+english (a literal duplicate), pair-based identity
        # can't tell which row the user actually clicked.  iid order
        # matches filtered_entries order at insert time, so we walk the
        # tree once to map iid -> entry, then build a set of entries
        # to delete by id().
        children = self.tree.get_children()
        iid_to_entry = {iid: entry
                        for iid, entry in zip(children, self.filtered_entries)}

        targets = set()
        for iid in selected:
            entry = iid_to_entry.get(iid)
            if entry is not None:
                targets.add(id(entry))

        if not targets:
            return

        # ── Capture undo frame before mutating ─────────────────────────
        # Keep the original entry objects (not copies) so undo can
        # re-insert them by identity, and redo can remove them by identity.
        entries_to_delete = [e for e in self.entries if id(e) in targets]
        positions         = [i for i, e in enumerate(self.entries) if id(e) in targets]
        meta_snap         = {
            e["steno"]: copy.deepcopy((self.metadata or {}).get(e["steno"], {}))
            for e in entries_to_delete
        }
        n = len(entries_to_delete)
        self._undo_stack.push({
            "op":      "delete",
            "label":   "Delete Entry" if n == 1 else f"Delete {n} Entries",
            "entries": list(zip(entries_to_delete, positions)),  # [(ref, pos), …]
            "meta":    meta_snap,
        })
        # ───────────────────────────────────────────────────────────────

        new_entries = [e for e in self.entries if id(e) not in targets]

        # Recompute which stenos disappeared entirely so we can clean up
        # bookmarks and metadata for them.  A steno might still be present
        # in new_entries via another row sharing the same key.
        old_stenos = {e["steno"] for e in self.entries}
        new_stenos = {e["steno"] for e in new_entries}
        removed_stenos = old_stenos - new_stenos
        for s in removed_stenos:
            self.bookmarked_stenos.discard(s)
            if self.metadata:
                self.metadata.pop(s, None)

        # Recompute conflicts: a steno is no longer in conflict if it now
        # appears 0 or 1 times.
        steno_counts: dict = {}
        for e in new_entries:
            steno_counts[e["steno"]] = steno_counts.get(e["steno"], 0) + 1
        for s in list(self.conflict_stenos):
            if steno_counts.get(s, 0) <= 1:
                self.conflict_stenos.discard(s)

        self.entries = new_entries
        self._set_dirty()
        self._refresh_dictionary_header()
        self._apply_filters()
        if self.on_entries_changed:
            self.on_entries_changed(len(self.entries))

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------
    def _push_undo_frame(self, frame: dict) -> None:
        """Push a frame onto the undo stack and update the dirty flag."""
        self._undo_stack.push(frame)
        self._set_dirty(True)

    def undo(self) -> None:
        """Reverse the most recent undoable operation."""
        frame = self._undo_stack.pop_undo()
        if frame is None:
            return
        self._apply_undo_redo_frame(frame, direction="undo")

    def redo(self) -> None:
        """Replay the most recently undone operation."""
        frame = self._undo_stack.pop_redo()
        if frame is None:
            return
        self._apply_undo_redo_frame(frame, direction="redo")

    def _apply_undo_redo_frame(self, frame: dict, direction: str) -> None:
        op = frame["op"]

        if op == "add":
            if direction == "undo":
                # Remove the added entry by object identity
                ref = frame["entry_ref"]
                self.entries = [e for e in self.entries if e is not ref]
                if self.metadata is not None:
                    self.metadata.pop(frame["steno"], None)
            else:  # redo
                self.entries.append(frame["entry_ref"])
                if self.metadata is not None:
                    self.metadata[frame["steno"]] = copy.deepcopy(frame["meta"])

        elif op == "edit":
            ref = frame["entry_ref"]
            if direction == "undo":
                restore_values = frame["old_values"]
                restore_meta_key = frame["old_meta_key"]
                restore_meta = frame["old_meta"]
                remove_meta_key = frame["new_meta_key"]
            else:  # redo
                restore_values = frame["new_values"]
                restore_meta_key = frame["new_meta_key"]
                restore_meta = frame["new_meta"]
                remove_meta_key = frame["old_meta_key"]

            # Restore the entry dict in-place (ref is still in self.entries)
            ref.clear()
            ref.update(restore_values)

            # Fix metadata: remove the key we're moving away from (if it changed)
            if self.metadata is not None:
                if remove_meta_key != restore_meta_key:
                    self.metadata.pop(remove_meta_key, None)
                self.metadata[restore_meta_key] = copy.deepcopy(restore_meta)

        elif op == "delete":
            if direction == "undo":
                # Re-insert original entry objects at their recorded positions.
                # Sort ascending so earlier insertions don't shift later ones.
                for ref, pos in sorted(frame["entries"], key=lambda x: x[1]):
                    pos = min(pos, len(self.entries))
                    self.entries.insert(pos, ref)
                    steno = ref["steno"]
                    if self.metadata is not None and steno in frame["meta"]:
                        self.metadata[steno] = copy.deepcopy(frame["meta"][steno])
            else:  # redo
                targets = {id(ref) for ref, _ in frame["entries"]}
                new_entries = [e for e in self.entries if id(e) not in targets]
                # Clean up metadata for stenos no longer present
                new_stenos = {e["steno"] for e in new_entries}
                if self.metadata is not None:
                    for ref, _ in frame["entries"]:
                        if ref["steno"] not in new_stenos:
                            self.metadata.pop(ref["steno"], None)
                self.entries = new_entries

        self._rebuild_conflict_stenos()
        self._apply_filters()
        self._set_dirty(self._undo_stack.is_dirty)
        self._refresh_dictionary_header()
        if self.on_entries_changed:
            self.on_entries_changed(len(self.entries))

    # ------------------------------------------------------------------
    # Cross-dictionary receive (copy / move)
    # ------------------------------------------------------------------
    def receive_entries(self, entries_with_meta):
        before = set(self.conflict_stenos)
        for entry, meta in entries_with_meta:
            steno = entry["steno"]
            self.entries.append(dict(entry))
            if self.metadata is not None and steno not in self.metadata:
                self.metadata[steno] = dict(meta) if meta else {}
        self._set_dirty()
        self._rebuild_conflict_stenos()
        new_conflicts = self._detect_new_conflicts(before, self.conflict_stenos)
        if new_conflicts:
            self._show_conflict_banner(new_conflicts)
        self._refresh_dictionary_header()
        self._apply_filters()
        if self.on_entries_changed:
            self.on_entries_changed(len(self.entries))

    # ------------------------------------------------------------------
    # Right-click context menu
    # ------------------------------------------------------------------
    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item not in self.tree.selection():
            self.tree.selection_set(item)
        selected = self.tree.selection()
        n = len(selected)

        menu = tk.Menu(self, tearoff=0)
        if n == 1:
            menu.add_command(label="Edit Entry", command=self._open_edit_dialog_for_selected)
            menu.add_separator()
        menu.add_command(
            label=f"Delete {'entry' if n == 1 else f'{n} entries'}",
            command=self.delete_selected,
        )
        menu.add_separator()
        menu.add_command(label="Toggle Bookmark ★", command=self.toggle_bookmark_selected)

        other = self._get_other_tabs()
        if other:
            menu.add_separator()
            cm = tk.Menu(menu, tearoff=0)
            mm = tk.Menu(menu, tearoff=0)
            for tname, tab in other.items():
                cm.add_command(label=tname, command=lambda t=tab: self._copy_selected_to(t))
                mm.add_command(label=tname, command=lambda t=tab: self._move_selected_to(t))
            menu.add_cascade(label="Copy to →", menu=cm)
            menu.add_cascade(label="Move to →", menu=mm)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_other_tabs(self) -> dict:
        app = self.winfo_toplevel()
        if not hasattr(app, "tabs"):
            return {}
        return {n: t for n, t in app.tabs.items() if t is not self}

    def _copy_selected_to(self, target_tab):
        payload = []
        children = self.tree.get_children()
        iid_to_entry = {iid: entry for iid, entry in zip(children, self.filtered_entries)}
        for item in self.tree.selection():
            entry = iid_to_entry.get(item)
            if entry:
                payload.append((entry, (self.metadata or {}).get(entry["steno"], {})))
        target_tab.receive_entries(payload)

    def _move_selected_to(self, target_tab):
        self._copy_selected_to(target_tab)
        self.delete_selected(confirm=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _stenos_for_items(self, items) -> set:
        return {
            dict(zip(self.column_order, self.tree.item(i, "values")))["steno"]
            for i in items
        }

    # ------------------------------------------------------------------
    # Selection handlers
    # ------------------------------------------------------------------
    def _on_click(self, event=None):
        if self.tree.identify("region", event.x, event.y) == "heading":
            return

    def _on_double_click(self, event=None): self._open_edit_dialog_for_selected()
    def _on_enter(self,        event=None): self._open_edit_dialog_for_selected()
    def _on_ctrl_e(self,       event=None): self._open_edit_dialog_for_selected()
    def toolbar_edit(self):                 self._open_edit_dialog_for_selected()

    # ------------------------------------------------------------------
    # Filters + search
    # ------------------------------------------------------------------
    def _apply_filters(self):
        """
        Walk self.entries and produce self.filtered_entries.

        With 100k+ entry dictionaries this is the hot path on every keystroke,
        so the loop is structured to do the minimum work per row:
        - Tk variable values are pulled once before the loop, not 100k times.
        - Per-entry work is gated on whether the relevant filter is active,
          so an unfiltered open-the-dictionary case skips lower(), metadata
          lookups, and regex compilation entirely.
        - Punctuation regex is compiled once and cached on the class.
        """
        # Guard: this may be called via StringVar trace during __init__ before
        # the Treeview is built.  Nothing to do yet in that case.
        if not hasattr(self, "tree"):
            return

        cfg = getattr(self, "search_config", {}) or {}
        steno_q       = cfg.get("steno_query", "").strip()
        steno_method  = cfg.get("steno_method", "Contains")
        whole_strokes = cfg.get("steno_whole_strokes", False)
        match_case    = cfg.get("text_match_case", False)
        text_q_raw    = cfg.get("text_query", "").strip()
        text_q        = text_q_raw if match_case else text_q_raw.lower()
        text_method   = cfg.get("text_method", "Begins With")

        steno_active = bool(steno_q)
        text_active  = bool(text_q)

        # Hoist tk var reads - one Tk call instead of 101k
        f_comments    = self.filter_has_comments.get()
        f_brief       = self.filter_is_brief.get()
        f_bookmarked  = self.filter_bookmarked.get()
        f_capitalised = self.filter_capitalised.get()
        f_digits      = self.filter_has_digits.get()
        f_written     = self.filter_has_written_numbers.get()
        f_punct       = self.filter_has_punctuation.get()
        f_conflict    = self.filter_conflicts.get()
        f_has_freq    = self.filter_has_frequency.get()
        f_top_freq    = self.filter_top_freq.get()

        any_meta_filter = f_comments or f_brief or f_has_freq
        any_filter      = (f_comments or f_brief or f_bookmarked or
                           f_capitalised or f_digits or f_written or
                           f_punct or f_conflict or f_has_freq or f_top_freq)

        # Local refs - faster lookup than self.X in the loop.
        # metadata must be assigned before the f_top_freq block below, which
        # needs it to compute the ranked steno set.
        metadata          = self.metadata or {}
        bookmarked_stenos = self.bookmarked_stenos
        conflict_stenos   = self.conflict_stenos
        steno_matches     = self._steno_matches
        text_matches      = self._text_matches
        digit_re          = _DIGIT_RE
        punct_re          = _PUNCT_RE
        word_re           = _WORD_RE
        written_numbers   = WRITTEN_NUMBERS

        # Pre-compute the top-N steno set when that filter is active.
        # Done once here — outside the per-entry loop — so the hot path
        # only does a fast set-membership test per row.
        if f_top_freq:
            try:
                top_n = max(1, int(self.filter_top_freq_n_var.get()))
            except (ValueError, TypeError):
                top_n = 500
            scored = sorted(
                (
                    (e["steno"], (metadata.get(e["steno"]) or {}).get("frequency", 0))
                    for e in self.entries
                ),
                key=lambda x: x[1],
                reverse=True,
            )
            # Entries with score 0 are never included regardless of N
            top_n_stenos = {steno for steno, score in scored[:top_n] if score > 0}
        else:
            top_n_stenos = None

        # Any filter change goes back to the first page.
        self._page = 0

        results = []
        for entry in self.entries:
            steno   = entry["steno"]
            # Guard against null English values (used in some steno dictionaries
            # as stroke suppressors).  Treat them as empty strings throughout.
            english = entry["english"] or ""

            # Steno axis
            if steno_active and not steno_matches(
                steno, steno_q, steno_method, whole_strokes
            ):
                continue

            # The text axis can run case-sensitively or not.  The lowered
            # form is also used by the written-numbers filter, so we may
            # need it even when match_case is on for the text search.
            need_lower = (text_active and not match_case) or f_written
            english_lower = english.lower() if need_lower else None

            # Text axis
            if text_active:
                haystack = english.strip() if match_case else english_lower.strip()
                if not text_matches(haystack, text_q, text_method):
                    continue

            # Predicate filters
            if any_filter:
                # Metadata-based predicates only fetch metadata if needed
                if any_meta_filter:
                    meta = metadata.get(steno, {})
                    if f_comments and not meta.get("comments", "").strip():
                        continue
                    if f_brief and not meta.get("brief", False):
                        continue
                    if f_has_freq and not meta.get("frequency", 0):
                        continue

                if f_bookmarked and steno not in bookmarked_stenos:
                    continue
                if f_capitalised and not (english and english[0].isupper()):
                    continue
                if f_digits and not digit_re.search(english):
                    continue
                if f_written:
                    if not (set(word_re.findall(english_lower)) & written_numbers):
                        continue
                if f_punct and not punct_re.search(english):
                    continue
                if f_conflict and steno not in conflict_stenos:
                    continue
                if f_top_freq and steno not in top_n_stenos:
                    continue

            results.append(entry)

        self.filtered_entries = results

        # Update entry count label - colour it to draw attention when a search
        # yields zero matches, otherwise keep the muted colour.
        total   = len(self.entries)
        showing = len(results)
        search_active = steno_active or text_active

        if showing < total:
            self.count_label.config(text=f"{showing:,} of {total:,} entries")
        else:
            self.count_label.config(text=f"{total:,} entries")

        if search_active and showing == 0:
            self.count_label.config(foreground=C["conflict_fg"])
        else:
            self.count_label.config(foreground=C["fg_dim"])

        # Notify owner of result count - lets main.py show "0 matches" hint
        if callable(getattr(self, "_on_filter_count_changed", None)):
            try:
                self._on_filter_count_changed(showing, total,
                                              search_active=search_active)
            except Exception:
                pass

        if self.sort_column:
            self._sort_by(self.sort_column, remember=False)
        else:
            self._refresh_tree()

    def _text_matches(self, english_lower: str, query: str, method: str) -> bool:
        """Match the English translation against the query using the given method."""
        if method == "Contains":    return query in english_lower
        if method == "Begins With": return english_lower.startswith(query)
        if method == "Ends With":   return english_lower.endswith(query)
        return False

    def _steno_matches(self, steno_value: str, query: str,
                       method: str, whole_strokes_only: bool) -> bool:
        """
        Match a steno entry against the query.

        Free-form mode (whole_strokes_only=False): treat steno as a single
        string and apply contains/starts/ends to its full text.

        Whole-strokes mode: split both steno and query on '/' and require
        the query strokes to appear at the right position as complete strokes.
        Example: query 'AL' with method 'Ends With' matches 'TPORPL/AL' but
        not 'TPAL' (which contains AL only as a substring of one stroke).
        """
        sv = steno_value.upper().strip()
        q  = query.upper().strip()

        if not whole_strokes_only:
            if method == "Contains":    return q in sv
            if method == "Begins With": return sv.startswith(q)
            if method == "Ends With":   return sv.endswith(q)
            return False

        strokes   = sv.split("/")
        q_strokes = q.split("/")
        n         = len(q_strokes)
        if n == 0 or n > len(strokes):
            return False

        if method == "Contains":
            for i in range(len(strokes) - n + 1):
                if strokes[i:i + n] == q_strokes:
                    return True
            return False
        if method == "Begins With":
            return strokes[:n] == q_strokes
        if method == "Ends With":
            return strokes[-n:] == q_strokes
        return False

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------
    def _sort_by(self, column, remember=True):
        if self.sort_column == column and remember:
            self.sort_reverse = not self.sort_reverse
        elif remember:
            self.sort_column  = column
            self.sort_reverse = False

        def key(entry):
            if column == "S": return entry["steno"].count("/") + 1
            if column == "W": return len((entry.get("english") or "").split())
            if column == "F": return (self.metadata or {}).get(entry["steno"], {}).get("frequency", 0)
            if column == "B":
                return 1 if (self.metadata or {}).get(entry["steno"], {}).get("brief") else 0
            if column in ("added", "modified", "comments"):
                meta = (self.metadata or {}).get(entry["steno"], {})
                k    = "date_added" if column == "added" else column
                return meta.get(k, "").lower()
            v = entry.get(column, "") or ""
            return v.lower() if isinstance(v, str) else v

        self.filtered_entries.sort(key=key, reverse=self.sort_reverse)
        self._refresh_tree()
        self._update_sort_headings()

    def _update_sort_headings(self):
        for col in self.column_order:
            base = self.HEADINGS[col]
            text = (f"{base} {'▼' if self.sort_reverse else '▲'}"
                    if col == self.sort_column else base)
            self.tree.heading(col, text=text, command=lambda c=col: self._sort_by(c))

    # ------------------------------------------------------------------
    # Tree refresh (zebra stripes + tags)
    # ------------------------------------------------------------------
    def _refresh_tree(self):
        """
        Rebuild the visible tree from self.filtered_entries.

        Two performance properties:
        - Caps inserted rows at MAX_DISPLAY_ROWS (most users find their
          target by searching, not scrolling, so the cap is rarely visible).
        - Per-row work is kept tight: column order and metadata lookups are
          hoisted out of the loop, dict-comprehension row construction is
          replaced with a positional list build.
        """
        prev_selected = self._stenos_for_items(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        to_reselect = []

        # Hoist out everything that doesn't change row-to-row
        column_order      = self.column_order
        metadata          = self.metadata or {}
        bookmarked_stenos = self.bookmarked_stenos
        conflict_stenos   = self.conflict_stenos
        max_chars         = MAX_COMMENT_CHARS

        # Clamp the page to the valid range in case filtered_entries shrank
        # (e.g. after a search that returns fewer results than the current page).
        max_page = max(0, (len(self.filtered_entries) - 1) // MAX_DISPLAY_ROWS)
        self._page = min(self._page, max_page)

        # Slice once so the loop has clean bounds
        start  = self._page * MAX_DISPLAY_ROWS
        capped = self.filtered_entries[start:start + MAX_DISPLAY_ROWS]

        for i, entry in enumerate(capped):
            steno   = entry["steno"]
            english = entry.get("english") or ""
            meta    = metadata.get(steno, {})

            added    = meta.get("date_added", entry.get("date_added", ""))
            modified = meta.get("modified",   entry.get("modified",   ""))
            comments = meta.get("comments", "")
            if len(comments) > max_chars:
                comments = comments[:max_chars - 3] + "..."

            B = "✓" if meta.get("brief", False) else ""
            S = steno.count("/") + 1
            W = len(english.split())
            freq = meta.get("frequency", 0)
            F = freq if freq else ""   # show empty instead of 0

            values_by_col = {
                "steno":    steno,
                "english":  english,
                "S":        S,
                "W":        W,
                "B":        B,
                "F":        F,
                "added":    added,
                "modified": modified,
                "comments": comments,
            }
            row = [values_by_col[c] for c in column_order]

            # Build tag list — later tags override earlier ones
            tags = ["row_odd" if i & 1 else "row_even"]
            is_bm = steno in bookmarked_stenos
            is_cx = steno in conflict_stenos
            if   is_bm and is_cx: tags.append("bookmarked_conflict")
            elif is_bm:           tags.append("bookmarked")
            elif is_cx:           tags.append("conflict")

            iid = self.tree.insert("", tk.END, values=row, tags=tags)
            if steno in prev_selected:
                to_reselect.append(iid)

        if to_reselect:
            self.tree.selection_set(to_reselect)

        # Update the pagination bar
        self._update_pagination()

    # ------------------------------------------------------------------
    # Conflict warning banner
    # ------------------------------------------------------------------
    def _show_conflict_banner(self, new_conflict_stenos):
        """
        Display a non-blocking warning above the tree when add/edit/receive
        creates one or more new conflicts.  Auto-ticks the Conflicts filter
        so the user can immediately see which rows are involved.
        """
        if not new_conflict_stenos:
            return

        n = len(new_conflict_stenos)
        if n == 1:
            steno = next(iter(new_conflict_stenos))
            text = (f"Conflict: \"{steno}\" now has multiple translations. "
                    f"The Conflicts filter has been turned on so you can review.")
        else:
            text = (f"{n} new conflicts created. "
                    f"The Conflicts filter has been turned on so you can review.")

        self._conflict_banner_label.config(
            text=text,
            background=C["conflict_bg"],
            foreground=C["conflict_fg"],
        )
        self._conflict_banner_close.config(
            background=C["conflict_bg"],
            foreground=C["conflict_fg"],
        )
        # Apply background to the frame itself via style
        try:
            self._conflict_banner.configure(style="Conflict.TFrame")
        except tk.TclError:
            pass

        self._conflict_banner.pack(fill=tk.X, side=tk.TOP, padx=2, pady=(0, 2))

        # Auto-toggle the Conflicts filter on
        if not self.filter_conflicts.get():
            self.filter_conflicts.set(True)  # triggers _apply_filters via trace

    def _hide_conflict_banner(self):
        try:
            self._conflict_banner.pack_forget()
        except tk.TclError:
            pass

    def _detect_new_conflicts(self, before: set, after: set) -> set:
        """Return the set of stenos that became conflicts since 'before'."""
        return after - before

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------
    def _go_prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._refresh_tree()

    def _go_next_page(self):
        max_page = max(0, (len(self.filtered_entries) - 1) // MAX_DISPLAY_ROWS)
        if self._page < max_page:
            self._page += 1
            self._refresh_tree()

    def _update_pagination(self):
        """Show/hide the pagination bar and update its label and button states."""
        total = len(self.filtered_entries)
        if total <= MAX_DISPLAY_ROWS:
            self._pagination_frame.pack_forget()
            return

        max_page = (total - 1) // MAX_DISPLAY_ROWS
        start    = self._page * MAX_DISPLAY_ROWS + 1
        end      = min(start + MAX_DISPLAY_ROWS - 1, total)
        self._page_label_var.set(f"Showing {start:,}–{end:,} of {total:,}")
        self._prev_btn.configure(state="normal" if self._page > 0        else "disabled")
        self._next_btn.configure(state="normal" if self._page < max_page else "disabled")

        if not self._pagination_frame.winfo_ismapped():
            self._pagination_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))

    # ------------------------------------------------------------------
    # Column width persistence
    # ------------------------------------------------------------------
    def _save_column_widths(self, event=None):
        # Only persist widths when the user drags a column sash (separator).
        # Firing on every row click was causing load_settings + save_settings
        # to run on each click, which is wasteful.
        if event is not None:
            region = self.tree.identify("region", event.x, event.y)
            if region != "separator":
                return
        self.after(50, self._do_save_column_widths)

    def _do_save_column_widths(self):
        try:
            for col in self.column_order:
                self.column_widths[col] = self.tree.column(col, "width")
        except Exception:
            return
        settings = load_settings()
        settings["column_widths"] = self.column_widths
        save_settings(settings)
        self.settings = settings

    # ------------------------------------------------------------------
    # Details dialog
    # ------------------------------------------------------------------
    def _open_details_dialog_for_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        row    = dict(zip(self.column_order, self.tree.item(selected[0], "values")))
        steno  = row["steno"]
        english = row["english"]
        entry  = next(
            (e for e in self.entries if e["steno"] == steno and e["english"] == english),
            None,
        )
        if entry is None:
            return

        dlg = tk.Toplevel(self)
        dlg.title("Entry Details")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        _style_dialog(dlg)

        con = ttk.Frame(dlg, padding=12)
        con.pack(fill=tk.BOTH, expand=True)
        ttk.Label(con, text="Entry Details", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        meta = (self.metadata or {}).get(steno, {})

        def add_row(r, lbl, val):
            ttk.Label(con, text=lbl+":", font=("Segoe UI", 9, "bold")).grid(
                row=r, column=0, sticky="ne", padx=(0, 8), pady=2)
            ttk.Label(con, text=val, wraplength=320, justify="left").grid(
                row=r, column=1, sticky="nw", pady=2)

        r = 1
        add_row(r, "Steno",       steno);                                           r += 1
        add_row(r, "Translation", english);                                         r += 1
        add_row(r, "Added",       meta.get("date_added", entry.get("date_added",""))); r += 1
        add_row(r, "Modified",    meta.get("modified",   entry.get("modified",""))); r += 1
        add_row(r, "Brief",       "Yes" if meta.get("brief") else "No");            r += 1
        add_row(r, "Bookmarked",  "★ Yes" if steno in self.bookmarked_stenos else "No"); r += 1

        ttk.Label(con, text="Comments:", font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky="ne", padx=(0, 8), pady=(8, 2))
        ct = tk.Text(con, height=6, wrap="word", state="normal",
                     borderwidth=1, relief="solid", font=("Segoe UI", 9))
        ct.grid(row=r, column=1, sticky="nsew", pady=(8, 2))
        ct.insert("1.0", meta.get("comments", ""))
        ct.config(state="disabled")
        con.rowconfigure(r, weight=1)
        con.columnconfigure(1, weight=1)

        ttk.Button(con, text="Close", command=dlg.destroy).grid(
            row=r+1, column=0, columnspan=2, pady=(10, 0))
        dlg.update_idletasks()
        center_on_parent(dlg, self.winfo_toplevel())

    # ------------------------------------------------------------------
    # Edit / Add dialog
    # ------------------------------------------------------------------
    def _open_edit_dialog_for_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        children = self.tree.get_children()
        try:
            idx = children.index(selected[0])
        except ValueError:
            return
        if idx >= len(self.filtered_entries):
            return
        self._open_edit_dialog(self.filtered_entries[idx])

    def _open_add_dialog(self):
        self._open_edit_dialog({
            "steno": "", "english": "",
            "date_added": datetime.now().strftime("%Y-%m-%d"),
            "modified":   datetime.now().strftime("%Y-%m-%d"),
            "brief": False, "comments": "",
        }, is_new=True)

    def _open_edit_dialog(self, entry, is_new=False):
        dlg = tk.Toplevel(self)
        dlg.title("Add Entry" if is_new else "Edit Entry")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        _style_dialog(dlg)

        con = ttk.Frame(dlg, padding=12)
        con.pack(fill=tk.BOTH, expand=True)

        ttk.Label(con, text="Add Entry" if is_new else "Edit Entry",
                  font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(con, text="Steno:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        steno_var   = tk.StringVar(value=entry.get("steno", ""))
        steno_entry = ttk.Entry(con, textvariable=steno_var, width=40)
        steno_entry.grid(row=1, column=1, sticky="w", pady=4)

        # Validation message slot just under the steno field.  Hidden until
        # validation fails on save attempt - we don't validate as the user
        # types because briefs are entered key-by-key and would flicker
        # errors mid-word.  When validation fails, both an inline message
        # and a red border on the field draw the eye to the problem.
        steno_error_var = tk.StringVar(value="")
        steno_error = ttk.Label(
            con, textvariable=steno_error_var,
            foreground=C["conflict_fg"], wraplength=320,
            font=("Segoe UI", 9, "bold"),
        )
        steno_error.grid(row=2, column=1, sticky="w", pady=(0, 2))

        # An invalid-state style for the entry that tints the border red.
        # Style is keyed off the standard 'invalid' state so we can flip it
        # by setting/clearing that state on the entry.
        style = ttk.Style()
        style.map(
            "Invalid.TEntry",
            fieldbackground=[("invalid", C["bg_input"])],
            bordercolor=[("invalid", C["conflict_fg"])],
            lightcolor=[("invalid", C["conflict_fg"])],
            darkcolor=[("invalid", C["conflict_fg"])],
        )
        steno_entry.configure(style="Invalid.TEntry")

        # Clear the error state as soon as the user edits the field, so
        # they see immediate feedback that they're addressing the problem.
        # Also auto-uppercase steno - it's conventional and saves the user
        # reaching for Caps Lock or holding Shift while typing every key.
        upcasing = {"flag": False}
        def on_steno_edit(*_):
            if steno_error_var.get():
                steno_error_var.set("")
                steno_entry.state(["!invalid"])
            # Auto-uppercase, guarded against the recursive trace fire
            if upcasing["flag"]:
                return
            current = steno_var.get()
            upper   = current.upper()
            if upper != current:
                upcasing["flag"] = True
                try:
                    # Preserve the cursor position - .set() resets it to 0
                    cursor = steno_entry.index(tk.INSERT)
                    steno_var.set(upper)
                    steno_entry.icursor(cursor)
                finally:
                    upcasing["flag"] = False
        steno_var.trace_add("write", on_steno_edit)

        ttk.Label(con, text="Translation:").grid(row=3, column=0, sticky="e", padx=(0, 8), pady=4)
        english_var = tk.StringVar(value=entry.get("english") or "")
        ttk.Entry(con, textvariable=english_var, width=40).grid(row=3, column=1, sticky="w", pady=4)

        edit_meta = (self.metadata or {}).get(entry.get("steno", ""), {})
        brief_var  = tk.BooleanVar(value=edit_meta.get("brief", entry.get("brief", False)))
        ttk.Checkbutton(con, text="Brief outline", variable=brief_var).grid(
            row=4, column=1, sticky="w", pady=(4, 4))

        ttk.Label(con, text="Comments:").grid(row=5, column=0, sticky="ne", padx=(0, 8), pady=(4, 2))
        cf = ttk.Frame(con)
        cf.grid(row=5, column=1, sticky="nsew", pady=(4, 2))
        ct = tk.Text(cf, height=4, wrap="word", borderwidth=1, relief="solid", font=("Segoe UI", 9))
        ct.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        csb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=ct.yview)
        csb.pack(side=tk.RIGHT, fill=tk.Y)
        ct.configure(yscrollcommand=csb.set)
        ct.insert("1.0", edit_meta.get("comments", entry.get("comments", "")))

        con.rowconfigure(5, weight=1)
        con.columnconfigure(1, weight=1)

        bf = ttk.Frame(con)
        bf.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="e")

        def on_save():
            # Validate steno before doing anything destructive.  Show error
            # inline (with a red border on the field) and abort save if invalid.
            from logic.steno_validator import validate_steno
            steno_input = steno_var.get().strip()
            ok, msg = validate_steno(steno_input)
            if not ok:
                steno_error_var.set(msg)
                steno_entry.state(["invalid"])
                steno_entry.focus_set()
                return
            steno_error_var.set("")
            steno_entry.state(["!invalid"])

            updated = dict(entry)
            updated["steno"]    = steno_input
            updated["english"]  = english_var.get().strip()
            updated["brief"]    = brief_var.get()
            updated["comments"] = ct.get("1.0", "end-1c").strip()
            updated["modified"] = datetime.now().strftime("%Y-%m-%d")

            if is_new:
                self.add_entry(updated)
                new_meta = {
                    "date_added": updated.get("date_added", updated["modified"]),
                    "modified":   updated["modified"],
                    "brief":      updated["brief"],
                    "comments":   updated["comments"],
                    "bookmarked": False,
                    "frequency":  0,
                }
                if self.metadata is not None:
                    self.metadata[updated["steno"]] = new_meta
                # Push undo frame: entry_ref is the object just appended
                self._push_undo_frame({
                    "op":        "add",
                    "label":     "Add Entry",
                    "entry_ref": self.entries[-1],
                    "steno":     updated["steno"],
                    "meta":      copy.deepcopy(new_meta),
                })
            else:
                orig_steno  = entry["steno"]
                old_values  = dict(entry)         # snapshot before edit
                old_meta    = copy.deepcopy((self.metadata or {}).get(orig_steno, {}))

                self.edit_selected_entry(updated)

                if self.metadata is not None:
                    if updated["steno"] != orig_steno:
                        self.metadata.pop(orig_steno, None)
                        self.bookmarked_stenos.discard(orig_steno)
                    self.metadata[updated["steno"]] = {
                        "date_added": old_meta.get("date_added", entry.get("date_added", "")),
                        "modified":   updated["modified"],
                        "brief":      updated["brief"],
                        "comments":   updated["comments"],
                        "bookmarked": old_meta.get("bookmarked", False),
                        "frequency":  old_meta.get("frequency", 0),
                    }
                new_meta = copy.deepcopy((self.metadata or {}).get(updated["steno"], {}))
                # Push undo frame: entry is the dict that was mutated in-place
                self._push_undo_frame({
                    "op":          "edit",
                    "label":       "Edit Entry",
                    "entry_ref":   entry,
                    "old_values":  old_values,
                    "new_values":  dict(entry),   # entry was mutated in-place
                    "old_meta_key": orig_steno,
                    "new_meta_key": updated["steno"],
                    "old_meta":    old_meta,
                    "new_meta":    new_meta,
                })

            self._metadata_dirty = True
            if self.dict_path and self.metadata is not None:
                try:
                    save_metadata(self.dict_path, self.metadata)
                    self._metadata_dirty = False
                except Exception as e:
                    messagebox.showerror(
                        "Metadata Save Error",
                        f"Failed to save entry metadata:\n{e}",
                    )

            self._rebuild_conflict_stenos()
            self._refresh_dictionary_header()
            self._apply_filters()
            if self.on_entries_changed:
                self.on_entries_changed(len(self.entries))
            dlg.destroy()

        ttk.Button(bf, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(bf, text="Save",   command=on_save).pack(side=tk.RIGHT)

        dlg.update_idletasks()
        center_on_parent(dlg, self.winfo_toplevel())
        steno_entry.focus_set()
