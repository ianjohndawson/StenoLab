from logic.steno_validator import validate_steno


def test_validates_common_single_and_multi_strokes():
    assert validate_steno("STKPWHR")[0]
    assert validate_steno("TPH/AEUPL")[0]
    assert validate_steno("STKPWRAO*EUFRPBLGTSDZ")[0]


def test_rejects_empty_whitespace_and_bad_characters():
    assert validate_steno("") == (False, "Steno cannot be empty.")
    ok, msg = validate_steno(" ST")
    assert not ok
    assert "whitespace" in msg
    ok, msg = validate_steno("ST!")
    assert not ok
    assert "Invalid character" in msg


def test_rejects_empty_stroke_and_duplicate_star():
    ok, msg = validate_steno("ST/")
    assert not ok
    assert "Empty stroke" in msg
    ok, msg = validate_steno("ST**")
    assert not ok
    assert "More than one" in msg
