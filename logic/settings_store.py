# logic/settings_store.py
import json
import os

from .storage_paths import SETTINGS_PATH, LEGACY_SETTINGS_PATH

def _ensure_settings_folder():
    folder = os.path.dirname(SETTINGS_PATH)
    os.makedirs(folder, exist_ok=True)

def _read_settings_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def load_settings():
    _ensure_settings_folder()
    if os.path.exists(SETTINGS_PATH):
        return _read_settings_file(SETTINGS_PATH)
    if os.path.exists(LEGACY_SETTINGS_PATH):
        settings = _read_settings_file(LEGACY_SETTINGS_PATH)
        if settings:
            save_settings(settings)
        return settings
    return {}

def save_settings(settings: dict):
    _ensure_settings_folder()
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"[StenoEditor] Failed to save settings to {SETTINGS_PATH}: {e}")
