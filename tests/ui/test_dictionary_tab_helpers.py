from ui.dictionary_tab import DictionaryTab, MAX_DISPLAY_ROWS


class FakeTree:
    def __init__(self, children):
        self._children = tuple(children)

    def get_children(self):
        return self._children


def test_focus_column_order_keeps_daily_editing_columns_compact():
    assert DictionaryTab._make_column_order(show_freq=False, focus_mode=True) == [
        "steno",
        "english",
        "B",
    ]
    assert DictionaryTab._make_column_order(show_freq=True, focus_mode=True) == [
        "steno",
        "english",
        "B",
        "F",
    ]


def test_tree_item_mapping_accounts_for_pagination_offset():
    tab = object.__new__(DictionaryTab)
    tab._page = 1
    tab.tree = FakeTree(["row-0", "row-1"])
    tab.filtered_entries = [
        {"steno": f"S{i}", "english": f"word{i}"}
        for i in range(MAX_DISPLAY_ROWS + 2)
    ]

    assert tab._entry_for_tree_item("row-0") is tab.filtered_entries[MAX_DISPLAY_ROWS]
    assert tab._entry_for_tree_item("row-1") is tab.filtered_entries[MAX_DISPLAY_ROWS + 1]
    assert tab._entry_for_tree_item("missing") is None
