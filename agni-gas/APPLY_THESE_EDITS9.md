# APPLY_THESE_EDITS9 — Stock lots: oldest-first cost tracking (FIFO)

**The idea you described is now what the backend does.** Before this the app did NOT work that way: stock was just a
count per size plus one global buying price, and sales stored no cost, so a price change would have rewritten
old profit. Now every purchase creates a lot, sales take from the oldest lot, and the cost of each sale is recorded.
Backend only. No screen changes.

## Easy way
Unzip `v0.4_stock_lots.zip` over `agni-gas/` (same folders). Start the app once; it upgrades your database by itself
(adds 2 tables, turns your current full stock into an "opening stock" lot at each size's saved buying price; nothing
is deleted). Done. Run `python -m unittest discover tests` — 21 pass (your 14 + 7 new).

## By hand (7 files)

### 1. NEW file `lots.py` (next to `money.py`)
Copy the file from the zip. It holds `add_lot`, `consume_fifo`, `restore`, `cost_of`, `create_opening_lots`.

### 2. `schema.sql` — paste at the very END of the file
```sql
-- Stock lots (FIFO). One row per purchase of full cylinders: how many, at what price, and how
-- many are still on the shelf. Sales take from the oldest lot first, so profit stays correct
-- when the buying price changes. purchase_id is the "pid"; NULL for opening stock.
CREATE TABLE IF NOT EXISTS stock_lots (
    id               INTEGER PRIMARY KEY,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    purchase_id      INTEGER REFERENCES purchases(id),
    source           TEXT NOT NULL DEFAULT 'purchase' CHECK (source IN ('purchase', 'opening', 'adjustment')),
    lot_date         TEXT NOT NULL,
    qty_in           INTEGER NOT NULL CHECK (qty_in > 0),
    qty_left         INTEGER NOT NULL CHECK (qty_left >= 0),
    unit_cost_paise  INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_stock_lots_fifo ON stock_lots(cylinder_type_id, qty_left, lot_date, id);
CREATE INDEX IF NOT EXISTS idx_stock_lots_purchase ON stock_lots(purchase_id);

-- Which lots a sale (or any document) took cylinders from, and at what cost.
-- Never deleted: a cancelled sale marks its rows 'reversed' and the lots get their cylinders back.
-- lot_id is NULL only for stock that was never recorded as a lot.
CREATE TABLE IF NOT EXISTS lot_consumptions (
    id               INTEGER PRIMARY KEY,
    lot_id           INTEGER REFERENCES stock_lots(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    ref_type         TEXT NOT NULL,
    ref_id           INTEGER NOT NULL,
    qty              INTEGER NOT NULL CHECK (qty > 0),
    unit_cost_paise  INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reversed')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_lot_consumptions_ref ON lot_consumptions(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_lot_consumptions_lot ON lot_consumptions(lot_id);
```

### 3. `db.py` — in `init_db()`
**Find:**
```python
        conn.commit()
    finally:
        conn.close()


def get_db
```
**Replace with:**
```python
        # v0.4: first start with stock lots - existing full stock becomes an "opening stock" lot.
        if conn.execute("SELECT COUNT(*) FROM stock_lots").fetchone()[0] == 0:
            import lots
            lots.create_opening_lots(conn)
        conn.commit()
    finally:
        conn.close()


def get_db
```

