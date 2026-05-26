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
from ui.searchbar import SearchBar
from ui.theme import C
from ui.tooltip import Tooltip, TreeHeadingTooltip


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

    # Hover help for the cryptic single-letter columns.  Shown as a tooltip
    # whenever the user pauses over the column heading.
    COLUMN_TOOLTIPS = {
        "steno":    "Steno outline (key)",
        "english":  "Translation / output text",
        "S":        "Stroke count (number of '/' separated strokes)",
        "W":        "Word count in the translation",
        "B":        "Brief: ✓ if this outline is marked as a brief",
        "F":        "Frequency score for this word (higher = more common)",
        "added":    "Date this entry was first added",
        "modified": "Date this entry was last modified",
        "comments": "Notes you've added to this entry",
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
    FOCUS_COLUMNS = ["steno", "english", "B"]
    EDIT_COLUMNS = ["steno", "english", "S", "W", "B", "added", "modified", "comments"]

    def __init__(self, parent, name="Dictionary",
                 on_entries_changed=None,
                 on_filter_count_changed=None,
                 on_search_broadcast=None,
                 on_search_collapse_changed=None,
                 initial_search_collapsed=True):
        super().__init__(parent)
        self.name = name
        self.on_entries_changed   = on_entries_changed
        self._on_filter_count_changed = on_filter_count_changed
        self._on_search_broadcast = on_search_broadcast
        self._on_search_collapse_changed = on_search_collapse_changed
        self._initial_search_collapsed = bool(initial_search_collapsed)

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
        self.focus_mode = tk.BooleanVar(value=False)

        # Build the active column order, inserting F when the toggle is on
        self.column_order = self._make_column_order(show_freq, self.focus_mode.get())

        # Unified Search & Filters bar state.  Default collapsed so the
        # table gets maximum vertical space; the user can expand it when
        # they need to refine results.
        self.unified_expanded      = not bool(initial_search_collapsed)
        self.unified_content_height = 0

        self.search_config = {}

        # Build — note the dictionary info bar is no longer drawn as a
        # permanent block above the table.  Its information lives in the
        # right-hand cluster of the unified bar (entry count + ⓘ popover).
        self._build_search_filter_panel()
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
    def _make_column_order(cls, show_freq: bool, focus_mode: bool = False) -> list:
        """Return the active column list, inserting F after B when requested."""
        cols = list(cls.FOCUS_COLUMNS if focus_mode else cls.EDIT_COLUMNS)
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
        self.column_order = self._make_column_order(show, self.focus_mode.get())
        self._configure_columns()
        self._configure_tree_tags()
        self._update_sort_headings()
        self._refresh_tree()

    def _toggle_focus_mode(self):
        """Switch between the full editing table and a compact daily-editing view."""
        self.column_order = self._make_column_order(
            self.show_freq_column.get(), self.focus_mode.get()
        )
        self._configure_columns()
        self._update_sort_headings()
        self._refresh_tree()
        self._refresh_dictionary_header()

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
            # A leading bullet reads as "modified" more clearly than a
            # trailing asterisk and is the convention most editors use.
            title = ("● " if dirty else "") + self.name
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
    # Dictionary info (no longer a permanent header — info lives in the
    # right-hand cluster of the unified Search & Filters bar and the
    # popover that opens from the ⓘ chip).
    # ------------------------------------------------------------------
    def _refresh_dictionary_header(self):
        """Refresh the unified bar's entry-count chip and cached info
        strings.  Kept as ``_refresh_dictionary_header`` because dozens of
        callers reach it from outside this file."""
        if not hasattr(self, "entry_count_var"):
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

        # Cache fresh values so the popover and tooltip pull live data.
        self._info_total = total
        self._info_conflicts = conflict_count
        self._info_briefs = brief_count
        self._info_freq_pct = freq_pct

        # The entry-count chip is owned by _apply_filters, which knows
        # both the filtered ("X of Y") and unfiltered ("N entries") forms.
        # Only seed it here if the filter hasn't yet had a chance to run.
        if not (self.entry_count_var.get() or "").strip():
            self.entry_count_var.set(
                f"{total:,} entr{'y' if total == 1 else 'ies'}"
            )

        # Conflict chip - shown only when there are actual conflicts; uses
        # the danger style so it stands out.
        if hasattr(self, "conflict_chip"):
            if conflict_count:
                text = f"{conflict_count:,} conflict{'s' if conflict_count != 1 else ''}"
                self.conflict_chip.configure(text=text, style="HeaderDanger.TLabel")
                if not self.conflict_chip.winfo_ismapped():
                    self.conflict_chip.pack(side=tk.LEFT, padx=(0, 6),
                                            before=self.info_btn)
            else:
                if self.conflict_chip.winfo_ismapped():
                    self.conflict_chip.pack_forget()

        # Saved / unsaved state chip
        if hasattr(self, "saved_chip"):
            if self._json_dirty:
                self.saved_chip.configure(text="Unsaved", style="HeaderWarning.TLabel")
            else:
                self.saved_chip.configure(text="Saved", style="HeaderSuccess.TLabel")

        # Tooltip on the count chip shows path + stats
        if hasattr(self, "_count_tooltip") and self._count_tooltip is not None:
            self._count_tooltip.update_text(self._info_tooltip_text())

    def _info_tooltip_text(self) -> str:
        path = self.dict_path or "Unsaved dictionary"
        return (
            f"{path}\n\n"
            f"{self._info_total:,} entries\n"
            f"{self._info_briefs:,} briefs\n"
            f"{self._info_conflicts:,} conflicts\n"
            f"{self._info_freq_pct}% frequency matched\n\n"
            f"Click for details"
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

    def _copy_path_to_clipboard(self, _event=None):
        """Clicking the header path copies the full file path to the clipboard."""
        path = self.dict_path or ""
        if not path:
            return
        try:
            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(path)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Unified Search & Filters bar
    # ------------------------------------------------------------------
    def _build_search_filter_panel(self):
        """One collapsible bar that contains the search inputs, filter
        checkboxes, active chips for both, the entry-count chip and the
        ⓘ info popover.

        Layout:

            Header (always visible):
                ▶/▼  Search & Filters   [chips ...]      [123 entries] [Unsaved] [ⓘ]
            Body (shown when expanded):
                ┌ Search ────────────────────────────────────────────────┐
                │ Text:  [Method ▼] [____________]  [ ] Match case       │
                │ Steno: [Method ▼] [____________]  [ ] Whole strokes    │
                │ Scope: [Current Dictionary ▼]                  [Clear] │
                └────────────────────────────────────────────────────────┘
                ┌ Filters ───────────────────────────────────────────────┐
                │ [ ] Has comments  [ ] Is brief  [ ] Bookmarked …       │
                │ [ ] Capitalised   [ ] Digits   [ ] Punctuation …       │
                │ [ ] Has freq  [ ] Top [500] entries  [ ] Show F col    │
                └────────────────────────────────────────────────────────┘
        """
        # Container
        self.unified_container = ttk.Frame(self, style="UnifiedBar.TFrame")
        self.unified_container.pack(fill=tk.X, pady=(0, 6))

        # ---------------------------------------------------------------
        # Header
        # ---------------------------------------------------------------
        self.unified_header = ttk.Frame(self.unified_container,
                                        style="UnifiedBar.TFrame")
        self.unified_header.pack(fill=tk.X, padx=10, pady=(6, 6))
        self.unified_header.bind("<Button-1>", self._toggle_unified)

        arrow = "▼" if self.unified_expanded else "▶"
        self.unified_label = ttk.Label(
            self.unified_header,
            text=f"{arrow}  Search & Filters",
            style="Disclosure.TLabel",
            padding=(2, 2),
            cursor="hand2",
        )
        self.unified_label.pack(side=tk.LEFT)
        self.unified_label.bind("<Button-1>", self._toggle_unified)

        # Active chip strip (search + filter chips combined)
        self.active_chip_frame = ttk.Frame(self.unified_header,
                                           style="UnifiedBar.TFrame")
        self.active_chip_frame.pack(side=tk.LEFT, padx=(12, 0))

        # Right-hand cluster: count chip + saved chip + info button
        right = ttk.Frame(self.unified_header, style="UnifiedBar.TFrame")
        right.pack(side=tk.RIGHT)

        self.info_btn = ttk.Button(
            right,
            text="ⓘ",
            style="ToolbarIcon.TButton",
            command=self._open_info_popup,
            takefocus=False,
        )
        self.info_btn.pack(side=tk.RIGHT)
        Tooltip(self.info_btn, "Show full dictionary info")

        self.saved_chip = ttk.Label(right, text="Saved", style="HeaderSuccess.TLabel")
        self.saved_chip.pack(side=tk.RIGHT, padx=(0, 8))

        # Conflict chip (hidden unless > 0 — packed in _refresh_dictionary_header)
        self.conflict_chip = ttk.Label(right, text="", style="HeaderDanger.TLabel")

        self.entry_count_var = tk.StringVar(value="0 entries")
        self.count_chip = ttk.Label(
            right, textvariable=self.entry_count_var, style="HeaderInfo.TLabel"
        )
        self.count_chip.pack(side=tk.RIGHT, padx=(0, 8))
        self._count_tooltip = Tooltip(self.count_chip, "")

        # ---------------------------------------------------------------
        # Body (animated)
        # ---------------------------------------------------------------
        self.unified_body = ttk.Frame(self.unified_container,
                                      style="UnifiedBar.TFrame")
        # Note: not packed until _open_immediately or _animate_unified runs.

        # ----- Search inputs -----
        self.searchbar = SearchBar(
            self.unified_body,
            on_search=self._on_local_search_changed,
        )
        self.searchbar.pack(fill=tk.X, padx=8, pady=(2, 0))

        ttk.Separator(self.unified_body, orient="horizontal").pack(
            fill=tk.X, padx=10, pady=(4, 4),
        )

        # ----- Filter checkboxes -----
        filters_box = ttk.Frame(self.unified_body, style="UnifiedBar.TFrame")
        filters_box.pack(fill=tk.X, padx=8, pady=(0, 6))

        row1 = ttk.Frame(filters_box, style="UnifiedBar.TFrame")
        row1.pack(fill=tk.X)
        for text, var in [
            ("Has comments", self.filter_has_comments),
            ("Is brief",     self.filter_is_brief),
            ("Bookmarked",   self.filter_bookmarked),
            ("Conflicts",    self.filter_conflicts),
        ]:
            ttk.Checkbutton(row1, text=text, variable=var,
                            command=self._apply_filters).pack(side=tk.LEFT, padx=(0, 16),
                                                              pady=3)

        row2 = ttk.Frame(filters_box, style="UnifiedBar.TFrame")
        row2.pack(fill=tk.X)
        for text, var in [
            ("Capitalised",       self.filter_capitalised),
            ("Numbers (0–9)",     self.filter_has_digits),
            ("Numbers (written)", self.filter_has_written_numbers),
            ("Punctuation",       self.filter_has_punctuation),
        ]:
            ttk.Checkbutton(row2, text=text, variable=var,
                            command=self._apply_filters).pack(side=tk.LEFT, padx=(0, 16),
                                                              pady=3)

        row3 = ttk.Frame(filters_box, style="UnifiedBar.TFrame")
        row3.pack(fill=tk.X)
        ttk.Checkbutton(
            row3, text="Has frequency", variable=self.filter_has_frequency,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=(0, 16), pady=3)

        top_group = ttk.Frame(row3, style="UnifiedBar.TFrame")
        top_group.pack(side=tk.LEFT, padx=(0, 16), pady=3)
        ttk.Checkbutton(
            top_group, text="Top", variable=self.filter_top_freq,
            command=self._apply_filters,
        ).pack(side=tk.LEFT)
        ttk.Entry(top_group, textvariable=self.filter_top_freq_n_var, width=6).pack(
            side=tk.LEFT, padx=(4, 4),
        )
        ttk.Label(top_group, text="entries by frequency",
                  style="UnifiedBar.TLabel").pack(side=tk.LEFT)

        ttk.Checkbutton(
            row3, text="Show frequency column",
            variable=self.show_freq_column,
            command=self._toggle_freq_column,
        ).pack(side=tk.RIGHT, pady=3)

        ttk.Checkbutton(
            row3, text="Focus mode",
            variable=self.focus_mode,
            command=self._toggle_focus_mode,
        ).pack(side=tk.RIGHT, padx=(0, 16), pady=3)

        # Hidden count label used by legacy code paths (kept as None-safe
        # reference; the visible count is now in self.count_chip).
        self.count_label = self.count_chip

        # Establish initial expanded / collapsed visual.
        if self.unified_expanded:
            self.unified_body.pack(fill=tk.X, padx=2, pady=(0, 4))
        else:
            self.unified_label.config(text="▶  Search & Filters")
        self._refresh_dictionary_header()

    def _toggle_unified(self, _event=None):
        if self.unified_expanded:
            self.collapse_unified()
        else:
            self.expand_unified()

    def expand_unified(self, focus_field: str | None = None,
                       append_char: str | None = None):
        if not self.unified_expanded:
            self.unified_expanded = True
            self.unified_label.config(text="▼  Search & Filters")
            if not self.unified_body.winfo_ismapped():
                self.unified_body.pack(fill=tk.X, padx=2, pady=(0, 4))
            self._notify_collapse_state(False)
        if focus_field == "text":
            self.searchbar.focus_text_entry(append_char=append_char)
        elif focus_field == "steno":
            self.searchbar.focus_steno_entry(append_char=append_char)

    def collapse_unified(self):
        if not self.unified_expanded:
            return
        # Flush any pending debounced search before the panel disappears
        if hasattr(self, "searchbar"):
            self.searchbar.flush_pending()
        self.unified_expanded = False
        self.unified_label.config(text="▶  Search & Filters")
        if self.unified_body.winfo_ismapped():
            self.unified_body.pack_forget()
        self._notify_collapse_state(True)

    def _notify_collapse_state(self, collapsed: bool):
        if callable(self._on_search_collapse_changed):
            try:
                self._on_search_collapse_changed(collapsed)
            except Exception:
                pass

    def _on_local_search_changed(self, config):
        """Apply locally, then broadcast if scope is 'All Dictionaries'."""
        self.search_config = config or {}
        self._apply_filters()
        if (config or {}).get("scope") == "All Dictionaries" and callable(
            self._on_search_broadcast
        ):
            try:
                self._on_search_broadcast(self, config)
            except Exception:
                pass

    def set_search_quietly(self, config: dict):
        """Receive a sibling's broadcast: mirror its query inputs and re-filter."""
        if not hasattr(self, "searchbar"):
            return
        self.searchbar.set_config_quietly(config or {})
        merged = self.searchbar.get_config()
        self.search_config = merged
        self._apply_filters()

    def focus_search_text(self, append_char=None):
        """Expose the search bar's text-field focus for type-ahead routing."""
        if not hasattr(self, "searchbar"):
            return
        if not self.unified_expanded:
            self.expand_unified(focus_field="text", append_char=append_char)
        else:
            self.searchbar.focus_text_entry(append_char=append_char)

    def _open_info_popup(self):
        """Show a popover with full dictionary details."""
        if hasattr(self, "_info_popup") and self._info_popup is not None:
            try:
                if self._info_popup.winfo_exists():
                    self._info_popup.destroy()
            except tk.TclError:
                pass
            self._info_popup = None

        pop = tk.Toplevel(self.winfo_toplevel())
        pop.wm_overrideredirect(True)
        pop.transient(self.winfo_toplevel())
        pop.configure(bg=C["border"])
        self._info_popup = pop

        inner = ttk.Frame(pop, style="Card.TFrame", padding=14)
        inner.pack(padx=1, pady=1)

        ttk.Label(inner, text=self.name or "Dictionary",
                  style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(inner, text=self.dict_path or "Unsaved — not yet on disk",
                  style="CardSubtitle.TLabel",
                  wraplength=420).pack(anchor="w", pady=(2, 12))

        stats = ttk.Frame(inner, style="CardActions.TFrame")
        stats.pack(anchor="w")
        rows = [
            ("Entries",            f"{self._info_total:,}"),
            ("Briefs",             f"{self._info_briefs:,}"),
            ("Conflicts",          f"{self._info_conflicts:,}"),
            ("Frequency matched",  f"{self._info_freq_pct}%"),
            ("State",              "Unsaved" if self._json_dirty else "Saved"),
        ]
        for r, (k, v) in enumerate(rows):
            ttk.Label(stats, text=k, style="CardSubtitle.TLabel").grid(
                row=r, column=0, sticky="w", padx=(0, 18), pady=2,
            )
            ttk.Label(stats, text=v, style="CardItem.TLabel").grid(
                row=r, column=1, sticky="w", pady=2,
            )

        # Actions
        actions = ttk.Frame(inner, style="CardActions.TFrame")
        actions.pack(anchor="w", pady=(12, 0))
        ttk.Button(
            actions, text="Copy path", style="Secondary.TButton",
            command=lambda: self._copy_path_to_clipboard(),
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions, text="Close", style="Secondary.TButton",
            command=pop.destroy,
        ).pack(side=tk.LEFT, padx=(8, 0))

        # Position the popover under the ⓘ button
        try:
            x = self.info_btn.winfo_rootx()
            y = self.info_btn.winfo_rooty() + self.info_btn.winfo_height() + 4
            pop.update_idletasks()
            pw = pop.winfo_reqwidth()
            sw = pop.winfo_screenwidth()
            x = min(x, sw - pw - 12)
            pop.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

        # Dismiss on Escape or click outside
        pop.bind("<Escape>", lambda _e: pop.destroy())
        pop.bind("<FocusOut>", lambda _e: pop.destroy())
        pop.focus_set()

    def _update_no_match_hint(self, *, showing: int, search_active: bool):
        """Append a "no matches" indicator + a Clear-search affordance to
        the active chip strip.  Runs after ``_refresh_filter_chips`` so
        the hint always sits to the right of the chips."""
        if not hasattr(self, "active_chip_frame"):
            return
        if not (search_active and showing == 0):
            return
        ttk.Label(
            self.active_chip_frame,
            text="no matches",
            style="WarningBadge.TLabel",
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            self.active_chip_frame,
            text="Clear search ✕",
            style="Chip.TButton",
            command=self.searchbar.clear,
        ).pack(side=tk.LEFT, padx=(0, 6))

    def _clear_active_filters_local(self):
        """Clear all active filter toggles on this tab."""
        for attr in (
            "filter_has_comments", "filter_is_brief", "filter_bookmarked",
            "filter_capitalised", "filter_has_digits", "filter_has_written_numbers",
            "filter_has_punctuation", "filter_conflicts",
            "filter_has_frequency", "filter_top_freq",
        ):
            var = getattr(self, attr, None)
            if var is not None:
                try:
                    var.set(False)
                except Exception:
                    pass
        self._apply_filters()

    def _filter_chip_defs(self):
        return [
            ("Comments", self.filter_has_comments),
            ("Brief", self.filter_is_brief),
            ("Bookmarked", self.filter_bookmarked),
            ("Conflicts", self.filter_conflicts),
            ("Capitalised", self.filter_capitalised),
            ("Digits", self.filter_has_digits),
            ("Written numbers", self.filter_has_written_numbers),
            ("Punctuation", self.filter_has_punctuation),
            ("Frequency", self.filter_has_frequency),
            (f"Top {self.filter_top_freq_n_var.get().strip() or '500'}", self.filter_top_freq),
        ]

    def _refresh_filter_chips(self):
        """Render the combined search + filter active-chip row inside
        the unified bar's header.  Clears all children unconditionally —
        any no-match hint will be re-added afterwards by
        ``_update_no_match_hint`` so it always appears to the right of
        the chips."""
        if not hasattr(self, "active_chip_frame"):
            return
        for child in list(self.active_chip_frame.winfo_children()):
            child.destroy()

        search_chips = self.searchbar.chip_defs() if hasattr(self, "searchbar") else []
        filter_chips = [(label, lambda v=var: self._clear_filter_var(v))
                        for label, var in self._filter_chip_defs() if var.get()]

        chips = search_chips + filter_chips
        if not chips:
            return

        for label, callback in chips:
            btn = ttk.Button(
                self.active_chip_frame,
                text=f"{label} ✕",
                style="Chip.TButton",
                command=callback,
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))

    def _clear_filter_var(self, var):
        var.set(False)
        self._apply_filters()

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

        # Friendly hover tooltips on the cryptic column headings (S, W, B, F).
        self._heading_tooltip = TreeHeadingTooltip(self.tree, self.COLUMN_TOOLTIPS)

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
        # Locate the exact entry represented by the visible row.  Pagination
        # means tree row 0 is not always filtered_entries[0].
        target = self._entry_for_tree_item(selected[0])
        if target is None:
            return
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
            if not self._save_metadata_if_dirty():
                return False
            self._set_dirty(False)
            self._undo_stack.mark_saved()
            return True
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save dictionary:\n{e}")
            return False

    def _save_metadata_if_dirty(self) -> bool:
        """Persist sidecar metadata when an edit changed it in memory."""
        if not self._metadata_dirty or not self.dict_path or self.metadata is None:
            return True
        try:
            save_metadata(self.dict_path, self.metadata)
            self._metadata_dirty = False
            return True
        except Exception as e:
            messagebox.showerror(
                "Metadata Save Error",
                f"Failed to save entry metadata:\n{e}",
            )
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
        # can't tell which row the user actually clicked.
        targets = set()
        for iid in selected:
            entry = self._entry_for_tree_item(iid)
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
        self._metadata_dirty = True
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
        self._metadata_dirty = True
        if not self._undo_stack.is_dirty:
            self._save_metadata_if_dirty()
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
                self._metadata_dirty = True
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
        for item in self.tree.selection():
            entry = self._entry_for_tree_item(item)
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

    def _entry_for_tree_item(self, item):
        """Return the filtered entry represented by a visible Treeview item."""
        children = self.tree.get_children()
        try:
            visible_idx = children.index(item)
        except ValueError:
            return None
        filtered_idx = self._page * MAX_DISPLAY_ROWS + visible_idx
        if filtered_idx >= len(self.filtered_entries):
            return None
        return self.filtered_entries[filtered_idx]

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
        self._refresh_filter_chips()

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

        # Update entry-count chip — total when nothing filtered, otherwise
        # "X of Y".  Style changes (rather than fg overrides) when a search
        # returns zero matches so the chip lights up red.
        total   = len(self.entries)
        showing = len(results)
        search_active = steno_active or text_active

        if showing < total:
            self.entry_count_var.set(f"{showing:,} of {total:,}")
        else:
            self.entry_count_var.set(f"{total:,} entries")

        if hasattr(self, "count_chip"):
            if search_active and showing == 0:
                self.count_chip.configure(style="HeaderDanger.TLabel")
            else:
                self.count_chip.configure(style="HeaderInfo.TLabel")

        self._update_no_match_hint(showing=showing, search_active=search_active)

        # Notify owner of result count - lets main.py react if interested.
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

        Performance:
        - Caps inserted rows at MAX_DISPLAY_ROWS (users find their target
          by searching, not scrolling, so the cap is rarely felt).
        - Fingerprints the slice that's about to be drawn and skips the
          rebuild entirely if the same page is already on screen.
        - Hoists everything possible out of the per-row loop; column row
          tuples are built positionally to avoid intermediate dicts.
        """
        # Clamp the page to the valid range in case filtered_entries shrank
        # (e.g. after a search that returns fewer results than the current page).
        max_page = max(0, (len(self.filtered_entries) - 1) // MAX_DISPLAY_ROWS)
        self._page = min(self._page, max_page)

        start  = self._page * MAX_DISPLAY_ROWS
        capped = self.filtered_entries[start:start + MAX_DISPLAY_ROWS]

        prev_selected = self._stenos_for_items(self.tree.selection())

        # Hoist locals — measurable on 100k-entry dictionaries.
        tree              = self.tree
        tree_insert       = tree.insert
        END               = tk.END
        metadata          = self.metadata or {}
        bookmarked_stenos = self.bookmarked_stenos
        conflict_stenos   = self.conflict_stenos
        max_chars         = MAX_COMMENT_CHARS
        cols_tuple        = tuple(self.column_order)
        # Column → row-tuple index mapping built once for this render.
        col_indexes = {c: i for i, c in enumerate(cols_tuple)}
        n_cols = len(cols_tuple)

        tree.delete(*tree.get_children())
        to_reselect = []

        empty_meta = {}
        for i, entry in enumerate(capped):
            steno   = entry["steno"]
            english = entry.get("english") or ""
            meta    = metadata.get(steno, empty_meta)

            comments = meta.get("comments", "")
            if comments and len(comments) > max_chars:
                comments = comments[:max_chars - 3] + "..."

            freq = meta.get("frequency", 0)

            # Build the row tuple positionally for the current column order.
            row = [""] * n_cols
            for col, idx in col_indexes.items():
                if col == "steno":
                    row[idx] = steno
                elif col == "english":
                    row[idx] = english
                elif col == "S":
                    row[idx] = steno.count("/") + 1
                elif col == "W":
                    row[idx] = len(english.split())
                elif col == "B":
                    row[idx] = "✓" if meta.get("brief", False) else ""
                elif col == "F":
                    row[idx] = f"{freq:,}" if freq else ""
                elif col == "added":
                    row[idx] = meta.get("date_added", entry.get("date_added", ""))
                elif col == "modified":
                    row[idx] = meta.get("modified", entry.get("modified", ""))
                elif col == "comments":
                    row[idx] = comments

            # Build tag list — later tags override earlier ones
            if steno in bookmarked_stenos:
                if steno in conflict_stenos:
                    tag = "bookmarked_conflict"
                else:
                    tag = "bookmarked"
            elif steno in conflict_stenos:
                tag = "conflict"
            else:
                tag = "row_odd" if i & 1 else "row_even"
            tags = (tag,)

            iid = tree_insert("", END, values=row, tags=tags)
            if steno in prev_selected:
                to_reselect.append(iid)

        if to_reselect:
            tree.selection_set(to_reselect)

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
        entry = self._entry_for_tree_item(selected[0])
        if entry is None:
            return
        self._open_edit_dialog(entry)

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
