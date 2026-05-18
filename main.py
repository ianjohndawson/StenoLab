# main.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

# UI components
from ui.theme import apply_steno_theme, apply_theme, set_titlebar_dark, get_mode
from ui.toolbar import Toolbar
from ui.searchbar import SearchBar
from ui.dictionary_tab import DictionaryTab
from ui.statusbar import StatusBar
from ui.open_dictionary_dialog import ask_open_dictionary
from ui.missing_frequency_dialog import (
    MissingFrequencyDialog,
    IgnoredFrequencyWordsDialog,
    IGNORED_WORDS_KEY,
)

# Logic
from logic.dictionary_loader import load_dictionary_with_metadata
from logic.metadata_store import METADATA_ROOT, save_metadata
from logic.settings_store import load_settings, save_settings
from logic.frequency_importer import (
    DEFAULT_UK_FREQUENCY_URL,
    download_frequency_text,
    parse_frequency_text,
    parse_frequency_file,
)

from ui.find_replace_dialog import FindReplaceDialog

import os
import subprocess


class StenoApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("StenoLab")
        self.geometry("1100x700")
        self.minsize(900, 600)

        # Theme - read persisted choice (default: dark)
        settings = load_settings()
        self._theme_mode = settings.get("theme", "dark")
        self.dark_mode_var = tk.BooleanVar(value=(self._theme_mode == "dark"))

        apply_steno_theme(self, mode=self._theme_mode)

        # Search panel collapse state - default to collapsed for a clean
        # opening view, same philosophy as the Filter panel.
        self._search_collapsed = settings.get("search_collapsed", True)

        # Display row cap.  Default 500.  Hidden setting reachable via
        # Tools → Set Display Limit; the module-level constant is mutated
        # so all places that read it (refresh tree, hint label) pick up
        # the new value on the next filter pass.
        from ui import dictionary_tab as _dt_module
        cap = settings.get("max_display_rows", _dt_module.MAX_DISPLAY_ROWS)
        try:
            cap = int(cap)
            if cap >= 1:
                _dt_module.MAX_DISPLAY_ROWS = cap
        except (TypeError, ValueError):
            pass

        self.tabs = {}
        self._find_replace_dlg = None   # singleton

        # Track which dictionary paths have been backed up since the program
        # started.  Each path triggers exactly one open-time backup; saves
        # then add their own pre-save backups on top.
        self._backed_up_this_session: set = set()

        self._create_menu()
        self._create_layout()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keyboard shortcuts
        self.bind("<Control-s>", lambda e: self._save_current_dictionary())

        # Type-ahead: forward bare keystrokes to the Text search field when no
        # input widget currently has focus.
        self.bind_all("<KeyPress>", self._maybe_route_type_ahead, add="+")

        # Reopen tabs from previous session
        self._restore_open_tabs()

        # Re-apply title bar after the window is mapped, so DWM has a real HWND
        # to operate on. This makes the dark title bar reliably stick on Windows.
        self.after(50, lambda: set_titlebar_dark(self, self._theme_mode == "dark"))
        self.after(400, self._poll_statusbar)

    # ------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------
    def _create_menu(self):
        menubar = tk.Menu(self)

        # ── File ──────────────────────────────────────────────────
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Open Dictionary...",
            command=self._open_dictionary,
            accelerator="Ctrl+O",
        )
        file_menu.add_command(
            label="Save Dictionary",
            command=self._save_current_dictionary,
            accelerator="Ctrl+S",
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Close Dictionary",
            command=self._close_current_dictionary,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # ── Edit ──────────────────────────────────────────────────
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(
            label="Undo",
            command=self._undo,
            accelerator="Ctrl+Z",
        )
        edit_menu.add_command(
            label="Redo",
            command=self._redo,
            accelerator="Ctrl+Y",
        )
        edit_menu.add_separator()
        edit_menu.add_command(
            label="Add Entry",
            command=self._open_add_entry_dialog,
            accelerator="Ctrl+N",
        )
        edit_menu.add_command(
            label="Edit Entry",
            command=self._open_edit_entry_dialog,
            accelerator="Ctrl+E",
        )
        edit_menu.add_command(
            label="Delete Selected",
            command=self._delete_selected,
            accelerator="Del",
        )
        edit_menu.add_separator()
        edit_menu.add_command(
            label="Toggle Bookmark",
            command=self._toggle_bookmark,
            accelerator="Ctrl+B",
        )
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # ── Tools ─────────────────────────────────────────────────
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(
            label="Restore Backup...",
            command=self._restore_backup,
        )
        tools_menu.add_separator()
        tools_menu.add_command(
            label="Open Backup Folder",
            command=self._open_backup_folder,
        )
        tools_menu.add_command(
            label="Open Metadata Folder",
            command=self._open_metadata_folder,
        )
        tools_menu.add_separator()
        tools_menu.add_command(
            label="Import Frequency List...",
            command=self._import_frequency_list,
        )
        tools_menu.add_command(
            label="Review Missing Frequency Words...",
            command=self._review_missing_frequency_words,
        )
        tools_menu.add_command(
            label="Manage Ignored Frequency Words...",
            command=self._manage_ignored_frequency_words,
        )
        tools_menu.add_command(
            label="Set Display Limit...",
            command=self._set_display_limit,
        )
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # ── View ──────────────────────────────────────────────────
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Dark Mode",
            variable=self.dark_mode_var,
            command=self._toggle_theme,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menubar)

        # Keyboard accelerators
        self.bind("<Control-o>", lambda e: self._open_dictionary())
        self.bind("<Control-n>", lambda e: self._open_add_entry_dialog())
        self.bind("<Control-e>", lambda e: self._open_edit_entry_dialog())
        self.bind("<Control-b>", lambda e: self._toggle_bookmark())
        self.bind("<Control-f>", lambda e: self._open_find_replace())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<Control-Z>", lambda e: self._redo())   # Ctrl+Shift+Z
        self.bind("<F3>", lambda e: self._find_next_global())
        self.bind("<Shift-F3>", lambda e: self._find_prev_global())

    # ------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------
    def _create_layout(self):

        self.toolbar = Toolbar(
            self,
            callbacks={
                "add":       self._open_add_entry_dialog,
                "edit":      self._open_edit_entry_dialog,
                "find":      self._open_find_replace,
                "bookmarks": self._toggle_bookmark,
                "open":      self._open_dictionary,
                "undo":      self._undo,
                "redo":      self._redo,
            }
        )
        self.toolbar.pack(fill=tk.X, padx=10, pady=(10, 0))

        self.searchbar = SearchBar(
            self,
            on_search=self._on_search_update,
            on_collapse_changed=self._on_search_collapse_changed,
            initially_collapsed=self._search_collapsed,
        )
        self.searchbar.pack(fill=tk.X, padx=10, pady=10)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.notebook.bind("<Button-3>", self._on_tab_right_click)
        self.notebook.bind("<ButtonPress-1>", self._on_tab_drag_start, add="+")
        self.notebook.bind("<B1-Motion>", self._on_tab_drag_motion, add="+")
        self.notebook.bind("<ButtonRelease-1>", self._on_tab_drag_end, add="+")
        self._drag_tab_id = None

        self.statusbar = StatusBar(self, on_save_all=self._save_all_dictionaries)
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

        self.statusbar.update_status(entries=0, dictionaries=0, active="None", unsaved=0)

    # ------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------
    def _on_tab_changed(self, event=None):
        tab = self._get_active_tab()
        if tab:
            tab.event_generate("<<DictionaryTabActivated>>")
            self.statusbar.update_status(
                entries=len(tab.entries),
                active=tab.name,
            )
            # Re-apply the search to the now-active tab so its filtered
            # state matches the search bar.  We don't touch any other tab:
            # they're not visible right now, and re-running their filter
            # pipeline on tab change adds visible lag with large dictionaries.
            try:
                tab.apply_search(self.searchbar.get_config())
            except Exception:
                pass
        self._refresh_undo_buttons()

    def _get_active_tab(self):
        try:
            widget = self.notebook.nametowidget(self.notebook.select())
            return widget
        except Exception:
            return None

    def _tab_id_at(self, x, y):
        try:
            if not self.notebook.identify(x, y):
                return None
            idx = self.notebook.index(f"@{x},{y}")
            return self.notebook.tabs()[idx]
        except (IndexError, tk.TclError):
            return None

    def _on_tab_drag_start(self, event):
        self._drag_tab_id = self._tab_id_at(event.x, event.y)

    def _on_tab_drag_motion(self, event):
        if not self._drag_tab_id:
            return
        target_id = self._tab_id_at(event.x, event.y)
        if not target_id or target_id == self._drag_tab_id:
            return
        try:
            current_index = self.notebook.index(self._drag_tab_id)
            target_index = self.notebook.index(target_id)
            bx, _, bw, _ = self.notebook.bbox(target_index)
            if event.x > bx + (bw / 2):
                target_index += 1
            if current_index < target_index:
                target_index -= 1
            if current_index == target_index:
                return
            self.notebook.insert(target_index, self._drag_tab_id)
            self.notebook.select(self._drag_tab_id)
        except tk.TclError:
            pass

    def _on_tab_drag_end(self, event):
        if self._drag_tab_id:
            self._save_open_tabs()
        self._drag_tab_id = None

    # ------------------------------------------------------------
    # Right-click on tab heading
    # ------------------------------------------------------------
    def _on_tab_right_click(self, event):
        """
        Show a context menu when the user right-clicks a tab heading.
        We use ttk.Notebook.identify(x, y) to find which tab was clicked;
        when the click is on the tab area it returns 'label', otherwise
        an empty string (and we ignore it).
        """
        try:
            element = self.notebook.identify(event.x, event.y)
        except tk.TclError:
            return
        if not element:
            return

        # Find the tab index under the cursor
        try:
            tab_index = self.notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return

        # Get the underlying widget for that tab
        try:
            tab_id = self.notebook.tabs()[tab_index]
            tab_widget = self.notebook.nametowidget(tab_id)
        except (IndexError, tk.TclError):
            return

        if not isinstance(tab_widget, DictionaryTab):
            return

        # Switch to the right-clicked tab so subsequent commands operate on it.
        # Without this the user might right-click tab B intending to close it
        # but the "active tab" is still A.
        self.notebook.select(tab_id)

        menu = tk.Menu(self, tearoff=0)
        is_dirty = bool(getattr(tab_widget, "_json_dirty", False))

        # Save - only meaningful if there are unsaved changes
        if is_dirty:
            menu.add_command(label="Save", command=self._save_current_dictionary)
        else:
            menu.add_command(label="Save", state="disabled")

        menu.add_command(label="Save As...", command=self._save_as_dictionary)
        menu.add_separator()
        menu.add_command(label="Open Containing Folder",
                         command=lambda w=tab_widget: self._open_containing_folder(w))
        menu.add_command(label="Restore Backup...", command=self._restore_backup)
        menu.add_separator()
        menu.add_command(label="Close", command=self._close_current_dictionary)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_containing_folder(self, tab_widget):
        """Reveal the tab's dictionary file in the system file browser."""
        path = getattr(tab_widget, "dict_path", None)
        if not path:
            messagebox.showinfo(
                "Open Containing Folder",
                "This dictionary has no file path yet (it hasn't been saved).",
            )
            return
        folder = os.path.dirname(path)
        if not folder:
            return
        self._open_folder_in_explorer(folder)

    def _save_as_dictionary(self):
        """Save the active tab's dictionary to a chosen new path."""
        from tkinter import filedialog
        tab = self._get_active_tab()
        if tab is None:
            return

        initial = os.path.basename(tab.dict_path) if tab.dict_path else "dictionary.json"
        new_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Dictionary As",
            defaultextension=".json",
            filetypes=[("JSON Dictionary", "*.json")],
            initialfile=initial,
        )
        if not new_path:
            return

        new_name, _ = os.path.splitext(os.path.basename(new_path))
        new_key = self._tab_key_for_path(new_path)
        if new_key in self.tabs and self.tabs[new_key] is not tab:
            messagebox.showerror(
                "Save As Failed",
                "That dictionary is already open in another tab.",
            )
            return

        # Repoint the tab at the new path and save.  The original file is
        # left untouched — this is "fork", not "rename".
        old_path = tab.dict_path
        tab.dict_path = new_path

        # Update the tab title and self.tabs key
        old_key = next((k for k, t in self.tabs.items() if t is tab), None)
        if old_key is not None and old_key != new_key:
            del self.tabs[old_key]
            self.tabs[new_key] = tab
            tab.name = new_name
            self.notebook.tab(tab, text=new_name)

        try:
            saved = tab.save_json()
        except Exception as e:
            messagebox.showerror(
                "Save As Failed",
                f"Could not save dictionary to {os.path.basename(new_path)}:\n\n{e}",
            )
            saved = False

        if not saved:
            # Roll back the path and key change so the user isn't left in a weird state
            tab.dict_path = old_path
            if old_key is not None and old_key != new_key:
                del self.tabs[new_key]
                self.tabs[old_key] = tab
                tab.name, _ = os.path.splitext(os.path.basename(old_path)) if old_path else (new_name, "")
                self.notebook.tab(tab, text=tab.name)
            return
        if hasattr(tab, "_refresh_dictionary_header"):
            tab._refresh_dictionary_header()

    # ------------------------------------------------------------
    # Open Dictionary
    # ------------------------------------------------------------
    def _open_dictionary(self):
        path = ask_open_dictionary(self)
        if not path:
            return
        if os.path.isdir(path):
            messagebox.showerror(
                "Invalid Selection",
                "Please select a JSON dictionary file, not a folder."
            )
            return
        self._open_dictionary_path(path)

    def _tab_key_for_path(self, path):
        """Stable key for tab bookkeeping; display names remain user-friendly."""
        return os.path.normcase(os.path.abspath(path))

    def _open_dictionary_path(self, path):
        """Load a dictionary from path and add it as a tab. Safe to call on startup."""
        if not os.path.isfile(path):
            return

        tab_key = self._tab_key_for_path(path)
        if tab_key in self.tabs:
            self.notebook.select(self.tabs[tab_key])
            return

        try:
            entries, metadata, _ = load_dictionary_with_metadata(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load dictionary:\n{e}")
            return

        # Take an open-time backup so the user has a snapshot of the file as
        # it was when they started working today.  Done once per path per
        # session — reopening the same file later in the session won't
        # produce a redundant backup.
        if path not in self._backed_up_this_session:
            try:
                from logic.backup_store import backup_dictionary
                backup_dictionary(path, kind="open")
            except Exception:
                pass  # never let a backup failure block opening
            self._backed_up_this_session.add(path)

        base = os.path.basename(path)
        name, _ = os.path.splitext(base)

        tab = DictionaryTab(
            self.notebook,
            name=name,
            on_entries_changed=self._on_entries_changed,
            on_filter_count_changed=self._on_filter_count_changed,
        )

        tab.dict_path = path
        tab.load_entries(entries, metadata)

        # Apply the current search config so the new tab opens already filtered
        # consistently with the others.
        try:
            tab.apply_search(self.searchbar.get_config())
        except Exception:
            pass

        self.notebook.add(tab, text=name)
        self.tabs[tab_key] = tab
        self.notebook.select(tab)
        if hasattr(tab, "_refresh_dictionary_header"):
            tab._refresh_dictionary_header()

        self.statusbar.update_status(
            entries=len(entries),
            dictionaries=len(self.tabs),
            active=name
        )
        self._refresh_unsaved_status()

    # ------------------------------------------------------------
    # Save Dictionary
    # ------------------------------------------------------------
    def _save_current_dictionary(self):
        tab = self._get_active_tab()
        if not tab:
            return
        if tab.save_json():
            self.statusbar.update_status(saved=datetime.now().strftime("%H:%M"))
        self._refresh_unsaved_status()

    # ------------------------------------------------------------
    # Close Dictionary
    # ------------------------------------------------------------
    def _close_current_dictionary(self):
        if not self.tabs:
            return

        widget = self._get_active_tab()
        if widget is None:
            return

        # Prompt if dirty
        if getattr(widget, "_json_dirty", False) and widget.dict_path:
            from ui.save_changes_dialog import (
                ask_save_changes, RESULT_SAVE, RESULT_DISCARD, RESULT_CANCEL,
            )
            result, to_save = ask_save_changes(
                self, [widget.dict_path], context="close",
            )
            if result == RESULT_CANCEL:
                return
            if result == RESULT_SAVE and widget.dict_path in to_save:
                try:
                    saved = widget.save_json()
                except Exception as e:
                    messagebox.showerror(
                        "Save Failed",
                        f"Could not save {os.path.basename(widget.dict_path)}:\n\n{e}",
                    )
                    return
                if not saved:
                    return

        # Drop the tab (use widget identity, not title - the title may have a
        # ' *' suffix when dirty)
        name_to_remove = next(
            (n for n, t in self.tabs.items() if t is widget), None
        )
        if name_to_remove is not None:
            del self.tabs[name_to_remove]
        self.notebook.forget(widget)

        if self.tabs:
            first = next(iter(self.tabs.values()))
            self.statusbar.update_status(
                entries=len(first.entries),
                dictionaries=len(self.tabs),
                active=first.name
            )
        else:
            self.statusbar.update_status(entries=0, dictionaries=0, active="None", unsaved=0)

    # ------------------------------------------------------------
    # Add Entry
    # ------------------------------------------------------------
    def _open_add_entry_dialog(self):
        if not self.tabs:
            return
        active_tab = self._get_active_tab()
        if not active_tab:
            return
        active_tab._open_add_dialog()

    # ------------------------------------------------------------
    # Edit Entry
    # ------------------------------------------------------------
    def _open_edit_entry_dialog(self):
        if not self.tabs:
            return
        active_tab = self._get_active_tab()
        if not active_tab:
            return
        active_tab._open_edit_dialog_for_selected()

    # ------------------------------------------------------------
    # Find & Replace
    # ------------------------------------------------------------
    def _open_find_replace(self):
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            self._find_replace_dlg.lift()
            self._find_replace_dlg.focus()
            return
        self._find_replace_dlg = FindReplaceDialog(self, self._get_active_tab)

    # ------------------------------------------------------------
    # Toggle Bookmark
    # ------------------------------------------------------------
    def _toggle_bookmark(self):
        tab = self._get_active_tab()
        if tab:
            tab.toggle_bookmark_selected()

    # ------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------
    def _undo(self):
        tab = self._get_active_tab()
        if tab:
            tab.undo()
            self._refresh_undo_buttons()

    def _redo(self):
        tab = self._get_active_tab()
        if tab:
            tab.redo()
            self._refresh_undo_buttons()

    def _refresh_undo_buttons(self):
        """Sync the toolbar undo/redo button states with the active tab's stack."""
        tab = self._get_active_tab()
        if tab and hasattr(tab, "_undo_stack"):
            self.toolbar.refresh_undo_redo(
                can_undo=tab._undo_stack.can_undo,
                can_redo=tab._undo_stack.can_redo,
            )
        else:
            self.toolbar.refresh_undo_redo(can_undo=False, can_redo=False)

    # ------------------------------------------------------------
    # Delete (menu / accelerator route)
    # ------------------------------------------------------------
    def _delete_selected(self):
        tab = self._get_active_tab()
        if tab:
            tab.delete_selected()

    # ------------------------------------------------------------
    # Entries changed (callback from DictionaryTab)
    # ------------------------------------------------------------
    def _on_entries_changed(self, count):
        self.statusbar.update_status(entries=count)
        self._refresh_unsaved_status()

    def _count_dirty_tabs(self) -> int:
        return sum(1 for t in self.tabs.values() if getattr(t, "_json_dirty", False))

    def _refresh_unsaved_status(self):
        self.statusbar.update_status(unsaved=self._count_dirty_tabs())

    def _poll_statusbar(self):
        # Keep unsaved count and undo button states current even when edits
        # happen deep in tab/dialog logic.
        self._refresh_unsaved_status()
        self._refresh_undo_buttons()
        self.after(400, self._poll_statusbar)

    def _save_all_dictionaries(self):
        dirty_tabs = [t for t in self.tabs.values()
                      if getattr(t, "_json_dirty", False) and getattr(t, "dict_path", None)]
        if not dirty_tabs:
            return

        failed = []
        for tab in dirty_tabs:
            try:
                saved = tab.save_json()
            except Exception as e:
                failed.append((tab, str(e)))
                continue
            if not saved:
                failed.append((tab, "Save was cancelled or failed."))

        if failed:
            messagebox.showerror(
                "Save All",
                "Some dictionaries could not be saved:\n\n" +
                "\n".join(f"- {getattr(tab, 'name', 'dictionary')}: {err}" for tab, err in failed),
            )

        if len(failed) < len(dirty_tabs):
            self.statusbar.update_status(saved=datetime.now().strftime("%H:%M"))
        self._refresh_unsaved_status()

    def _find_next_global(self):
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            self._find_replace_dlg._find_next()
            self._find_replace_dlg.lift()
            return "break"
        self._open_find_replace()
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            self._find_replace_dlg._find_next()
        return "break"

    def _find_prev_global(self):
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            self._find_replace_dlg._find_prev()
            self._find_replace_dlg.lift()
            return "break"
        self._open_find_replace()
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            self._find_replace_dlg._find_prev()
        return "break"

    def _clear_active_filters(self):
        tab = self._get_active_tab()
        if tab is None:
            return
        for attr in (
            "filter_has_comments", "filter_is_brief", "filter_bookmarked",
            "filter_capitalised", "filter_has_digits", "filter_has_written_numbers",
            "filter_has_punctuation", "filter_conflicts",
            "filter_has_frequency", "filter_top_freq",
        ):
            var = getattr(tab, attr, None)
            if var is not None:
                try:
                    var.set(False)
                except Exception:
                    pass
        try:
            tab._apply_filters()
        except Exception:
            pass

    # ------------------------------------------------------------
    # Tab persistence
    # ------------------------------------------------------------
    def _save_open_tabs(self):
        paths = []
        for tab_id in self.notebook.tabs():
            try:
                widget = self.notebook.nametowidget(tab_id)
                if hasattr(widget, "dict_path") and widget.dict_path:
                    paths.append(widget.dict_path)
            except Exception:
                continue
        settings = load_settings()
        settings["open_tabs"] = paths
        save_settings(settings)

    def _restore_open_tabs(self):
        settings = load_settings()
        for path in settings.get("open_tabs", []):
            try:
                self._open_dictionary_path(path)
            except Exception:
                pass

    def _on_close(self):
        """
        Close the application.  Prompt about any tabs with unsaved JSON
        changes; the user can save the ones they want, discard everything,
        or cancel and stay open.

        Tabs with no dirty JSON state never enter the prompt — they're
        already in sync with disk for their dictionaries, and metadata
        changes save immediately on edit, so they have nothing at risk.
        """
        from ui.save_changes_dialog import (
            ask_save_changes, RESULT_SAVE, RESULT_DISCARD, RESULT_CANCEL,
        )

        # Find dirty tabs in the order they appear in the notebook
        dirty_widgets = []
        for tab_id in self.notebook.tabs():
            try:
                w = self.notebook.nametowidget(tab_id)
            except Exception:
                continue
            if getattr(w, "_json_dirty", False) and getattr(w, "dict_path", None):
                dirty_widgets.append(w)

        if dirty_widgets:
            paths = [w.dict_path for w in dirty_widgets]
            result, to_save = ask_save_changes(self, paths, context="exit")
            if result == RESULT_CANCEL:
                return  # user changed their mind; stay open
            if result == RESULT_SAVE:
                save_set = set(to_save)
                for w in dirty_widgets:
                    if w.dict_path in save_set:
                        try:
                            saved = w.save_json()
                        except Exception as e:
                            saved = False
                            err = str(e)
                        else:
                            err = "Save was cancelled or failed."
                        if not saved:
                            cont = messagebox.askyesno(
                                "Save Failed",
                                f"Could not save "
                                f"{os.path.basename(w.dict_path)}:\n\n{err}\n\n"
                                f"Continue closing anyway?",
                            )
                            if not cont:
                                return

        self._save_open_tabs()
        self._refresh_unsaved_status()
        self.destroy()

    # ------------------------------------------------------------
    # Search
    # ------------------------------------------------------------
    def _on_search_update(self, config):
        self._apply_search_to_tabs(config)

    def _apply_search_to_tabs(self, config):
        """
        Route a search config to one or all tabs depending on Scope.

        Scope = "Current Dictionary": only the active tab is filtered.
        Other tabs are left in their existing filtered state — they're not
        visible, so it doesn't matter what their tree looks like, and
        running the filter pipeline against them per keystroke is wasted
        work.  When the user switches tabs, _on_tab_changed re-applies the
        current search to whichever tab they switched to, so the active
        tab is always in sync with the search bar.

        Scope = "All Dictionaries": every open tab applies the same search.
        Cross-tab consistency is the explicit point, so the cost is
        justified — but it does mean a keystroke can be slow when many
        large dictionaries are open.  Acceptable tradeoff for the use case.
        """
        if not self.tabs:
            return

        scope = (config or {}).get("scope", "Current Dictionary")

        if scope == "All Dictionaries":
            for tab in self.tabs.values():
                try:
                    tab.apply_search(config)
                except Exception:
                    pass
        else:
            active_tab = self._get_active_tab()
            if active_tab is None:
                return
            try:
                active_tab.apply_search(config)
            except Exception:
                pass

    def _on_search_collapse_changed(self, collapsed: bool):
        """Persist the search panel collapse state."""
        self._search_collapsed = collapsed
        settings = load_settings()
        settings["search_collapsed"] = collapsed
        save_settings(settings)

    def _on_filter_count_changed(self, _showing: int, _total: int, search_active: bool):
        """
        Surface a 'no matches' hint on the collapsed search panel.

        Called from every tab that re-runs its filters.  We only listen to the
        active tab — when scope is 'All Dictionaries' every tab fires this
        callback, but the hint should reflect what the user is actively looking
        at, not whichever tab happened to fire last.  The incoming _showing/_total
        arguments are therefore ignored in favour of a fresh read from the active
        tab.
        """
        active = self._get_active_tab()
        if active is None:
            return
        try:
            visible = len(active.filtered_entries)
            total   = len(active.entries)
        except AttributeError:
            return

        cfg = self.searchbar.get_config()
        active_search = bool(cfg.get("steno_query") or cfg.get("text_query"))

        if active_search and visible == 0:
            self.searchbar.set_count_hint("no matches")
            self.searchbar.set_no_match_actions([
                ("Clear search", self.searchbar.clear),
                ("Search all", lambda: self.searchbar.set_scope("All Dictionaries")),
                ("Clear filters", self._clear_active_filters),
            ])
        else:
            self.searchbar.set_count_hint("")
            self.searchbar.set_no_match_actions([])

    # ------------------------------------------------------------
    # Type-ahead routing
    # ------------------------------------------------------------
    # Keysyms we never want to route through to the search box - navigation,
    # editing, modifier, and function keys.
    _NON_TYPING_KEYSYMS = frozenset({
        "Tab", "ISO_Left_Tab",
        "Shift_L", "Shift_R", "Control_L", "Control_R",
        "Alt_L", "Alt_R", "Meta_L", "Meta_R",
        "Caps_Lock", "Num_Lock", "Scroll_Lock",
        "Escape", "Return", "KP_Enter", "BackSpace", "Delete",
        "Up", "Down", "Left", "Right",
        "Home", "End", "Page_Up", "Page_Down",
        "Insert", "Print", "Pause", "Menu",
    })

    def _maybe_route_type_ahead(self, event):
        """Route bare letter/digit keystrokes to the Text search field."""
        if not self.tabs:
            return None

        # Skip if focus is already in an input or the menu.  When no widget
        # has focus at all (e.g. after the window first appears, or briefly
        # when the user clicks on empty chrome), we still want to route the
        # keystroke - nothing else is going to consume it.
        focus = self.focus_get()
        if focus is not None:
            try:
                cls = focus.winfo_class()
            except tk.TclError:
                cls = None
            if cls in ("Entry", "TEntry", "Text", "TCombobox",
                       "Spinbox", "Listbox", "Menu"):
                return None

        keysym = event.keysym
        if keysym in self._NON_TYPING_KEYSYMS:
            return None
        if keysym.startswith("F") and keysym[1:].isdigit():   # F1–F12
            return None

        # Ignore Ctrl-* and Alt-* — those are application shortcuts.
        # Control bit is 0x4 on all platforms.
        # Alt bits differ: 0x8 on Windows, 0x80 on Linux/macOS, 0x20000 also
        # seen on some Windows builds.  Check all three to be safe.
        if event.state & 0x0004:
            return None
        if event.state & (0x0008 | 0x0080 | 0x20000):
            return None

        char = event.char
        if not char or not char.isprintable():
            return None

        # Route: focus Text entry (expanding panel if collapsed) and let the
        # search bar insert the char at the right moment in the animation.
        # We must NOT also call .insert() ourselves - that would double-insert
        # when the panel is already open, and could land before focus settles
        # when the panel is expanding.
        self.searchbar.focus_text_entry(append_char=char)
        return "break"

    # ------------------------------------------------------------
    # Theme toggle
    # ------------------------------------------------------------
    def _toggle_theme(self):
        """Switch between dark and light mode and persist the choice."""
        window_state, window_geometry = self._snapshot_window_geometry()
        column_widths = self._snapshot_column_widths()

        self._theme_mode = "dark" if self.dark_mode_var.get() else "light"
        apply_theme(self, self._theme_mode)
        self.after_idle(lambda: self._restore_after_theme_switch(
            window_state, window_geometry, column_widths,
        ))

        # Update Find & Replace if it happens to be open - apply_theme already
        # walked the main window's tree, but a non-modal Toplevel is a separate
        # tree, so we refresh it explicitly.
        if self._find_replace_dlg and self._find_replace_dlg.winfo_exists():
            from ui.theme import refresh_theme_recursive
            refresh_theme_recursive(self._find_replace_dlg)
            set_titlebar_dark(self._find_replace_dlg,
                              dark=(self._theme_mode == "dark"))

        # Persist
        settings = load_settings()
        settings["theme"] = self._theme_mode
        save_settings(settings)

    def _snapshot_window_geometry(self):
        try:
            return self.state(), self.geometry()
        except tk.TclError:
            return "normal", None

    def _snapshot_column_widths(self):
        out = {}
        for tab in self.tabs.values():
            tree = getattr(tab, "tree", None)
            if tree is None:
                continue
            try:
                out[tab] = {
                    col: tree.column(col, "width")
                    for col in getattr(tab, "column_order", [])
                }
            except tk.TclError:
                pass
        return out

    def _restore_after_theme_switch(self, window_state, window_geometry, column_widths):
        for tab, widths in column_widths.items():
            tree = getattr(tab, "tree", None)
            if tree is None:
                continue
            for col, width in widths.items():
                try:
                    tree.column(col, width=width)
                except tk.TclError:
                    pass
            try:
                tab.column_widths.update(widths)
            except Exception:
                pass

        try:
            if window_state == "zoomed":
                self.state("zoomed")
            elif window_geometry:
                self.geometry(window_geometry)
        except tk.TclError:
            pass

    # ------------------------------------------------------------
    # Tools → Open Metadata Folder
    # ------------------------------------------------------------
    def _open_metadata_folder(self):
        self._open_folder_in_explorer(METADATA_ROOT)

    # ------------------------------------------------------------
    # Tools → Open Backup Folder
    # ------------------------------------------------------------
    def _open_backup_folder(self):
        from logic.backup_store import BACKUP_ROOT
        self._open_folder_in_explorer(BACKUP_ROOT)

    def _open_folder_in_explorer(self, path):
        """Cross-platform best-effort folder opener.  Silent on failure."""
        import platform
        try:
            os.makedirs(path, exist_ok=True)
            system = platform.system()
            if system == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    # ------------------------------------------------------------
    # Tools → Set Display Limit
    # ------------------------------------------------------------
    def _set_display_limit(self):
        """
        Open the dialog, persist the new value, push it into the module
        constant, and re-render every open tab so the change is visible
        immediately.
        """
        from ui.display_limit_dialog import ask_display_limit
        from ui import dictionary_tab as _dt_module

        new_value = ask_display_limit(self, _dt_module.MAX_DISPLAY_ROWS)
        if new_value is None:
            return

        _dt_module.MAX_DISPLAY_ROWS = new_value

        settings = load_settings()
        settings["max_display_rows"] = new_value
        save_settings(settings)

        # Re-render every open tab so the new cap takes immediate effect.
        # Inactive tabs aren't visible right now but will render correctly
        # on tab activation; rebuilding them now is cheap relative to the
        # work the user just did to think about this setting.
        for tab in self.tabs.values():
            try:
                tab._apply_filters()
            except Exception:
                pass

    # ------------------------------------------------------------
    # Tools → Restore Backup
    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # Tools -> Import Frequency List
    # ------------------------------------------------------------
    def _load_frequency_map_from_user(self, title: str):
        choice = messagebox.askyesnocancel(
            title,
            "Use the default UK frequency list (BNC) from:\n\n"
            f"{DEFAULT_UK_FREQUENCY_URL}\n\n"
            "Choose Yes to download it now, No to pick a local file.",
        )
        if choice is None:
            return None, None

        if choice:
            text = download_frequency_text(DEFAULT_UK_FREQUENCY_URL)
            return parse_frequency_text(text), "UK BNC online list"

        path = filedialog.askopenfilename(
            parent=self,
            title="Select Frequency List",
            filetypes=[
                ("Text and CSV", "*.txt *.csv *.tsv"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return None, None
        return parse_frequency_file(path), os.path.basename(path)

    def _import_frequency_list(self):
        tab = self._get_active_tab()
        if tab is None or not getattr(tab, "dict_path", None):
            messagebox.showinfo(
                "Import Frequency List",
                "Open a dictionary first, then import frequency data.",
            )
            return

        try:
            freq_map, source = self._load_frequency_map_from_user("Import Frequency List")
        except Exception as e:
            messagebox.showerror(
                "Import Frequency List",
                f"Could not load frequency data:\n\n{e}",
            )
            return
        if freq_map is None:
            return

        if not freq_map:
            messagebox.showwarning(
                "Import Frequency List",
                "No usable frequency rows were found in that source.",
            )
            return

        updated = self._apply_frequency_map_to_tab(tab, freq_map)
        try:
            save_metadata(tab.dict_path, tab.metadata or {})
        except Exception as e:
            messagebox.showerror(
                "Import Frequency List",
                f"Imported frequencies but failed to save metadata:\n\n{e}",
            )
            return
        if hasattr(tab, "_refresh_dictionary_header"):
            tab._refresh_dictionary_header()

        try:
            tab._apply_filters()
        except Exception:
            pass

        self.statusbar.update_status(saved=datetime.now().strftime("%H:%M"))
        messagebox.showinfo(
            "Import Frequency List",
            f"Imported frequencies from {source}.\n"
            f"Updated {updated:,} entries.",
        )

    def _apply_frequency_map_to_tab(self, tab, freq_map: dict[str, int]) -> int:
        import re

        token_re = re.compile(r"[a-z']+")

        # A scoreable entry is a plain word containing only letters and
        # apostrophes.  Entries with digits, hyphens, punctuation, or Plover
        # formatting commands (e.g. {^ing}, {-|}) are excluded — they either
        # don't appear in a word-frequency list or would get a misleading score.
        plain_word_re = re.compile(r"^[a-z']+$")

        updated = 0
        metadata = tab.metadata if tab.metadata is not None else {}
        tab.metadata = metadata

        for entry in tab.entries:
            steno   = entry.get("steno", "")
            english = (entry.get("english") or "").lower().strip()
            tokens  = token_re.findall(english)

            # Score only single plain-word entries.
            # The plain_word_re check on the raw string catches cases where
            # token_re would silently strip out disqualifying characters
            # (e.g. "Hello!" → token ["hello"] but the raw string fails the
            # check, so score stays 0).
            if len(tokens) == 1 and plain_word_re.match(english):
                score = freq_map.get(tokens[0], 0)
            else:
                score = 0

            meta = metadata.setdefault(steno, {
                "date_added": entry.get("date_added", ""),
                "modified": entry.get("modified", ""),
                "brief": False,
                "comments": "",
                "bookmarked": False,
                "frequency": 0,
            })
            if meta.get("frequency", 0) != score:
                meta["frequency"] = score
                updated += 1

        return updated

    def _review_missing_frequency_words(self):
        tab = self._get_active_tab()
        if tab is None or not getattr(tab, "dict_path", None):
            messagebox.showinfo(
                "Review Missing Frequency Words",
                "Open a dictionary first, then review missing frequency words.",
            )
            return

        try:
            freq_map, source = self._load_frequency_map_from_user(
                "Review Missing Frequency Words"
            )
        except Exception as e:
            messagebox.showerror(
                "Review Missing Frequency Words",
                f"Could not load frequency data:\n\n{e}",
            )
            return
        if freq_map is None:
            return
        if not freq_map:
            messagebox.showwarning(
                "Review Missing Frequency Words",
                "No usable frequency rows were found in that source.",
            )
            return

        candidates, omitted_count = self._missing_frequency_candidates(tab, freq_map)
        if not candidates:
            messagebox.showinfo(
                "Review Missing Frequency Words",
                "No missing frequency words were found.",
            )
            return

        dlg = MissingFrequencyDialog(
            self,
            tab,
            candidates,
            source or "frequency list",
            omitted_count=omitted_count,
        )
        dlg.focus_set()

    def _missing_frequency_candidates(self, tab, freq_map: dict[str, int]):
        import re

        max_candidates = 1000
        plain_word_re = re.compile(r"^[a-z']+$")
        settings = load_settings()
        ignored = {
            str(word).strip().lower()
            for word in settings.get(IGNORED_WORDS_KEY, [])
            if str(word).strip()
        }

        existing = set()
        for entry in tab.entries:
            english = (entry.get("english") or "").strip().lower()
            if plain_word_re.match(english):
                existing.add(english)

        missing = []
        for word, freq in freq_map.items():
            if word in existing or word in ignored or not plain_word_re.match(word):
                continue
            hint = self._possible_suffix_coverage(word, existing)
            item = {"word": word, "frequency": freq}
            if hint:
                item["status"] = "Possibly Covered"
                item["note"] = hint
            missing.append(item)
        missing.sort(key=lambda item: (-item["frequency"], item["word"]))
        omitted_count = max(0, len(missing) - max_candidates)
        return missing[:max_candidates], omitted_count

    def _possible_suffix_coverage(self, word: str, existing: set[str]) -> str:
        checks = []

        if word.endswith("ies") and len(word) > 3:
            checks.append((word[:-3] + "y", "y + ies suffix"))
        if word.endswith("es") and len(word) > 2:
            checks.append((word[:-2], "base + es suffix"))
        if word.endswith("s") and len(word) > 1:
            checks.append((word[:-1], "base + s suffix"))

        if word.endswith("ied") and len(word) > 3:
            checks.append((word[:-3] + "y", "y + ied suffix"))
        if word.endswith("ed") and len(word) > 2:
            checks.append((word[:-2], "base + ed suffix"))
            if len(word) > 3 and word[-3] == word[-4]:
                checks.append((word[:-3], "doubled consonant + ed suffix"))

        if word.endswith("ing") and len(word) > 3:
            checks.append((word[:-3], "base + ing suffix"))
            checks.append((word[:-3] + "e", "drop e + ing suffix"))
            if len(word) > 4 and word[-4] == word[-5]:
                checks.append((word[:-4], "doubled consonant + ing suffix"))

        for suffix in ("ly", "er", "est"):
            if word.endswith(suffix) and len(word) > len(suffix):
                checks.append((word[:-len(suffix)], f"base + {suffix} suffix"))

        seen = set()
        for base, label in checks:
            if not base or base in seen:
                continue
            seen.add(base)
            if base in existing:
                return f"{base} ({label})"
        return ""

    def _manage_ignored_frequency_words(self):
        dlg = IgnoredFrequencyWordsDialog(self)
        self.wait_window(dlg)

    def _restore_backup(self):
        """
        Show the restore dialog, then replace the active dictionary's file
        with the chosen backup and reload the tab.

        The current state is itself backed up first, so the user can undo
        a wrong restore by restoring the snapshot taken at the moment
        before the restore.
        """
        from ui.restore_backup_dialog import RestoreBackupDialog
        from logic.backup_store import backup_dictionary
        import shutil

        tab = self._get_active_tab()
        if tab is None or not getattr(tab, "dict_path", None):
            messagebox.showinfo(
                "Restore Backup",
                "Open a dictionary first, then choose Tools → Restore Backup.",
            )
            return

        # Warn before overwriting unsaved JSON edits
        if getattr(tab, "_json_dirty", False):
            ok = messagebox.askyesno(
                "Unsaved Changes",
                f"{os.path.basename(tab.dict_path)} has unsaved changes that "
                f"will be lost if you restore a backup.\n\n"
                f"Continue?",
            )
            if not ok:
                return

        dlg = RestoreBackupDialog(self, tab.dict_path)
        self.wait_window(dlg)
        if dlg.selected_backup is None:
            return  # user cancelled

        # Confirmation - show the restore target so they know what they're doing
        backup = dlg.selected_backup
        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Replace {os.path.basename(tab.dict_path)} with the backup from "
            f"{backup['timestamp']}?\n\n"
            f"A new backup of the current state will be made first, so this "
            f"is reversible.",
        )
        if not confirm:
            return

        # Snapshot current state before replacing
        try:
            ok, msg = backup_dictionary(tab.dict_path, kind="save")
        except Exception as e:
            ok, msg = False, str(e)
        if not ok:
            # If the safety backup fails, ask before continuing
            cont = messagebox.askyesno(
                "Backup Failed",
                f"Could not back up the current dictionary before restoring:\n\n{msg}\n\n"
                "Restore anyway?",
            )
            if not cont:
                return

        # Copy the backup's dictionary file into place
        try:
            shutil.copy2(backup["dict_path"], tab.dict_path)
        except OSError as e:
            messagebox.showerror(
                "Restore Failed",
                f"Could not restore backup:\n\n{e}",
            )
            return

        # Restore the matching metadata sidecar if it exists.  If the chosen
        # backup has no metadata, remove current metadata so stale comments,
        # brief flags, dates, or frequencies do not leak into the restored file.
        try:
            from logic.metadata_store import _metadata_file_for, _metadata_files_for_all_locations
            meta_dst = _metadata_file_for(tab.dict_path)
            if backup.get("metadata_path"):
                shutil.copy2(backup["metadata_path"], meta_dst)
            else:
                for stale_meta in _metadata_files_for_all_locations(tab.dict_path):
                    try:
                        if os.path.exists(stale_meta):
                            os.remove(stale_meta)
                    except OSError:
                        pass
        except OSError:
            # Non-fatal - the dictionary itself restored fine
            pass

        # Reload the tab from the restored file
        try:
            entries, metadata, _ = load_dictionary_with_metadata(tab.dict_path)
            tab.load_entries(entries, metadata)
            tab._set_dirty(False)
            tab.apply_search(self.searchbar.get_config())
            self.statusbar.update_status(
                entries=len(entries),
                dictionaries=len(self.tabs),
                active=tab.name,
            )
        except Exception as e:
            messagebox.showerror(
                "Reload Failed",
                f"The file was restored but could not be reloaded:\n\n{e}\n\n"
                f"Try closing and reopening the dictionary.",
            )
            return

        messagebox.showinfo(
            "Restore Complete",
            f"Restored {os.path.basename(tab.dict_path)} from backup "
            f"{backup['timestamp']}.",
        )


if __name__ == "__main__":
    app = StenoApp()
    app.mainloop()
