import json

import pytest

from logic.dictionary_loader import load_dictionary_with_metadata


def test_load_dictionary_preserves_duplicate_steno_keys(tmp_path):
    dictionary = tmp_path / "dict.json"
    dictionary.write_text('{"ST": "first", "ST": "second"}', encoding="utf-8")

    entries, metadata, has_metadata = load_dictionary_with_metadata(str(dictionary))

    assert [entry["english"] for entry in entries] == ["first", "second"]
    assert [entry["steno"] for entry in entries] == ["ST", "ST"]
    assert metadata == {}
    assert not has_metadata


def test_load_dictionary_rejects_non_object_json(tmp_path):
    dictionary = tmp_path / "dict.json"
    dictionary.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_dictionary_with_metadata(str(dictionary))
