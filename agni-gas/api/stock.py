"""Stock & Price screen: numbers, cylinder cards, other items, history and the actions on them.

Cylinders live in cylinder_types (counts are full / empty / damaged / with customers).
Other items (gas pipes, stoves ...) live in catalog_items with a quantity in thousandths.
Every change to a count is written to a history table; nothing is ever silently overwritten.
Full cylinders also move through stock lots (see lots.py) so the cost of stock stays exact.
"""
from datetime import date

from flask import jsonify, request

import lots
from db import (get_db, transaction, link_new_cylinder_to_sole_supplier,
                link_new_item_to_sole_supplier)
from money import to_rupees
from . import api_bp
from .util import (ApiError, body, gst_rate_bp_field, hsn_field, int_field,
                   money_field, quantity_from_milli, quantity_milli_field, text)

LOW_CYLINDERS = 5     # a size is "LOW" when it has this many full cylinders or fewer
LOW_ITEM_MILLI = 2000  # an item is "LOW" at 2 (of its unit) or fewer

MOVEMENT_LABEL = {
    "purchase": "Purchase", "sale": "Sale", "sale_cancel": "Sale cancelled", "adjustment": "Adjusted",
    "opening": "Opening stock", "damaged": "Damaged updated", "customer_return": "Empty returned",
    "return": "Empty returned", "damaged_send_back": "Damaged cylinders sent back",
}


# ---------- small helpers ----------
def _blank0_money(data, key, label):
    """A price box left empty means 0."""
    if data.get(key) in (None, ""):
        return 0
    return money_field(data, key, label, allow_zero=True)


def _blank0_int(data, key, label):
    if data.get(key) in (None, ""):
        return 0
    return int_field(data.get(key), label, field=key, maximum=1_000_000)


def _weight(data):
    try:
        weight = float(data.get("weight_kg"))
    except (TypeError, ValueError):
        raise ApiError("Enter the cylinder weight in kg.", field="weight_kg")
    if not (0.1 <= weight <= 1000):
        raise ApiError("Cylinder weight must be between 0.1 and 1000 kg.", field="weight_kg")
    weight = round(weight, 3)
    return weight, f"{weight:g} kg"


def _cylinder(db, tid):
    row = db.execute("SELECT * FROM cylinder_types WHERE id=? AND active=1", (tid,)).fetchone()
    if not row:
        raise ApiError("Cylinder not found.", 404)
    return row


def _item(db, iid):
    row = db.execute("SELECT * FROM catalog_items WHERE id=? AND active=1", (iid,)).fetchone()
    if not row:
        raise ApiError("Item not found.", 404)
    return row


def _movement(db, tid, ref_type, ref_id=None, full=0, empty=0, damaged=0, note=None):
    return db.execute(
        "INSERT INTO stock_movements (cylinder_type_id, ref_type, ref_id, full_delta, empty_delta, damaged_delta, note)"
        " VALUES (?,?,?,?,?,?,?)", (tid, ref_type, ref_id, full, empty, damaged, note)).lastrowid


def _item_movement(db, iid, delta_milli, kind, note=None):
    db.execute("INSERT INTO catalog_adjustments (item_id, kind, quantity_delta_milli, note) VALUES (?,?,?,?)",
               (iid, kind, delta_milli, note))


# ---------- page data ----------
def _cylinder_dict(r, lot_value, lot_qty, suppliers):
    covered = lot_value + max(0, r["full_qty"] - lot_qty) * r["purchase_price_paise"]   # stock the lots do not cover
    return {
        "id": r["id"], "name": r["name"], "kg": r["kg"], "hsn": r["hsn"],
        "gst_rate": None if r["gst_rate_bp"] is None else str(r["gst_rate_bp"] / 100),
        "full": r["full_qty"], "empty": r["empty_qty"], "damaged": r["damaged_qty"],
        "with_customers": r["with_customers_qty"],
        "sale_price": to_rupees(r["sale_price_paise"]), "wholesale_price": to_rupees(r["wholesale_price_paise"]),
        "purchase_price": to_rupees(r["purchase_price_paise"]), "security": to_rupees(r["security_paise"]),
        "low": r["full_qty"] <= LOW_CYLINDERS,
        "stock_value": to_rupees(covered),                         # what the full cylinders on the shelf cost
        "margin": to_rupees(r["sale_price_paise"] - r["purchase_price_paise"]),
        "suppliers": suppliers,
    }


