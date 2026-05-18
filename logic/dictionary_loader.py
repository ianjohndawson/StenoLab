# logic/dictionary_loader.py
import json
from .metadata_store import load_metadata


def load_dictionary_with_metadata(dict_path: str):
    """
    Load a dictionary JSON and its metadata (if present).

    Duplicate steno keys are preserved as separate entries so they surface
    as conflicts in the UI.  Standard json.load() silently keeps only the
    last value for duplicate keys; object_pairs_hook bypasses that.

    Returns:
        entries: list of {
            "steno": str,
            "english": str,
            "modified": str,
            "date_added": str
        }
        metadata: dict keyed by steno
        has_metadata: bool
    """
    with open(dict_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # object_pairs_hook returns the raw [(steno, english), ...] list,
    # preserving any duplicate keys rather than collapsing to a dict.
    pairs = json.loads(raw_text, object_pairs_hook=lambda p: p)

    if not isinstance(pairs, list) or any(
        not isinstance(pair, tuple) or len(pair) != 2
        for pair in pairs
    ):
        raise ValueError(f"Dictionary file must be a JSON object: {dict_path}")

    metadata = load_metadata(dict_path)
    has_metadata = len(metadata) > 0

    entries = []
    for steno, english in pairs:
        meta = metadata.get(steno, {})
        entries.append(
            {
                "steno": steno,
                "english": english,
                "modified": meta.get("modified", ""),
                "date_added": meta.get("date_added", ""),
            }
        )

    return entries, metadata, has_metadata
