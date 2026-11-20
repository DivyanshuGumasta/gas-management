"""Where things live. Works in dev and inside a PyInstaller .exe."""
import os
import sys


def resource_path(relative: str) -> str:
    """Read-only bundled files (templates, static, schema.sql)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def data_dir() -> str:
    """Writable folder for the database and backups.

    .exe  : %APPDATA%\\AgniGas   (survives reinstalling / updating the app)
    dev   : ./data
    Override with AGNI_DATA_DIR.
    """
    override = os.environ.get("AGNI_DATA_DIR")
    if override:
        return override
    if getattr(sys, "frozen", False):
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AgniGas")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
