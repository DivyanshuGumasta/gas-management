"""SQLite backup manager for manual, automatic and restore-safety snapshots.

All snapshots are generated with sqlite3.Connection.backup(), so committed
pages still present in the live database's WAL are included consistently.
Downloaded/restored backup files are made standalone DELETE-journal databases.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import tempfile
import threading
from datetime import datetime

from db import db_path
from paths import data_dir

DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_RETENTION_COUNT = 30
MAX_RETENTION_COUNT = 100
_BACKUP_LOCK = threading.Lock()
_LEGACY_AUTO_RE = re.compile(r"^agni-\d{4}-\d{2}-\d{2}\.db$", re.IGNORECASE)
_AUTO_RE = re.compile(r"^agni-auto-[0-9-]+\.db$", re.IGNORECASE)


def default_backup_directory() -> str:
    return os.path.abspath(os.path.join(data_dir(), "backups"))


def _read_settings() -> dict[str, str]:
    path = db_path()
    if not os.path.isfile(path):
        return {}
    conn = sqlite3.connect(path, timeout=30)
    try:
        try:
            return {
                str(key): str(value or "")
                for key, value in conn.execute(
                    "SELECT key,value FROM settings WHERE key LIKE 'backup.%'"
                )
            }
        except sqlite3.Error:
            return {}
    finally:
        conn.close()


def _positive_int(value, default, minimum=1, maximum=365 * 24 * 60 * 60) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if minimum <= number <= maximum else default


def load_backup_config() -> dict:
    values = _read_settings()
    interval = _positive_int(values.get("backup.interval_seconds"), DEFAULT_INTERVAL_SECONDS, 3600)
    retention = _positive_int(values.get("backup.retention_count"), DEFAULT_RETENTION_COUNT,
                              1, MAX_RETENTION_COUNT)
    folder = os.path.expanduser(values.get("backup.directory", "").strip())
    if not folder:
        folder = default_backup_directory()
    elif not os.path.isabs(folder):
        folder = os.path.abspath(os.path.join(data_dir(), folder))
    else:
        folder = os.path.abspath(folder)
    return {"interval_seconds": interval, "retention_count": retention, "directory": folder}


def public_backup_settings() -> dict:
    config = load_backup_config()
    seconds = config["interval_seconds"]
    if seconds % (7 * 24 * 3600) == 0:
        value, unit = seconds // (7 * 24 * 3600), "weeks"
    elif seconds % (24 * 3600) == 0:
        value, unit = seconds // (24 * 3600), "days"
    else:
        value, unit = max(1, seconds // 3600), "hours"
    return {
        "frequency_value": int(value),
        "frequency_unit": unit,
        "retention_count": config["retention_count"],
        "directory": config["directory"],
    }


def _backup_to_path(source_path: str, target_path: str) -> None:
    """Write a transactionally consistent standalone SQLite snapshot."""
    source = sqlite3.connect(source_path, timeout=30)
    destination = sqlite3.connect(target_path, timeout=30)
    try:
        source.backup(destination, pages=256, sleep=0.01)
        # The backup inherits the source's persistent journal mode. The
        # snapshot is transferred as a single .db file, so it must not depend
        # on sidecar WAL/SHM files.
        journal_mode = destination.execute("PRAGMA journal_mode=DELETE").fetchone()
        if not journal_mode or str(journal_mode[0]).lower() != "delete":
            raise sqlite3.OperationalError(
                "Could not make the backup self-contained (journal mode is not DELETE)."
            )
        destination.execute("PRAGMA optimize")
    except BaseException:
        destination.close()
        source.close()
        try:
            os.remove(target_path)
        except FileNotFoundError:
            pass
        raise
    else:
        destination.close()
        source.close()


def _unique_path(folder: str, prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(folder, f"{prefix}-{stamp}.db")
    suffix = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{prefix}-{stamp}-{suffix}.db")
        suffix += 1
    return path


def _create_named_backup(prefix: str, folder: str | None = None) -> str | None:
    source_path = db_path()
    if not os.path.isfile(source_path):
        return None
    folder = os.path.abspath(folder or load_backup_config()["directory"])
    os.makedirs(folder, exist_ok=True)
    target_path = _unique_path(folder, prefix)
    _backup_to_path(source_path, target_path)
    return target_path


def create_temporary_backup() -> str | None:
    """Create a standalone temporary snapshot for a legacy download endpoint."""
    source_path = db_path()
    if not os.path.isfile(source_path):
        return None
    fd, target_path = tempfile.mkstemp(prefix="agni-gas-backup-", suffix=".db")
    os.close(fd)
    try:
        _backup_to_path(source_path, target_path)
    except BaseException:
        try:
            os.remove(target_path)
        except FileNotFoundError:
            pass
        raise
    return target_path


def create_manual_backup() -> str | None:
    """Create a user-requested manual backup in the configured folder."""
    return _create_named_backup("agni-manual")


def create_restore_safety_backup() -> str | None:
    """Create a pre-restore safety snapshot, not subject to auto retention."""
    return _create_named_backup("agni-before-restore")


def _automatic_files(folder: str) -> list[str]:
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    return [os.path.join(folder, name) for name in names
            if _AUTO_RE.match(name) or _LEGACY_AUTO_RE.match(name)]


def maybe_create_automatic_backup(now: float | None = None) -> str | None:
    """Create a due automatic backup and prune the oldest automatic files.

    The app calls this at startup, from a lightweight scheduler while open,
    and before incoming requests as a fallback for embedded Flask deployments.
    """
    source_path = db_path()
    if not os.path.isfile(source_path):
        return None
    with _BACKUP_LOCK:
        config = load_backup_config()
        folder = config["directory"]
        os.makedirs(folder, exist_ok=True)
        files = _automatic_files(folder)
        current_time = datetime.now().timestamp() if now is None else float(now)
        newest_mtime = max((os.path.getmtime(p) for p in files if os.path.isfile(p)), default=None)
        if newest_mtime is not None and current_time - newest_mtime < config["interval_seconds"]:
            return None

        created = _create_named_backup("agni-auto", folder)
        if not created:
            return None
        files = [p for p in _automatic_files(folder) if os.path.isfile(p)]
        files.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
        keep = config["retention_count"]
        for old_path in files[:-keep]:
            try:
                os.remove(old_path)
            except OSError:
                # A locked/permission-protected old snapshot should not make
                # the application unavailable after a successful new backup.
                pass
        return created


def daily_backup(folder: str | None = None, keep: int = DEFAULT_RETENTION_COUNT) -> str | None:
    """Backward-compatible force-create helper for older launchers."""
    if not os.path.isfile(db_path()):
        return None
    folder = os.path.abspath(folder or load_backup_config()["directory"])
    os.makedirs(folder, exist_ok=True)
    with _BACKUP_LOCK:
        created = _create_named_backup("agni-auto", folder)
        if created:
            files = [p for p in _automatic_files(folder) if os.path.isfile(p)]
            files.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
            for old_path in files[:-max(1, min(int(keep), MAX_RETENTION_COUNT))]:
                try:
                    os.remove(old_path)
                except OSError:
                    pass
        return created


def start_backup_scheduler(check_every_seconds: int = 60):
    """Start a small daemon that checks the configured cadence while the app is open.

    Desktop and direct Flask launchers call this once. Request-time checks remain
    as a fallback for servers that embed the Flask app without using a launcher.
    The returned Event can stop the thread cleanly during application shutdown.
    """
    stop_event = threading.Event()
    interval = max(10, int(check_every_seconds))

    def worker():
        while not stop_event.is_set():
            try:
                maybe_create_automatic_backup()
            except Exception as exc:
                # Backups must never crash or stop the billing application.
                logging.getLogger(__name__).warning("Automatic backup scheduler failed: %s", exc)
            stop_event.wait(interval)

    thread = threading.Thread(target=worker, name="agni-backup-scheduler", daemon=True)
    thread.start()
    return stop_event, thread