def _item_dict(r, suppliers):
    value = (r["stock_qty_milli"] * r["purchase_price_paise"] + 500) // 1000
    return {
        "id": r["id"], "name": r["name"], "unit": r["unit"], "qty": quantity_from_milli(r["stock_qty_milli"]),
        "hsn": r["hsn"], "gst_rate": None if r["gst_rate_bp"] is None else str(r["gst_rate_bp"] / 100),
        "sale_price": to_rupees(r["sale_price_paise"]), "wholesale_price": to_rupees(r["wholesale_price_paise"]),
        "purchase_price": to_rupees(r["purchase_price_paise"]),
        "low": r["stock_qty_milli"] <= LOW_ITEM_MILLI,
        "stock_value": to_rupees(value),
        "margin": to_rupees(r["sale_price_paise"] - r["purchase_price_paise"]),
        "suppliers": suppliers,
    }


def _stock_payload(db):
    cyl_rows = db.execute("SELECT * FROM cylinder_types WHERE active=1 ORDER BY sort_order, id").fetchall()
    lot = {r["cylinder_type_id"]: (r["v"], r["q"]) for r in db.execute(
        "SELECT cylinder_type_id, SUM(qty_left * unit_cost_paise) AS v, SUM(qty_left) AS q FROM stock_lots GROUP BY cylinder_type_id")}
    sup = {}
    for r in db.execute("SELECT si.cylinder_type_id AS k, s.name FROM supplier_items si "
                        "JOIN suppliers s ON s.id=si.supplier_id WHERE s.active=1 ORDER BY s.name COLLATE NOCASE"):
        sup.setdefault(r["k"], []).append(r["name"])
    cylinders = [_cylinder_dict(r, *lot.get(r["id"], (0, 0)), sup.get(r["id"], [])) for r in cyl_rows]

    item_rows = db.execute("SELECT * FROM catalog_items WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
    isup = {}
    for r in db.execute("SELECT sci.item_id AS k, s.name FROM supplier_catalog_items sci "
                        "JOIN suppliers s ON s.id=sci.supplier_id WHERE sci.active=1 AND s.active=1 "
                        "ORDER BY s.name COLLATE NOCASE"):
        isup.setdefault(r["k"], []).append(r["name"])
    items = [_item_dict(r, isup.get(r["id"], [])) for r in item_rows]

    cost = sum(int(round(float(c["stock_value"]) * 100)) for c in cylinders) + \
        sum((r["stock_qty_milli"] * r["purchase_price_paise"] + 500) // 1000 for r in item_rows)
    value = sum(r["full_qty"] * r["sale_price_paise"] for r in cyl_rows) + \
        sum((r["stock_qty_milli"] * r["sale_price_paise"] + 500) // 1000 for r in item_rows)
    full = sum(r["full_qty"] for r in cyl_rows)
    empty = sum(r["empty_qty"] for r in cyl_rows)
    held = sum(r["with_customers_qty"] for r in cyl_rows)
    return {
        "summary": {
            "ready": full, "to_refill": empty, "with_customers": held, "total_owned": full + empty + held,
            "other_items": len(items), "stock_cost": to_rupees(cost), "stock_value": to_rupees(value),
            "damaged_total": sum(r["damaged_qty"] for r in cyl_rows),
        },
        "cylinders": cylinders, "items": items,
    }


@api_bp.get("/stock")
def stock_overview():
    return jsonify(_stock_payload(get_db()))


@api_bp.get("/stock/history")
def stock_history():
    """Newest first. ?limit=  (default 30, max 200)   ?cylinder_type_id=  one size only."""
    db = get_db()
    limit = int_field(request.args.get("limit", 30), "Limit", minimum=1, maximum=200)
    tid = request.args.get("cylinder_type_id")
    params, where = [], ""
    if tid:
        where = " WHERE m.cylinder_type_id=?"
        params.append(int_field(tid, "Cylinder", minimum=1))
    rows = []
    for m in db.execute(
        "SELECT m.id, COALESCE(dd.dispatch_date || ' 12:00:00', m.moved_at) AS moved_at, "
        "m.ref_type, m.note, m.full_delta, m.empty_delta, m.damaged_delta, t.name, "
        "COALESCE(p.number, s.number, CASE WHEN dd.id IS NOT NULL THEN 'Dispatch #' || dd.id END) AS number "
        "FROM stock_movements m "
        "JOIN cylinder_types t ON t.id=m.cylinder_type_id "
        "LEFT JOIN purchases p ON m.ref_type='purchase' AND p.id=m.ref_id "
        "LEFT JOIN sales s ON m.ref_type IN ('sale','sale_cancel') AND s.id=m.ref_id "
        "LEFT JOIN damaged_cylinder_dispatches dd ON m.ref_type='damaged_send_back' AND dd.id=m.ref_id" + where +
        " ORDER BY COALESCE(dd.dispatch_date || ' 12:00:00', m.moved_at) DESC, m.id DESC LIMIT ?",
        params + [limit + 1]
    ):
        changes = [{"n": n, "label": label} for n, label in
                   ((m["full_delta"], "Full"), (m["empty_delta"], "Empty"), (m["damaged_delta"], "Damaged")) if n]
        label = MOVEMENT_LABEL.get(m["ref_type"], (m["ref_type"] or "Change").replace("_", " ").capitalize())
        rows.append(((m["moved_at"], 1, m["id"]), {
            "id": f"c{m['id']}", "at": m["moved_at"], "title": f"{m['name']} · {label}",
            "ref": m["number"] or (m["note"] if m["ref_type"] in ("adjustment", "opening") else None), "changes": changes}))
    if not tid:
        for m in db.execute(
            "SELECT 'a' || a.id AS key, a.id, a.moved_at, a.kind, a.note, a.quantity_delta_milli AS d, i.name, i.unit, NULL AS number "
            "FROM catalog_adjustments a JOIN catalog_items i ON i.id=a.item_id "
            "UNION ALL SELECT 'p' || c.id, c.id, c.moved_at, 'purchase', c.note, c.quantity_delta_milli, i.name, i.unit, p.number "
            "FROM catalog_stock_movements c JOIN catalog_items i ON i.id=c.item_id JOIN purchases p ON p.id=c.purchase_id "
            "UNION ALL SELECT 's' || m.id, m.id, m.moved_at, m.kind, m.note, m.quantity_delta_milli, i.name, i.unit, s.number "
            "FROM catalog_sale_movements m JOIN catalog_items i ON i.id=m.item_id JOIN sales s ON s.id=m.sale_id "
            "ORDER BY 3 DESC, 2 DESC LIMIT ?", (limit + 1,)
        ):
            label = MOVEMENT_LABEL.get(m["kind"], m["kind"].capitalize())
            rows.append(((m["moved_at"], 0, m["id"]), {
                "id": m["key"], "at": m["moved_at"], "title": f"{m['name']} · {label}",
                "ref": m["number"] or (m["note"] if m["kind"] in ("adjustment", "opening") else None),
                "changes": [{"n": m["d"] / 1000, "label": m["unit"]}]}))
    rows.sort(key=lambda x: x[0], reverse=True)
    return jsonify([r[1] for r in rows[:limit + 1]])


# ---------- cylinders ----------
def _cylinder_response(db, tid, status=200):
    for c in _stock_payload(db)["cylinders"]:
        if c["id"] == tid:
            return jsonify(c), status
    raise ApiError("Cylinder not found.", 404)


@api_bp.post("/cylinders")
def cylinder_create():
    data = body()
    weight, label = _weight(data)
    prices = {k: _blank0_money(data, k, lab) for k, lab in (
        ("sale_price", "Sale price"), ("wholesale_price", "Wholesale price"),
        ("purchase_price", "Purchase price"), ("security", "Security"))}
    hsn = hsn_field(data)
    gst_rate_bp = gst_rate_bp_field(data)
    full, empty = _blank0_int(data, "full", "Full cylinders"), _blank0_int(data, "empty", "Empty cylinders")
    db = get_db()
    with transaction(db):
        row = db.execute("SELECT id, active FROM cylinder_types WHERE ABS(COALESCE(kg,0)-?) < 0.0005", (weight,)).fetchone()
        if row and row["active"]:
            raise ApiError(f"{label} already exists. Use Adjust stock or Update price on its card.", 409, field="weight_kg")
        if row:       # a deleted size comes back, with fresh numbers
            tid = row["id"]
            db.execute("UPDATE cylinder_types SET active=1, full_qty=0, empty_qty=0, damaged_qty=0, with_customers_qty=0 WHERE id=?", (tid,))
        else:
            order = db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM cylinder_types").fetchone()[0]
            tid = db.execute("INSERT INTO cylinder_types (name, kg, sort_order) VALUES (?,?,?)", (label, weight, order)).lastrowid
        db.execute("UPDATE cylinder_types SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?, security_paise=?,"
                   " full_qty=?, empty_qty=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (prices["sale_price"], prices["wholesale_price"], prices["purchase_price"], prices["security"],
                    full, empty, hsn, gst_rate_bp, tid))
        link_new_cylinder_to_sole_supplier(db, tid)
        if full or empty:
            _movement(db, tid, "opening", full=full, empty=empty, note="Starting stock")
        if full:
            lots.add_lot(db, tid, full, prices["purchase_price"], date.today().isoformat(), None, "opening")
    return _cylinder_response(db, tid, 201)


@api_bp.put("/cylinders/<int:tid>")
def cylinder_rename(tid):
    data = body()
    weight, label = _weight(data)
    db = get_db()
    current = _cylinder(db, tid)
    hsn = hsn_field(data) if "hsn" in data else current["hsn"]
    gst_rate_bp = gst_rate_bp_field(data) if "gst_rate" in data else current["gst_rate_bp"]
    with transaction(db):
        if db.execute("SELECT 1 FROM cylinder_types WHERE ABS(COALESCE(kg,0)-?) < 0.0005 AND id<>? AND active=1", (weight, tid)).fetchone():
            raise ApiError(f"{label} already exists.", 409, field="weight_kg")
        db.execute("UPDATE cylinder_types SET name=?, kg=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (label, weight, hsn, gst_rate_bp, tid))
    return _cylinder_response(db, tid)


@api_bp.put("/cylinders/<int:tid>/prices")
def cylinder_prices(tid):
    data = body()
    prices = [money_field(data, k, lab) for k, lab in (
        ("sale_price", "Sale price"), ("wholesale_price", "Wholesale price"),
        ("purchase_price", "Purchase price"), ("security", "Security"))]
    db = get_db()
    _cylinder(db, tid)
    with transaction(db):     # lots are not touched: cylinders already bought keep the price they were bought at
        db.execute("UPDATE cylinder_types SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?, security_paise=? WHERE id=?",
                   (*prices, tid))
    return _cylinder_response(db, tid)


@api_bp.post("/cylinders/<int:tid>/adjust")
def cylinder_adjust(tid):
    """The person types what is really on the shelf; the difference becomes a history entry."""
    data = body()
    full = int_field(data.get("full"), "Full cylinders", field="full", maximum=1_000_000)
    empty = int_field(data.get("empty"), "Empty cylinders", field="empty", maximum=1_000_000)
    note = text(data, "note", "Reason", max_len=200)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        d_full, d_empty = full - c["full_qty"], empty - c["empty_qty"]
        if d_full or d_empty:
            mid = _movement(db, tid, "adjustment", full=d_full, empty=d_empty, note=note)
            db.execute("UPDATE cylinder_types SET full_qty=?, empty_qty=? WHERE id=?", (full, empty, tid))
            if d_full > 0:
                lots.add_lot(db, tid, d_full, c["purchase_price_paise"], date.today().isoformat(), None, "adjustment")
            elif d_full < 0:
                lots.consume_fifo(db, tid, -d_full, "adjustment", mid)
    return _cylinder_response(db, tid)


@api_bp.delete("/cylinders/<int:tid>")
def cylinder_delete(tid):
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        if c["with_customers_qty"]:
            raise ApiError(f"{c['name']}: customers still hold {c['with_customers_qty']} cylinder(s). Get them back first.", 409)
        left = c["full_qty"] + c["empty_qty"] + c["damaged_qty"]
        if left:
            raise ApiError(f"{c['name']} still has {left} cylinder(s) in stock. Adjust it to 0 first.", 409)
        db.execute("UPDATE cylinder_types SET active=0 WHERE id=?", (tid,))   # old bills and purchases keep pointing at it
    return jsonify({"ok": True})


@api_bp.put("/stock/damaged")
def damaged_update():
    data = body()
    counts = data.get("counts")
    if not isinstance(counts, dict):
        raise ApiError("Send the damaged counts for each size.")
    db = get_db()
    with transaction(db):
        for key, raw in counts.items():
            c = _cylinder(db, int_field(key, "Cylinder", minimum=1))
            n = int_field(raw, f"Damaged {c['name']}", field=f"d{c['id']}", maximum=1_000_000)
            if n != c["damaged_qty"]:
                _movement(db, c["id"], "damaged", damaged=n - c["damaged_qty"])
                db.execute("UPDATE cylinder_types SET damaged_qty=? WHERE id=?", (n, c["id"]))
    return jsonify({"ok": True})


# ---------- other items ----------
def _item_response(db, iid, status=200):
    for it in _stock_payload(db)["items"]:
        if it["id"] == iid:
            return jsonify(it), status
    raise ApiError("Item not found.", 404)


@api_bp.post("/items")
def item_create():
    data = body()
    name = text(data, "name", "Item name", required=True, max_len=100)
    unit = text(data, "unit", "Unit", max_len=20) or "pcs"
    qty = 0 if data.get("qty") in (None, "") else quantity_milli_field(data.get("qty"), "Stock", field="qty", allow_zero=True)
    sale, wholesale, buy = (_blank0_money(data, k, lab) for k, lab in (
        ("sale_price", "Sale price"), ("wholesale_price", "Wholesale price"), ("purchase_price", "Purchase price")))
    hsn = hsn_field(data)
    gst_rate_bp = gst_rate_bp_field(data)
    db = get_db()
    with transaction(db):
        row = db.execute("SELECT id, active FROM catalog_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if row and row["active"]:
            raise ApiError(f"{name} already exists. Use Adjust stock or Update price on its card.", 409, field="name")
        if row:
            iid = row["id"]
            db.execute("UPDATE catalog_items SET active=1, name=?, unit=?, stock_qty_milli=0 WHERE id=?", (name, unit, iid))
        else:
            iid = db.execute("INSERT INTO catalog_items (name, unit) VALUES (?,?)", (name, unit)).lastrowid
        db.execute("UPDATE catalog_items SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?,"
                   " stock_qty_milli=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (sale, wholesale, buy, qty, hsn, gst_rate_bp, iid))
        link_new_item_to_sole_supplier(db, iid)
        if qty:
            _item_movement(db, iid, qty, "opening", "Starting stock")
    return _item_response(db, iid, 201)


@api_bp.put("/items/<int:iid>")
def item_edit(iid):
    data = body()
    name = text(data, "name", "Item name", required=True, max_len=100)
    unit = text(data, "unit", "Unit", max_len=20) or "pcs"
    db = get_db()
    current = _item(db, iid)
    hsn = hsn_field(data) if "hsn" in data else current["hsn"]
    gst_rate_bp = gst_rate_bp_field(data) if "gst_rate" in data else current["gst_rate_bp"]
    with transaction(db):
        if db.execute("SELECT 1 FROM catalog_items WHERE name=? COLLATE NOCASE AND id<>?", (name, iid)).fetchone():
            raise ApiError("Another item already uses this name.", 409, field="name")
        db.execute("UPDATE catalog_items SET name=?, unit=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (name, unit, hsn, gst_rate_bp, iid))
    return _item_response(db, iid)


@api_bp.put("/items/<int:iid>/prices")
def item_prices(iid):
    data = body()
    sale, wholesale, buy = (money_field(data, k, lab) for k, lab in (
        ("sale_price", "Sale price"), ("wholesale_price", "Wholesale price"), ("purchase_price", "Purchase price")))
    db = get_db()
    _item(db, iid)
    with transaction(db):
        db.execute("UPDATE catalog_items SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=? WHERE id=?",
                   (sale, wholesale, buy, iid))
    return _item_response(db, iid)


@api_bp.post("/items/<int:iid>/adjust")
def item_adjust(iid):
    data = body()
    qty = quantity_milli_field(data.get("qty"), "Stock", field="qty", allow_zero=True)
    note = text(data, "note", "Reason", max_len=200)
    db = get_db()
    with transaction(db):
        it = _item(db, iid)
        delta = qty - it["stock_qty_milli"]
        if delta:
            _item_movement(db, iid, delta, "adjustment", note)
            db.execute("UPDATE catalog_items SET stock_qty_milli=? WHERE id=?", (qty, iid))
    return _item_response(db, iid)


@api_bp.delete("/items/<int:iid>")
def item_delete(iid):
    db = get_db()
    with transaction(db):
        it = _item(db, iid)
        if it["stock_qty_milli"]:
            raise ApiError(f"{it['name']} still has {quantity_from_milli(it['stock_qty_milli'])} {it['unit']} in stock. Adjust it to 0 first.", 409)
        db.execute("UPDATE catalog_items SET active=0 WHERE id=?", (iid,))
        db.execute("UPDATE supplier_catalog_items SET active=0 WHERE item_id=?", (iid,))
    return jsonify({"ok": True})
