"""Automatic daily backup of the database (one file per day, newest 30 kept).

Uses SQLite's own backup API, so it is safe even while the app is running.
The destination folder / USB drive setting comes with the Data & sync screen.
"""
import os
import sqlite3
from datetime import date

from db import db_path
from paths import data_dir


def daily_backup(folder: str | None = None, keep: int = 30) -> str | None:
    src_path = db_path()
    if not os.path.exists(src_path):
        return None
    folder = folder or os.path.join(data_dir(), "backups")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, f"agni-{date.today().isoformat()}.db")
    if os.path.exists(target):
        return None  # already backed up today

    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    files = sorted(f for f in os.listdir(folder) if f.startswith("agni-") and f.endswith(".db"))
    for old in files[:-keep]:
        os.remove(os.path.join(folder, old))
    return target
