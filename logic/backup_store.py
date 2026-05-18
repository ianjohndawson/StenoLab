# logic/backup_store.py
"""
Timestamped backups of dictionaries and their metadata sidecars.

Backups live in the user-visible StenoLab data folder, usually:

    OneDrive/Documents/StenoLab Data/backups/

and follow the naming pattern:

    <name>__<pathhash>_<YYYY-MM-DD>_<HH-MM-SS>-<ms>_open.json
    <name>__<pathhash>_<YYYY-MM-DD>_<HH-MM-SS>-<ms>_save.json
    <name>__<pathhash>_<YYYY-MM-DD>_<HH-MM-SS>-<ms>_open.metadata.json
    <name>__<pathhash>_<YYYY-MM-DD>_<HH-MM-SS>-<ms>_save.metadata.json

Two kinds of backup are created:

  open  — taken the first time a dictionary is opened in a session.  Captures
          the file exactly as it was when the user sat down to work.
          At most MAX_OPEN_BACKUPS of these are kept.

  save  — taken before every write, preserving the previous on-disk state so
          a bad save is recoverable.
          At most MAX_SAVE_BACKUPS of these are kept.

The two pools are pruned independently, so open-time snapshots are never
crowded out by heavy saving.  Maximum total backups per dictionary is
MAX_OPEN_BACKUPS + MAX_SAVE_BACKUPS = 5.

Legacy backups (created before this naming scheme) have no _open/_save suffix
and are treated as 'legacy' kind for display purposes.  They are not pruned
by the new logic and will persist until removed manually.
"""
import os
import re
import shutil
import hashlib
from datetime import datetime

from .metadata_store import _metadata_file_for
from .storage_paths import BACKUP_ROOT, LEGACY_BACKUP_ROOT

# Separate retention limits for each backup kind.
MAX_OPEN_BACKUPS = 3   # open-time snapshots  (one anchor per recent session)
MAX_SAVE_BACKUPS = 2   # pre-save snapshots   (enough to undo a bad save)


def _ensure_backup_dir() -> None:
    """Create the backup directory on first use rather than at import time."""
    os.makedirs(BACKUP_ROOT, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_basename(path: str) -> str:
    """Strip directory and extension: /foo/bar/main.json -> 'main'."""
    base = os.path.basename(path)
    name, _ = os.path.splitext(base)
    return name


def _dict_identity(path: str) -> str:
    """Stable identity token for a dictionary path."""
    norm = os.path.normcase(os.path.abspath(path))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def _prefix_for(path: str) -> str:
    """Filename prefix used for all backups for this dictionary path."""
    return f"{_safe_basename(path)}__{_dict_identity(path)}"


def _legacy_prefix_for(path: str) -> str:
    """Backward-compatible prefix from old naming scheme."""
    return _safe_basename(path)


def _timestamp() -> str:
    # Millisecond granularity ensures saves within the same second produce
    # distinct backup files instead of overwriting each other.
    now = datetime.now()
    return now.strftime("%Y-%m-%d_%H-%M-%S-") + f"{now.microsecond // 1000:03d}"


# Regex for the new naming scheme: <prefix>_<timestamp>_<kind>
_NEW_BACKUP_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d{3})?)_(?P<kind>open|save)$"
)
# Regex for the legacy naming scheme: <prefix>_<timestamp>  (no kind suffix)
_LEGACY_BACKUP_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d{3})?)$"
)


def _parse_backup_filename(filename: str) -> tuple[str | None, str | None, str | None]:
    """
    Return (prefix, timestamp, kind) for a dictionary backup filename.

    kind is 'open', 'save', or 'legacy' (pre-naming-scheme backups).
    Returns (None, None, None) if the filename does not match any known pattern.
    """
    if not filename.endswith(".json") or filename.endswith(".metadata.json"):
        return None, None, None
    stem = filename[:-5]

    m = _NEW_BACKUP_RE.match(stem)
    if m:
        return m.group("prefix"), m.group("ts"), m.group("kind")

    m = _LEGACY_BACKUP_RE.match(stem)
    if m:
        return m.group("prefix"), m.group("ts"), "legacy"

    return None, None, None


