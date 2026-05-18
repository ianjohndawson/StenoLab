# logic/undo_stack.py
"""
Per-dictionary-tab undo/redo stack.

Frames are plain dicts with an 'op' key ('add', 'edit', 'delete') and
whatever data is needed to reverse or replay the operation.  The stack
tracks a "dirty delta" relative to the last save so it can tell callers
whether the current in-memory state matches what is on disk — even after
a series of undos and redos.
"""


class UndoStack:
    def __init__(self):
        self._undo: list = []   # oldest frame at index 0, newest at end
        self._redo: list = []   # most-recently-undone frame at end
        # Distance from the last-saved state.  0 means "matches disk".
        # Positive = unsaved edits on top.  Negative = undone past last save.
        self._dirty_delta: int = 0

    # ── State queries ───────────────────────────────────────────────────

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def is_dirty(self) -> bool:
        """True when the current state differs from the last saved state."""
        return self._dirty_delta != 0

    # ── Mutation ────────────────────────────────────────────────────────

    def push(self, frame: dict) -> None:
        """Record a new undoable operation.  Clears the redo stack."""
        self._undo.append(frame)
        self._redo.clear()
        self._dirty_delta += 1

    def mark_saved(self) -> None:
        """
        Call immediately after a successful save.  Resets the dirty delta
        so that undoing all the way back to this point will clear the
        dirty flag correctly.
        """
        self._dirty_delta = 0

    def clear(self) -> None:
        """Discard all history.  Called when a dictionary is (re)loaded."""
        self._undo.clear()
        self._redo.clear()
        self._dirty_delta = 0

    def pop_undo(self) -> dict | None:
        """
        Move the top undo frame to the redo stack and return it.
        Returns None when there is nothing to undo.
        """
        if not self._undo:
            return None
        frame = self._undo.pop()
        self._redo.append(frame)
        self._dirty_delta -= 1
        return frame

    def pop_redo(self) -> dict | None:
        """
        Move the top redo frame back onto the undo stack and return it.
        Returns None when there is nothing to redo.
        """
        if not self._redo:
            return None
        frame = self._redo.pop()
        self._undo.append(frame)
        self._dirty_delta += 1
        return frame
