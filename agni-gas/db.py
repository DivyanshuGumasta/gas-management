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
        # v0.3.7: brand-new full cylinders are stored separately from refills.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(purchase_items)")]
        if "new_full_qty" not in cols:
            conn.execute("ALTER TABLE purchase_items ADD COLUMN new_full_qty INTEGER NOT NULL DEFAULT 0")
        if conn.execute("SELECT COUNT(*) FROM cylinder_types").fetchone()[0] == 0:
            for i, (name, kg, sale, whole, buy, sec) in enumerate(DEFAULT_CYLINDERS):
                conn.execute(
                    "INSERT INTO cylinder_types (name, kg, sale_price_paise, wholesale_price_paise,"
                    " purchase_price_paise, security_paise, sort_order) VALUES (?,?,?,?,?,?,?)",
                    (name, kg, sale * 100, whole * 100, buy * 100, sec * 100, i),
                )
        # v0.4.2: ordinary items get a wholesale price.
        if "wholesale_price_paise" not in [r[1] for r in conn.execute("PRAGMA table_info(catalog_items)")]:
            conn.execute("ALTER TABLE catalog_items ADD COLUMN wholesale_price_paise INTEGER NOT NULL DEFAULT 0")
        # v0.4: first start with stock lots - existing full stock becomes an "opening stock" lot.
        if conn.execute("SELECT COUNT(*) FROM stock_lots").fetchone()[0] == 0:
            import lots
            lots.create_opening_lots(conn)

        # v0.4.4: everything per supplier. Own deposit and empty count on the supplier link, supplier on each lot,
        # and where a refunded deposit was received (cash / bank).
        if "security_paise" not in [r[1] for r in conn.execute("PRAGMA table_info(supplier_items)")]:
            conn.execute("ALTER TABLE supplier_items ADD COLUMN security_paise INTEGER")
            conn.execute("UPDATE supplier_items SET security_paise=(SELECT security_paise FROM cylinder_types WHERE id=supplier_items.cylinder_type_id)")
        if "empty_qty" not in [r[1] for r in conn.execute("PRAGMA table_info(supplier_items)")]:
            conn.execute("ALTER TABLE supplier_items ADD COLUMN empty_qty INTEGER NOT NULL DEFAULT 0")
        if "supplier_id" not in [r[1] for r in conn.execute("PRAGMA table_info(stock_lots)")]:
            conn.execute("ALTER TABLE stock_lots ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)")
        conn.execute("UPDATE stock_lots SET supplier_id=(SELECT supplier_id FROM purchases WHERE id=stock_lots.purchase_id) "
                     "WHERE supplier_id IS NULL AND purchase_id IS NOT NULL")
        if "received_in" not in [r[1] for r in conn.execute("PRAGMA table_info(cylinder_deposits)")]:
            conn.execute("ALTER TABLE cylinder_deposits ADD COLUMN received_in TEXT")

        # v0.4.3: deposits already paid on earlier purchases go into the deposit history (only when it is empty).
        if conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO cylinder_deposits (cylinder_type_id, supplier_id, kind, qty, amount_paise, purchase_id, note) "
                "SELECT i.cylinder_type_id, p.supplier_id, 'paid', i.new_full_qty + i.new_empty_qty, "
                "(i.new_full_qty + i.new_empty_qty) * i.security_rate_paise, p.id, 'Purchase ' || p.number "
                "FROM purchase_items i JOIN purchases p ON p.id = i.purchase_id WHERE i.new_full_qty + i.new_empty_qty > 0")
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
