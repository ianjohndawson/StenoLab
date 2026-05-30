# ui/theme.py
"""
Unified theming for Steno Editor.

Two palettes - DARK and LIGHT - share identical keys, so any code that reads
from the live palette `C` automatically gets correct colours after a switch.

`C` is mutated in place rather than rebound, so existing imports of the form

    from ui.theme import C

continue to see live values without any change to call sites.

Public API:
    apply_steno_theme(root, mode)      one-shot setup (call once at startup)
    apply_theme(root, mode)            switch palette at runtime
    set_titlebar_dark(window, dark)    Windows DWM dark title bar (no-op elsewhere)
    refresh_theme_recursive(root)      walk widget tree calling refresh_theme()
"""
import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
DARK = {
    "bg":                       "#17191f",
    "bg_panel":                 "#222630",
    "bg_input":                 "#303646",
    "bg_raised":                "#2b3140",
    "bg_card":                  "#262c38",
    "bg_card_alt":              "#1d222c",
    "bg_alt":                   "#1c2029",   # zebra alt row
    "fg":                       "#f0eee8",
    "fg_dim":                   "#aeb4bf",
    "accent":                   "#35bdb4",
    "accent_hover":             "#52d4cc",
    "accent_soft":              "#163f44",
    "success":                  "#63c978",
    "success_soft":             "#1c3929",
    "warning":                  "#f0b85a",
    "warning_soft":             "#3f3019",
    "danger":                   "#ef707f",
    "danger_soft":              "#44202a",
    "info":                     "#7aa7ff",
    "info_soft":                "#202f52",
    "border":                   "#3a4354",
    # Treeview row state colours
    "bookmark_bg":              "#23351e",
    "bookmark_fg":              "#b5df72",
    "conflict_bg":              "#3d1d29",
    "conflict_fg":              "#ff8a98",
    "bookmarked_conflict_bg":   "#3f3219",
    "bookmarked_conflict_fg":   "#f3c96a",
    "find_match_bg":            "#143f49",
    "find_match_fg":            "#93f1ec",
}

LIGHT = {
    "bg":                       "#f2f4f7",
    "bg_panel":                 "#ffffff",
    "bg_input":                 "#ffffff",
    "bg_raised":                "#e8edf3",
    "bg_card":                  "#ffffff",
    "bg_card_alt":              "#eef3f8",
    "bg_alt":                   "#f7f9fb",
    "fg":                       "#1f252c",
    "fg_dim":                   "#66717e",
    "accent":                   "#178f88",
    "accent_hover":             "#21aaa1",
    "accent_soft":              "#d8f2ef",
    "success":                  "#2d8f4a",
    "success_soft":             "#dff3e6",
    "warning":                  "#b87918",
    "warning_soft":             "#fff0cf",
    "danger":                   "#c93d51",
    "danger_soft":              "#fbe1e6",
    "info":                     "#386ed8",
    "info_soft":                "#dfe9ff",
    "border":                   "#d2dae5",
    "bookmark_bg":              "#e3f4cf",
    "bookmark_fg":              "#3f741d",
    "conflict_bg":              "#fbe1e6",
    "conflict_fg":              "#b72d43",
    "bookmarked_conflict_bg":   "#fff0cf",
    "bookmarked_conflict_fg":   "#8a5b12",
    "find_match_bg":            "#d8f2ef",
    "find_match_fg":            "#075d5a",
}

# Live palette - mutated in place so all `from ui.theme import C` imports
# automatically see updates.
C = dict(DARK)

# Tracks the currently active mode so callers can query without re-reading settings.
_current_mode = "dark"


def get_mode() -> str:
    return _current_mode


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def apply_steno_theme(root: tk.Tk, mode: str = "dark"):
    """One-time theme setup.  Call once during app construction."""
    style = ttk.Style(root)

    # Use clam as the base - we layer all our settings on top via configure().
    # This pattern (vs theme_create) means we can re-apply on switch without
    # hitting ttk's "theme already exists" error.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    apply_theme(root, mode)


