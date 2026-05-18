from logic.undo_stack import UndoStack


def test_undo_redo_tracks_dirty_delta():
    stack = UndoStack()
    frame = {"op": "add"}

    stack.push(frame)
    assert stack.can_undo
    assert stack.is_dirty

    assert stack.pop_undo() == frame
    assert not stack.can_undo
    assert stack.can_redo
    assert not stack.is_dirty

    assert stack.pop_redo() == frame
    assert stack.can_undo
    assert stack.is_dirty


def test_mark_saved_and_clear_reset_state():
    stack = UndoStack()
    stack.push({"op": "add"})
    stack.mark_saved()
    assert not stack.is_dirty

    stack.pop_undo()
    assert stack.is_dirty

    stack.clear()
    assert not stack.can_undo
    assert not stack.can_redo
    assert not stack.is_dirty
