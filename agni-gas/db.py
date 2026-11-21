"""SQLite access. One connection per request (Flask `g`)."""
import os
import sqlite3

from flask import g

from paths import data_dir, resource_path

# Starting items, taken from the design. The client edits these in Stock & Price.
# (name, kg, sale, wholesale, purchase, security) - rupees
DEFAULT_CYLINDERS = [
    ("5 kg", 5, 1450, 1400, 1300, 2500),
    ("11.8 kg", 11.8, 3250, 3150, 2950, 5000),
    ("15 kg", 15, 4100, 4000, 3750, 6000),
    ("45.4 kg", 45.4, 12300, 12000, 11300, 15000),
]


def db_path() -> str:
    return os.environ.get("AGNI_DB") or os.path.join(data_dir(), "agni.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: str | None = None) -> None:
    path = path or db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = connect(path)
    try:
        with open(resource_path("schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        if conn.execute("SELECT COUNT(*) FROM cylinder_types").fetchone()[0] == 0:
            for i, (name, kg, sale, whole, buy, sec) in enumerate(DEFAULT_CYLINDERS):
                conn.execute(
                    "INSERT INTO cylinder_types (name, kg, sale_price_paise, wholesale_price_paise,"
                    " purchase_price_paise, security_paise, sort_order) VALUES (?,?,?,?,?,?,?)",
                    (name, kg, sale * 100, whole * 100, buy * 100, sec * 100, i),
                )
        conn.commit()
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def next_number(db: sqlite3.Connection, name: str, prefix: str) -> str:
    """Next bill number, e.g. S-00006.

    Call inside the same transaction that saves the bill, so two saves can
    never get the same number (this is also what keeps the later multi-device
    version safe).
    """
    db.execute(
        "INSERT INTO counters (name, value) VALUES (?, 1) "
        "ON CONFLICT(name) DO UPDATE SET value = value + 1",
        (name,),
    )
    n = db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0]
    return f"{prefix}-{n:05d}"


from contextlib import contextmanager  # noqa: E402


@contextmanager
def transaction(conn: sqlite3.Connection):
    """All-or-nothing write block: `with transaction(db): ...`"""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