def _meta_filename(prefix: str, ts: str, kind: str) -> str:
    """Return the metadata sidecar filename for a given backup."""
    if kind == "legacy":
        return f"{prefix}_{ts}.metadata.json"
    return f"{prefix}_{ts}_{kind}.metadata.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def backup_dictionary(dict_path: str, kind: str = "save") -> tuple[bool, str]:
    """
    Snapshot the dictionary at dict_path (and its metadata sidecar if present)
    into the backup folder.

    Args:
        dict_path: path to the dictionary file to snapshot.
        kind:      'open'  -- taken when a dictionary is first opened in a session.
                   'save'  -- taken before a write (default).

    Returns:
        (True, backup_path)  on success -- backup_path is the dictionary backup.
        (True, "")           if there is nothing to back up (file does not exist).
        (False, error_msg)   on failure.
    """
    if not dict_path or not os.path.exists(dict_path):
        # Nothing to back up.  This is normal for a brand-new dictionary
        # that has not been saved yet.
        return True, ""

    # Ensure the backup directory exists on first use.
    try:
        _ensure_backup_dir()
    except OSError as e:
        return False, f"Could not create backup folder: {e}"

    prefix = _prefix_for(dict_path)
    ts     = _timestamp()

    try:
        dict_dst = os.path.join(BACKUP_ROOT, f"{prefix}_{ts}_{kind}.json")
        shutil.copy2(dict_path, dict_dst)

        # Mirror the metadata sidecar if present
        meta_src = _metadata_file_for(dict_path)
        if os.path.exists(meta_src):
            meta_dst = os.path.join(BACKUP_ROOT, _meta_filename(prefix, ts, kind))
            try:
                shutil.copy2(meta_src, meta_dst)
            except OSError:
                # Don't fail the whole backup over the metadata -- the
                # dictionary is the more important artefact.
                pass

        _prune_old_backups(dict_path)
        return True, dict_dst

    except OSError as e:
        return False, str(e)


def _prune_old_backups(dict_path: str) -> None:
    """
    Enforce the per-kind retention limits for this dictionary.

    The open and save pools are pruned independently so that open-time
    snapshots are never displaced by heavy saving.  Legacy backups are
    left untouched.

    Best-effort: any OSError is swallowed so a save never fails because
    pruning failed.
    """
    try:
        prefix    = _prefix_for(dict_path)
        open_pool = []
        save_pool = []

        for fn in os.listdir(BACKUP_ROOT):
            parsed_prefix, ts_part, kind = _parse_backup_filename(fn)
            if parsed_prefix != prefix or not ts_part:
                continue
            if kind == "open":
                open_pool.append((fn, ts_part))
            elif kind == "save":
                save_pool.append((fn, ts_part))
            # legacy backups are intentionally skipped -- not pruned

        for pool, limit, pool_kind in (
            (open_pool, MAX_OPEN_BACKUPS, "open"),
            (save_pool, MAX_SAVE_BACKUPS, "save"),
        ):
            if len(pool) <= limit:
                continue
            # Sort oldest first -- ISO timestamp format sorts lexicographically
            pool.sort(key=lambda item: item[1])
            excess = len(pool) - limit
            for fn, ts_part in pool[:excess]:
                full = os.path.join(BACKUP_ROOT, fn)
                try:
                    os.remove(full)
                except OSError:
                    continue
                # Drop matching metadata sidecar if present
                meta = os.path.join(BACKUP_ROOT, _meta_filename(prefix, ts_part, pool_kind))
                if os.path.exists(meta):
                    try:
                        os.remove(meta)
                    except OSError:
                        pass

    except OSError:
        pass


def list_backups(dict_path: str) -> list[dict]:
    """
    Return all backups for the given dictionary, newest first.

    Each entry is a dict with:
        timestamp:     str       -- the timestamp portion of the filename
        kind:          str       -- 'open', 'save', or 'legacy'
        dict_path:     str       -- full path to the dictionary backup file
        metadata_path: str|None  -- full path to the metadata backup, or None
        mtime:         float     -- file modification time
    """
    prefixes = {_prefix_for(dict_path), _legacy_prefix_for(dict_path)}
    out = []
    try:
        _ensure_backup_dir()
        roots = [BACKUP_ROOT]
        if os.path.isdir(LEGACY_BACKUP_ROOT):
            roots.append(LEGACY_BACKUP_ROOT)
        for root in roots:
            for fn in os.listdir(root):
                parsed_prefix, ts_part, kind = _parse_backup_filename(fn)
                if parsed_prefix not in prefixes or not ts_part:
                    continue
                full    = os.path.join(root, fn)
                meta_fn = _meta_filename(parsed_prefix, ts_part, kind)
                meta    = os.path.join(root, meta_fn)
                out.append({
                    "timestamp":     ts_part,
                    "kind":          kind,
                    "dict_path":     full,
                    "metadata_path": meta if os.path.exists(meta) else None,
                    "mtime":         os.path.getmtime(full),
                })
        out.sort(key=lambda b: b["mtime"], reverse=True)
    except OSError:
        pass
    return out
