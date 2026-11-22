"""Stock lots: which full cylinders were bought at what price, and who gets sold first.

Every purchase of full cylinders creates one LOT (qty bought, price paid, purchase id).
A sale takes cylinders from the OLDEST lot first (FIFO) and records exactly which lots
and at what cost, so profit never changes when today's buying price changes later.

All functions run inside the caller's transaction and never commit.
Deposits are not part of a lot's cost (they are tracked separately once the deposit
rules are decided).
"""
from datetime import date

# Oldest first. Opening stock (counted when tracking started) always goes before purchases.
_ORDER = "CASE source WHEN 'opening' THEN 0 ELSE 1 END, lot_date, id"


def add_lot(db, cylinder_type_id, qty, unit_cost_paise, lot_date, purchase_id=None, source="purchase"):
    """Record `qty` full cylinders bought at `unit_cost_paise` each. Returns the lot id."""
    if qty <= 0:
        return None
    return db.execute(
        "INSERT INTO stock_lots (cylinder_type_id, purchase_id, source, lot_date, qty_in, qty_left, unit_cost_paise)"
        " VALUES (?,?,?,?,?,?,?)",
        (cylinder_type_id, purchase_id, source, lot_date, qty, qty, unit_cost_paise),
    ).lastrowid


def consume_fifo(db, cylinder_type_id, qty, ref_type, ref_id):
    """Take `qty` full cylinders out of the oldest lots. Returns the total cost in paise.

    If the lots run short (stock that was never recorded as a lot) the missing cylinders
    are costed at the cylinder's latest purchase price and saved with no lot, so the
    sale still has a cost and nothing breaks.
    """
    remaining, total = qty, 0
    if remaining <= 0:
        return 0
    lots = db.execute(
        "SELECT id, qty_left, unit_cost_paise FROM stock_lots WHERE cylinder_type_id=? AND qty_left>0 ORDER BY " + _ORDER,
        (cylinder_type_id,),
    ).fetchall()
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot["qty_left"])
        db.execute("UPDATE stock_lots SET qty_left = qty_left - ? WHERE id=?", (take, lot["id"]))
        db.execute(
            "INSERT INTO lot_consumptions (lot_id, cylinder_type_id, ref_type, ref_id, qty, unit_cost_paise)"
            " VALUES (?,?,?,?,?,?)",
            (lot["id"], cylinder_type_id, ref_type, ref_id, take, lot["unit_cost_paise"]),
        )
        total += take * lot["unit_cost_paise"]
        remaining -= take
    if remaining > 0:
        row = db.execute("SELECT purchase_price_paise FROM cylinder_types WHERE id=?", (cylinder_type_id,)).fetchone()
        cost = row["purchase_price_paise"] if row else 0
        db.execute(
            "INSERT INTO lot_consumptions (lot_id, cylinder_type_id, ref_type, ref_id, qty, unit_cost_paise)"
            " VALUES (NULL,?,?,?,?,?)",
            (cylinder_type_id, ref_type, ref_id, remaining, cost),
        )
        total += remaining * cost
    return total


def restore(db, ref_type, ref_id):
    """Undo consume_fifo for one document (e.g. a cancelled sale). Cylinders go back to their own lots."""
    rows = db.execute(
        "SELECT id, lot_id, qty FROM lot_consumptions WHERE ref_type=? AND ref_id=? AND status='active'",
        (ref_type, ref_id),
    ).fetchall()
    for r in rows:
        if r["lot_id"] is not None:
            db.execute("UPDATE stock_lots SET qty_left = qty_left + ? WHERE id=?", (r["qty"], r["lot_id"]))
        db.execute("UPDATE lot_consumptions SET status='reversed' WHERE id=?", (r["id"],))
    return len(rows)


def cost_of(db, ref_type, ref_id, cylinder_type_id=None):
    """Total cost in paise of what a document took out of stock (cancelled ones count as 0)."""
    sql = ("SELECT COALESCE(SUM(qty * unit_cost_paise), 0) FROM lot_consumptions "
           "WHERE ref_type=? AND ref_id=? AND status='active'")
    args = [ref_type, ref_id]
    if cylinder_type_id is not None:
        sql += " AND cylinder_type_id=?"
        args.append(cylinder_type_id)
    return db.execute(sql, args).fetchone()[0]


def create_opening_lots(db):
    """Give already-counted full stock a starting lot (at the cylinder's saved buying price).

    Only fills the gap between full_qty and what lots already cover, so it is safe to call twice.
    """
    today = date.today().isoformat()
    for t in db.execute("SELECT id, full_qty, purchase_price_paise FROM cylinder_types").fetchall():
        tracked = db.execute(
            "SELECT COALESCE(SUM(qty_left), 0) FROM stock_lots WHERE cylinder_type_id=?", (t["id"],)
        ).fetchone()[0]
        gap = t["full_qty"] - tracked
        if gap > 0:
            add_lot(db, t["id"], gap, t["purchase_price_paise"], today, None, "opening")
