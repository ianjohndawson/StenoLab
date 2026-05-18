# logic/storage_paths.py
import os


APP_FOLDER_NAME = "StenoLab Data"
LEGACY_APP_FOLDER_NAME = "StenoEditor"


def _appdata_root() -> str:
    appdata = os.getenv("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    return os.path.join(appdata, LEGACY_APP_FOLDER_NAME)


def _candidate_documents_dirs() -> list[str]:
    home = os.path.expanduser("~")
    out = []

    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.getenv(env_name)
        if root:
            out.append(os.path.join(root, "Documents"))

    # Common OneDrive Documents location even when the environment variable is
    # not present, followed by the normal local Documents fallback.
    out.append(os.path.join(home, "OneDrive", "Documents"))
    out.append(os.path.join(home, "Documents"))

    seen = set()
    unique = []
    for path in out:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            unique.append(path)
    return unique


def documents_app_root() -> str:
    """Return the preferred user-visible, sync-friendly StenoLab data folder."""
    for docs in _candidate_documents_dirs():
        if os.path.isdir(docs):
            return os.path.join(docs, APP_FOLDER_NAME)

    # Last-resort fallback; this still lands somewhere user-visible.
    return os.path.join(os.path.expanduser("~"), "Documents", APP_FOLDER_NAME)


APP_ROOT = documents_app_root()
LEGACY_APP_ROOT = _appdata_root()

SETTINGS_PATH = os.path.join(APP_ROOT, "settings.json")
LEGACY_SETTINGS_PATH = os.path.join(LEGACY_APP_ROOT, "settings.json")

METADATA_ROOT = os.path.join(APP_ROOT, "metadata")
LEGACY_METADATA_ROOT = os.path.join(LEGACY_APP_ROOT, "metadata")

BACKUP_ROOT = os.path.join(APP_ROOT, "backups")
LEGACY_BACKUP_ROOT = os.path.join(LEGACY_APP_ROOT, "backups")
