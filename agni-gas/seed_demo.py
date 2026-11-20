"""Fill the database with sample data (like the Figma design) for demos.

    python seed_demo.py            # refuses if the database already has sales
    python seed_demo.py --force    # adds the sample data anyway

DEMO ONLY - never run this on the client's real database.
"""
import sys
from datetime import date, timedelta

from db import connect, db_path, init_db, next_number


def _type_id(conn, name):
    return conn.execute("SELECT id FROM cylinder_types WHERE name = ?", (name,)).fetchone()[0]


def _sale(conn, customer_id, day, clock, name, qty, rate, paid):
    total = qty * rate * 100
    number = next_number(conn, "sale", "S")
    cur = conn.execute(
        "INSERT INTO sales (number, customer_id, sale_date, created_at, subtotal_paise, total_paise,"
        " paid_paise) VALUES (?,?,?,?,?,?,?)",
        (number, customer_id, day.isoformat(), f"{day.isoformat()} {clock}", total, total, paid * 100),
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, cylinder_type_id, qty_out, rate_paise, amount_paise)"
        " VALUES (?,?,?,?,?)",
        (cur.lastrowid, _type_id(conn, name), qty, rate * 100, total),
    )


def seed(conn):
    today = date.today()
    yesterday = today - timedelta(days=1)

    stock = {"5 kg": (3, 1, 0), "11.8 kg": (4, 1, 0), "15 kg": (9, 1, 0), "45.4 kg": (4, 0, 1)}
    for name, (full, empty, with_c) in stock.items():
        conn.execute(
            "UPDATE cylinder_types SET full_qty=?, empty_qty=?, with_customers_qty=? WHERE name=?",
            (full, empty, with_c, name),
        )

    ids = {}
    for name, ctype, opening in [("harry", "retail", 0), ("karan", "retail", -1750 * 100), ("tiku", "retail", 0)]:
        ids[name] = conn.execute(
            "INSERT INTO customers (name, type, opening_balance_paise) VALUES (?,?,?)",
            (name, ctype, opening),
        ).lastrowid
    conn.execute(
        "INSERT INTO suppliers (name, gstin, opening_balance_paise) VALUES (?,?,?)",
        ("goo goo", "22AAAAA0000A1Z5", 25000 * 100),
    )

    _sale(conn, None, yesterday, "21:38:00", "5 kg", 1, 1450, 1450)       # walk-in, paid
    _sale(conn, ids["tiku"], today, "10:23:00", "15 kg", 1, 4100, 4100)    # paid
    _sale(conn, ids["harry"], today, "10:45:00", "5 kg", 1, 1450, 950)     # Rs 500 pending
    conn.commit()


if __name__ == "__main__":
    init_db()
    conn = connect()
    if conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] and "--force" not in sys.argv:
        sys.exit(f"{db_path()} already has sales. Use --force if you really want sample data added.")
    seed(conn)
    print("Sample data added to", db_path())