def apply_theme(root: tk.Tk, mode: str):
    """Switch between dark and light at runtime (or apply for the first time)."""
    global _current_mode
    mode = "light" if mode == "light" else "dark"
    _current_mode = mode

    palette = LIGHT if mode == "light" else DARK

    # Mutate C in place so all importers see the change
    C.clear()
    C.update(palette)

    style = ttk.Style(root)
    _configure_styles(style)

    root.configure(bg=C["bg"])

    # Combobox dropdown is a legacy Tk Listbox - styled via option_add
    root.option_add("*TCombobox*Listbox.background",       C["bg_input"])
    root.option_add("*TCombobox*Listbox.foreground",       C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.option_add("*TCombobox*Listbox.font",             '"Segoe UI" 10')

    # OS title bar (Windows only)
    _apply_titlebar_to_all(root, dark=(mode == "dark"))

    # Walk the widget tree calling refresh_theme() on any custom widget
    refresh_theme_recursive(root)


def refresh_theme_recursive(widget):
    """Call refresh_theme() on widget and all descendants if defined."""
    fn = getattr(widget, "refresh_theme", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        refresh_theme_recursive(child)


# ---------------------------------------------------------------------------
# ttk style configuration
# ---------------------------------------------------------------------------
def _configure_styles(style: ttk.Style):
    """Apply all element settings using the live palette C."""

    style.configure("TFrame",
                    background=C["bg_panel"],
                    borderwidth=0)

    style.configure("TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg"],
                    font=("Segoe UI", 10))

    style.configure("AppShell.TFrame",
                    background=C["bg"])
    style.configure("Card.TFrame",
                    background=C["bg_card"],
                    borderwidth=1,
                    bordercolor=C["border"],
                    relief="solid")
    style.configure("CardAlt.TFrame",
                    background=C["bg_card_alt"],
                    borderwidth=1,
                    bordercolor=C["border"],
                    relief="solid")
    style.configure("Card.TLabel",
                    background=C["bg_card"],
                    foreground=C["fg"],
                    font=("Segoe UI", 10))
    style.configure("CardTitle.TLabel",
                    background=C["bg_card"],
                    foreground=C["fg"],
                    font=("Segoe UI", 20, "bold"))
    style.configure("CardSectionTitle.TLabel",
                    background=C["bg_card"],
                    foreground=C["fg"],
                    font=("Segoe UI", 11, "bold"))
    style.configure("CardItem.TLabel",
                    background=C["bg_card"],
                    foreground=C["accent"],
                    font=("Segoe UI", 10, "bold"))
    style.configure("CardSubtitle.TLabel",
                    background=C["bg_card"],
                    foreground=C["fg_dim"],
                    font=("Segoe UI", 10))
    style.configure("CardActions.TFrame",
                    background=C["bg_card"])
    style.configure("Muted.TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg_dim"],
                    font=("Segoe UI", 9))
    style.configure("Disclosure.TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg"],
                    font=("Segoe UI", 10, "bold"))
    style.configure("Chip.TLabel",
                    background=C["accent_soft"],
                    foreground=C["accent"],
                    padding=(6, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("Badge.TLabel",
                    background=C["bg_raised"],
                    foreground=C["fg"],
                    padding=(7, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("DangerBadge.TLabel",
                    background=C["danger_soft"],
                    foreground=C["danger"],
                    padding=(7, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("SuccessBadge.TLabel",
                    background=C["success_soft"],
                    foreground=C["success"],
                    padding=(7, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("Toolbar.TFrame",
                    background=C["bg"],
                    borderwidth=0,
                    relief="flat")
    style.configure("ToolbarGroup.TFrame",
                    background=C["bg"])
    style.configure("ToolbarSeparator.TFrame",
                    background=C["border"])
    style.configure("ToolbarLabel.TLabel",
                    background=C["bg_card"],
                    foreground=C["fg_dim"],
                    font=("Segoe UI", 9, "bold"))

    style.configure("TButton",
                    background=C["bg_raised"],
                    foreground=C["fg"],
                    padding=(8, 4),
                    borderwidth=1,
                    bordercolor=C["border"])
    style.map("TButton",
              background=[("active", C["accent_hover"])],
              foreground=[("active", "white")])

    style.configure("Primary.TButton",
                    background=C["accent"],
                    foreground="white",
                    padding=(10, 5),
                    borderwidth=0,
                    font=("Segoe UI", 10))
    style.map("Primary.TButton",
              background=[("active", C["accent_hover"]),
                          ("pressed", C["accent_hover"]),
                          ("disabled", C["bg_raised"])],
              foreground=[("disabled", C["fg_dim"])])

    style.configure("Secondary.TButton",
                    background=C["bg_card"],
                    foreground=C["fg"],
                    padding=(10, 5),
                    borderwidth=1,
                    bordercolor=C["border"],
                    font=("Segoe UI", 10))
    style.map("Secondary.TButton",
              background=[("active", C["bg_raised"]),
                          ("pressed", C["bg_raised"])],
              foreground=[("disabled", C["fg_dim"])])

    # Compact inline button for toolbars and form rows (e.g. Clear).
    style.configure("Compact.TButton",
                    background=C["bg_panel"],
                    foreground=C["fg_dim"],
                    padding=(8, 2),
                    borderwidth=1,
                    bordercolor=C["border"],
                    font=("Segoe UI", 9))
    style.map("Compact.TButton",
              background=[("active", C["bg_raised"])],
              foreground=[("active", C["fg"])])

    style.configure("Link.TButton",
                    background=C["bg_panel"],
                    foreground=C["accent"],
                    padding=(2, 0),
                    borderwidth=0,
                    font=("Segoe UI", 9, "underline"))
    style.map("Link.TButton",
              foreground=[("active", C["accent_hover"]), ("disabled", C["fg_dim"])],
              background=[("active", C["bg_panel"])])

    # Pill / chip button used for active search and filter indicators.
    # Reads as a soft-tinted capsule with a small "×" remove affordance.
    style.configure("Chip.TButton",
                    background=C["accent_soft"],
                    foreground=C["accent"],
                    padding=(6, 1),
                    borderwidth=0,
                    font=("Segoe UI", 9, "bold"))
    style.map("Chip.TButton",
              background=[("active", C["bg_raised"])],
              foreground=[("active", C["fg"])])

    style.configure("StatusBar.TFrame",
                    background=C["bg"],
                    borderwidth=0)
    style.configure("StatusBarDivider.TFrame",
                    background=C["bg_raised"],
                    borderwidth=0)
    style.configure("StatusBar.TLabel",
                    background=C["bg"],
                    foreground=C["fg_dim"],
                    font=("Segoe UI", 9))
    style.configure("StatusBarDivider.TLabel",
                    background=C["bg"],
                    foreground=C["border"],
                    font=("Segoe UI", 9))

    style.configure("DictionaryHeader.TFrame",
                    background=C["bg_panel"],
                    borderwidth=1,
                    bordercolor=C["border"],
                    relief="solid")
    style.configure("DictionaryHeaderBody.TFrame",
                    background=C["bg_panel"])
    style.configure("HeaderAccent.TFrame",
                    background=C["accent"])

    # Unified Search & Filters bar.  Only the outer container draws a
    # border; all nested rows are borderless so controls do not appear to
    # overlap internal outlines.
    style.configure("UnifiedBar.TFrame",
                    background=C["bg_panel"],
                    borderwidth=1,
                    bordercolor=C["border"],
                    relief="solid")
    style.configure("UnifiedBarInner.TFrame",
                    background=C["bg_panel"],
                    borderwidth=0,
                    relief="flat")
    style.configure("UnifiedBar.TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg"])
    style.configure("UnifiedBar.TCheckbutton",
                    background=C["bg_panel"],
                    foreground=C["fg"],
                    focuscolor=C["bg_panel"],
                    padding=(0, 4))
    style.map("UnifiedBar.TCheckbutton",
              background=[("active", C["bg_panel"])],
              foreground=[("disabled", C["fg_dim"])])
    style.configure("WarningBadge.TLabel",
                    background=C["warning_soft"],
                    foreground=C["warning"],
                    padding=(8, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("HeaderTitle.TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg"],
                    font=("Segoe UI", 14, "bold"))
    style.configure("HeaderSubtle.TLabel",
                    background=C["bg_panel"],
                    foreground=C["fg_dim"],
                    font=("Segoe UI", 9))
    style.configure("HeaderChip.TLabel",
                    background=C["bg_raised"],
                    foreground=C["fg"],
                    padding=(6, 2),
                    font=("Segoe UI", 9))
    style.configure("HeaderInfo.TLabel",
                    background=C["info_soft"],
                    foreground=C["info"],
                    padding=(6, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("HeaderSuccess.TLabel",
                    background=C["success_soft"],
                    foreground=C["success"],
                    padding=(6, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("HeaderWarning.TLabel",
                    background=C["warning_soft"],
                    foreground=C["warning"],
                    padding=(6, 2),
                    font=("Segoe UI", 9, "bold"))
    style.configure("HeaderDanger.TLabel",
                    background=C["danger_soft"],
                    foreground=C["danger"],
                    padding=(6, 2),
                    font=("Segoe UI", 9, "bold"))

    # Generic icon button (used for compact icon-only buttons elsewhere).
    style.configure("Icon.TButton",
                    background=C["bg_card"],
                    foreground=C["fg"],
                    font=("Segoe UI Symbol", 13),
                    padding=(9, 6),
                    width=2,
                    borderwidth=0)
    style.map("Icon.TButton",
              background=[("active", C["bg_raised"]),
                          ("pressed", C["accent"])],
              foreground=[("active", C["fg"]),
                          ("pressed", "white"),
                          ("disabled", C["fg_dim"])])

    # Toolbar icon button — square, no border, very visible hover.
    # Hover paints the cell in accent_soft so the user can immediately see
    # which button is under the cursor.  Pressed/selected uses the accent
    # itself with a white glyph.
    style.configure("ToolbarIcon.TButton",
                    background=C["bg"],
                    foreground=C["fg"],
                    font=("Segoe UI Symbol", 14),
                    padding=(8, 5),
                    width=2,
                    borderwidth=0,
                    relief="flat",
                    focusthickness=0)
    style.map("ToolbarIcon.TButton",
              background=[("disabled", C["bg"]),
                          ("pressed",  C["accent"]),
                          ("active",   C["accent_soft"])],
              foreground=[("disabled", C["fg_dim"]),
                          ("pressed",  "white"),
                          ("active",   C["accent"])],
              relief=[("pressed", "flat"), ("active", "flat")])

    style.configure("TEntry",
                    fieldbackground=C["bg_input"],
                    foreground=C["fg"],
                    insertcolor=C["fg"],
                    bordercolor=C["border"],
                    lightcolor=C["bg_input"],
                    darkcolor=C["bg_input"])

    style.configure("TCombobox",
                    fieldbackground=C["bg_input"],
                    foreground=C["fg"],
                    background=C["bg_raised"],
                    arrowcolor=C["fg"],
                    bordercolor=C["border"],
                    lightcolor=C["bg_input"],
                    darkcolor=C["bg_input"],
                    selectbackground=C["accent"],
                    selectforeground="white")
    style.map("TCombobox",
              fieldbackground=[("readonly", C["bg_input"])],
              foreground=[("readonly", C["fg"])])

    style.configure("TCheckbutton",
                    background=C["bg_panel"],
                    foreground=C["fg"],
                    focuscolor=C["bg_panel"],
                    padding=2)
    style.map("TCheckbutton",
              background=[("active", C["bg_panel"])],
              foreground=[("disabled", C["fg_dim"])])

    style.configure("TScrollbar",
                    background=C["bg_raised"],
                    troughcolor=C["bg_panel"],
                    bordercolor=C["bg_panel"],
                    arrowcolor=C["fg_dim"],
                    darkcolor=C["bg_raised"],
                    lightcolor=C["bg_raised"])
    style.map("TScrollbar",
              background=[("active", C["accent"])])

    style.configure("TNotebook",
                    background=C["bg"],
                    tabmargins=[4, 4, 4, 0])

    # Redefine the tab layout to drop the Notebook.focus inner element. That
    # element introduces variable padding between selected and unselected
    # states on some Windows tk builds, which makes the selected tab appear
    # to shrink. With it removed, the selected/unselected geometry only
    # differs by what we set explicitly via the padding map below.
    style.layout("TNotebook.Tab", [
        ("Notebook.tab", {
            "sticky": "nswe",
            "children": [
                ("Notebook.padding", {
                    "side": "top",
                    "sticky": "nswe",
                    "children": [
                        ("Notebook.label", {"side": "top", "sticky": ""}),
                    ],
                }),
            ],
        }),
    ])

    style.configure("TNotebook.Tab",
                    background=C["bg_raised"],
                    foreground=C["fg_dim"],
                    padding=[14, 7],
                    borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", C["accent"]),
                          ("active",   C["bg_card"])],
              foreground=[("selected", "white"),
                          ("active",   C["fg"])],
              # Selected tab gets larger padding - this works regardless of
              # whether the platform respects 'expand' on Notebook.Tab.
              padding=[("selected", [16, 9])])

    style.configure("Treeview",
                    background=C["bg_panel"],
                    fieldbackground=C["bg_panel"],
                    foreground=C["fg"],
                    rowheight=27,
                    borderwidth=0)
    style.map("Treeview",
              background=[("selected", C["accent"])],
              foreground=[("selected", "white")])
    style.configure("Treeview.Heading",
                    background=C["bg_panel"],
                    foreground=C["fg_dim"],
                    padding=(8, 6),
                    relief="flat",
                    borderwidth=0,
                    font=("Segoe UI", 10, "bold"))
    style.map("Treeview.Heading",
              background=[("active", C["bg_raised"])],
              foreground=[("active", C["fg"])])

    style.configure("TSeparator",
                    background=C["border"])


# ---------------------------------------------------------------------------
# Windows DWM title bar
# ---------------------------------------------------------------------------
def set_titlebar_dark(window, dark: bool = True):
    """
    Toggle the OS-drawn title bar between dark and light on Windows 10/11.
    Silent no-op on macOS / Linux or older Windows builds.
    """
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)

        # Attribute 20 (DWMWA_USE_IMMERSIVE_DARK_MODE) on Windows 10 20H1+ / Win11.
        # Falls back to 19 for the brief window of Windows 10 builds 18985 - 19041.
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if result != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )

        # Do not withdraw/deiconify here.  It repaints the title bar, but on
        # Windows it can also drop maximized state and make stretchable table
        # columns recalculate.  The DWM attribute is applied immediately for
        # newly mapped windows, and existing windows pick it up on the next
        # normal non-client repaint.

    except (AttributeError, OSError, ImportError):
        # Not Windows, or DWM unavailable - silently skip
        pass


def _apply_titlebar_to_all(root, dark: bool):
    """Apply title-bar mode to root and any open Toplevels."""
    set_titlebar_dark(root, dark)
    try:
        children = root.winfo_children()
    except Exception:
        return
    for child in children:
        if isinstance(child, tk.Toplevel):
            set_titlebar_dark(child, dark)