### 4. `api/purchases.py` — 3 changes
**4a. Top of the file, find:** `from db import get_db, next_number, transaction`
**Replace with:**
```python
import lots
from db import get_db, next_number, transaction
```
**4b. In `purchase_create`, find (the `stock_movements` insert inside `for item in wanted:`):**
```python
            db.execute(
                "INSERT INTO stock_movements(cylinder_type_id,ref_type,ref_id,full_delta,empty_delta,note) VALUES(?,?,?,?,?,?)",
                (item["id"],"purchase",pid,item["full_in"],item["new_empty"]-item["empty_out"],f"Purchase {number}"),
            )
```
**Add right after it (same indentation, 12 spaces):**
```python
            # FIFO: remember what these full cylinders cost, so later price changes never rewrite old profit.
            lots.add_lot(db, item["id"], item["full_in"], item["rate"], day, pid)
```
**4c. Paste at the very END of the file** (read-only list of lots; this is what the Excel export will use):
```python
# ---------- Stock lots (FIFO) ----------
@api_bp.get("/stock-lots")
def stock_lots_list():
    """Every lot of full cylinders: bought when, from whom, at what price, how many left.

    ?cylinder_type_id=  limit to one size      ?open=1  only lots that still have cylinders
    Oldest first, which is the order cylinders are sold in.
    """
    where, params = [], []
    tid = request.args.get("cylinder_type_id")
    if tid:
        where.append("l.cylinder_type_id=?")
        params.append(int_field(tid, "Cylinder type", minimum=1))
    if request.args.get("open") == "1":
        where.append("l.qty_left>0")
    rows = get_db().execute(
        "SELECT l.*, ct.name AS cylinder, pu.number AS purchase_number, s.name AS supplier "
        "FROM stock_lots l JOIN cylinder_types ct ON ct.id=l.cylinder_type_id "
        "LEFT JOIN purchases pu ON pu.id=l.purchase_id LEFT JOIN suppliers s ON s.id=pu.supplier_id"
        + (" WHERE " + " AND ".join(where) if where else "") +
        " ORDER BY l.cylinder_type_id, CASE l.source WHEN 'opening' THEN 0 ELSE 1 END, l.lot_date, l.id", params
    ).fetchall()
    out, value_left = [], 0
    for r in rows:
        left_value = r["qty_left"] * r["unit_cost_paise"]
        value_left += left_value
        out.append({
            "id": r["id"], "cylinder_type_id": r["cylinder_type_id"], "cylinder": r["cylinder"],
            "source": r["source"], "purchase_id": r["purchase_id"], "purchase_number": r["purchase_number"],
            "supplier": r["supplier"], "date": r["lot_date"], "qty_in": r["qty_in"], "qty_left": r["qty_left"],
            "unit_cost": to_rupees(r["unit_cost_paise"]), "value_left": to_rupees(left_value),
        })
    return jsonify({"lots": out, "stock_value": to_rupees(value_left)})
```

### 5. `seed_demo.py` — demo data only
**Find:** the last `conn.commit()` before `if __name__` (the line right above the two blank lines and `if __name__ == "__main__":`).
**Add above it:**
```python
    import lots
    lots.create_opening_lots(conn)   # the starting stock becomes opening lots
```

### 6. `tests/test_lots.py` — NEW file, copy from the zip (7 tests).

### 7. `README.md` — replaced by the zip's version: new status row, and a section **"Stock lots — cost tracking, oldest first (FIFO)"** after the purchase rules.

## How it behaves (tested)
- Buy 2 @ 1,300 (1 Nov) and 2 @ 1,400 (10 Nov). Sell 3: cost = 1,300 + 1,300 + 1,400 = Rs 4,000, lots left 0 and 1.
- Price changes from 1,300 to 1,400: the old cylinders still cost 1,300, so profit stays 200 each at 1,500.
- A purchase entered later but dated earlier is older and goes first.
- Cancelling a sale gives the cylinders back to their own lots; cancelling twice changes nothing.
- Lots short (stock added by hand): costed at the latest buying price, so the sale never fails.
- Old databases: upgrade creates one opening lot per size; starting again does not add more.
- `GET /api/stock-lots?cylinder_type_id=1&open=1` lists lots with supplier, purchase number (the pid), cost, left, and total stock value.

## Not done yet (waiting on pieces you will build/tell me)
1. **Sales does not consume lots yet** because the Sales backend is not in your repo. `SALES_HOOK_NOTE.md` has the
   two calls it needs (I tested them against my Sales code: sell 3 across two lots, cancel, lots restored).
2. **Stock & Price "Adjust stock"** must add/consume lots too (rule written in the README).
3. **Cancel purchase** does not exist yet; when added it must remove its lot only if none of it was sold.
4. **Deposits** are not in the cost (waiting for your damaged-cylinder/security answer). **Empties** carry no cost.
5. The purchase receipt does not show lot numbers yet, only the API does.
