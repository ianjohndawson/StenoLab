from logic.metadata_store import ensure_metadata


def test_ensure_metadata_preserves_existing_and_fills_defaults():
    entries = [
        {"steno": "ST", "english": "set", "date_added": "2026-01-01", "modified": "2026-01-02"},
        {"steno": "TEFT", "english": "test"},
    ]
    existing = {"ST": {"comments": "keep me", "brief": True}}

    metadata = ensure_metadata(entries, existing)

    assert metadata["ST"] == {"comments": "keep me", "brief": True}
    assert metadata["TEFT"]["comments"] == ""
    assert metadata["TEFT"]["brief"] is False
    assert metadata["TEFT"]["bookmarked"] is False
    assert metadata["TEFT"]["frequency"] == 0
