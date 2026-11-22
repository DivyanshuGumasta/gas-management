"""Stock & Price, part 2: suppliers on each cylinder, damaged cylinders and security deposits.

Everything is kept per supplier: the price you buy at, the security deposit, the full cylinders
(stock_lots.supplier_id), the empty cylinders (supplier_items.empty_qty) and the deposit held.
Stock that is not tied to a supplier (opening stock, empties customers brought back) is shown as "unassigned".

Security deposits are tracked in `cylinder_deposits`, one row per event, never deleted:
    paid       - a purchase of new cylinders (written by api/purchases.py)
    cancelled  - cylinders marked damaged: the deposit is lost
    refunded   - good cylinders sent back to the supplier: the deposit comes back as real money (cash or bank)
Deposit held with a supplier = paid - cancelled - refunded.
"""
from datetime import date

from flask import jsonify

import lots
from db import get_db, transaction, sole_active_supplier_id
from money import to_rupees
from . import api_bp
from .stock import _cylinder, _movement
from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, text


def _supplier(db, sid):
    row = db.execute("SELECT id, name FROM suppliers WHERE id=? AND active=1", (sid,)).fetchone()
    if not row:
        raise ApiError("Supplier not found.", 404)
    return row


def _optional_supplier(db, data):
    # Omitted means use the only active supplier, if there is exactly one.
    # An explicitly blank value means the user chose Not sure / unassigned.
    if "supplier_id" not in data:
        return sole_active_supplier_id(db)
    raw = data.get("supplier_id")
    if raw in (None, "", "0"):
        return None
    return _supplier(db, int_field(raw, "Supplier", field="supplier_id", minimum=1))["id"]


def _link(db, tid, sid):
    row = db.execute("SELECT * FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
    if not row:
        raise ApiError("This supplier does not sell this cylinder.", 404)
    return row


def _security(link, cylinder):
    """The deposit for one cylinder from this supplier (their own, else the size's)."""
    return cylinder["security_paise"] if link is None or link["security_paise"] is None else link["security_paise"]


def _default_deposit(db, data, tid, sid, cylinder, key="deposit"):
    if data.get(key) not in (None, ""):
        return money_field(data, key, "Deposit", allow_zero=True)
    link = db.execute("SELECT * FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone() if sid else None
    return _security(link, cylinder)


def _deposit_event(db, tid, supplier_id, kind, qty, amount, note=None, received_in=None):
    db.execute("INSERT INTO cylinder_deposits (cylinder_type_id, supplier_id, kind, qty, amount_paise, note, received_in) VALUES (?,?,?,?,?,?,?)",
               (tid, supplier_id, kind, qty, amount, note, received_in))


def _held(db, tid, sid):
    """Deposit (paise) still held with one supplier for one cylinder size. Never below zero."""
    row = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'paid' THEN amount_paise ELSE -amount_paise END),0) FROM cylinder_deposits "
        "WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
    return max(0, row[0])


def _take_empty(db, tid, sid, qty):
    """The supplier's own empties go down (never below 0; the size total is changed by the caller)."""
    if sid:
        db.execute("UPDATE supplier_items SET empty_qty=MAX(0, empty_qty-?) WHERE cylinder_type_id=? AND supplier_id=?", (qty, tid, sid))


def _take_full(db, tid, sid, qty, ref_type, ref_id):
    """Take full cylinders out of one supplier's oldest lots first, then (if short) the oldest of any lot."""
    remaining = qty
    if sid:
        for lot in db.execute(
            "SELECT id, qty_left, unit_cost_paise FROM stock_lots WHERE cylinder_type_id=? AND supplier_id=? AND qty_left>0 "
            "ORDER BY " + lots._ORDER, (tid, sid)).fetchall():
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_left"])
            db.execute("UPDATE stock_lots SET qty_left=qty_left-? WHERE id=?", (take, lot["id"]))
            db.execute("INSERT INTO lot_consumptions (lot_id, cylinder_type_id, ref_type, ref_id, qty, unit_cost_paise) VALUES (?,?,?,?,?,?)",
                       (lot["id"], tid, ref_type, ref_id, take, lot["unit_cost_paise"]))
            remaining -= take
    if remaining > 0:
        lots.consume_fifo(db, tid, remaining, ref_type, ref_id)


@api_bp.get("/stock/extra")
def stock_extra():
    db = get_db()
    types = {r["id"]: r for r in db.execute("SELECT * FROM cylinder_types WHERE active=1")}
    full_from = {(r["t"], r["s"]): r["q"] for r in db.execute(
        "SELECT cylinder_type_id AS t, supplier_id AS s, SUM(qty_left) AS q FROM stock_lots WHERE supplier_id IS NOT NULL GROUP BY 1,2")}
    cylinders = {t: {"suppliers": [], "unassigned_full": r["full_qty"], "unassigned_empty": r["empty_qty"]} for t, r in types.items()}
    for r in db.execute(
        "SELECT si.*, s.name FROM supplier_items si JOIN suppliers s ON s.id=si.supplier_id "
        "WHERE s.active=1 ORDER BY s.name COLLATE NOCASE"
    ):
        c = types.get(r["cylinder_type_id"])
        if not c:
            continue
        t, full = r["cylinder_type_id"], full_from.get((r["cylinder_type_id"], r["supplier_id"]), 0)
        cylinders[t]["suppliers"].append({
            "supplier_id": r["supplier_id"], "name": r["name"], "price": to_rupees(r["purchase_price_paise"]),
            "security": to_rupees(_security(r, c)), "margin": to_rupees(c["sale_price_paise"] - r["purchase_price_paise"]),
            "full": full, "empty": r["empty_qty"], "deposit_held": to_rupees(_held(db, t, r["supplier_id"]))})
        cylinders[t]["unassigned_full"] -= full
        cylinders[t]["unassigned_empty"] -= r["empty_qty"]
    for c in cylinders.values():
        c["unassigned_full"] = max(0, c["unassigned_full"])
        c["unassigned_empty"] = max(0, c["unassigned_empty"])
    totals = {k: v for k, v in db.execute("SELECT kind, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits GROUP BY kind")}
    by_mode = {k: v for k, v in db.execute(
        "SELECT received_in, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits WHERE kind='refunded' GROUP BY 1")}
    damaged = [{"cylinder_type_id": r["id"], "name": r["name"], "qty": r["damaged_qty"], "deposit_lost": to_rupees(r["lost"])} for r in db.execute(
        "SELECT c.id, c.name, c.damaged_qty, COALESCE((SELECT SUM(amount_paise) FROM cylinder_deposits d "
        "WHERE d.cylinder_type_id=c.id AND d.kind='cancelled'),0) AS lost FROM cylinder_types c "
        "WHERE c.active=1 AND c.damaged_qty>0 ORDER BY c.sort_order, c.id")]
    # Each cancelled deposit row created by damaged_add() is one damage batch.
    # A batch remains selectable until all its damaged cylinders have been dispatched.
    dispatch_options = []
    physical_remaining = {
        r["id"]: r["damaged_qty"]
        for r in db.execute("SELECT id, damaged_qty FROM cylinder_types WHERE active=1")
    }
    damage_batches = db.execute(
        "SELECT d.id AS damage_event_id, d.cylinder_type_id, c.name, "
        "d.supplier_id, s.name AS supplier_name, d.qty, d.amount_paise, d.created_at, "
        "COALESCE((SELECT SUM(di.qty) FROM damaged_cylinder_dispatch_items di "
        "          WHERE di.damage_event_id=d.id),0) AS dispatched_qty "
        "FROM cylinder_deposits d "
        "JOIN cylinder_types c ON c.id=d.cylinder_type_id "
        "LEFT JOIN suppliers s ON s.id=d.supplier_id "
        "WHERE d.kind='cancelled' AND c.active=1 "
        "ORDER BY d.created_at, d.id"
    ).fetchall()
    for r in damage_batches:
        batch_remaining = max(0, r["qty"] - r["dispatched_qty"])
        # Do not offer more cylinders than the current damaged stock count.
        available = min(batch_remaining, physical_remaining.get(r["cylinder_type_id"], 0))
        if available <= 0:
            continue
        per_cylinder = (r["amount_paise"] + (r["qty"] // 2)) // r["qty"] if r["qty"] else 0
        dispatch_options.append({
            "damage_event_id": r["damage_event_id"],
            "cylinder_type_id": r["cylinder_type_id"],
            "name": r["name"],
            "supplier_id": r["supplier_id"],
            "supplier_name": r["supplier_name"],
            "remaining_qty": available,
            "deposit_reference": to_rupees(per_cylinder),
            "damaged_at": r["created_at"],
        })
        physical_remaining[r["cylinder_type_id"]] -= available

    return jsonify({
        "cylinders": cylinders, "damaged": damaged,
        "damaged_dispatch_options": dispatch_options,
        "suppliers": [{"id": r["id"], "name": r["name"]} for r in db.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name COLLATE NOCASE")],
        "deposits": {"paid": to_rupees(totals.get("paid", 0)), "cancelled": to_rupees(totals.get("cancelled", 0)),
                     "refunded": to_rupees(totals.get("refunded", 0)),
                     "refunded_cash": to_rupees(by_mode.get("cash", 0)), "refunded_bank": to_rupees(by_mode.get("bank", 0)),
                     "held": to_rupees(max(0, totals.get("paid", 0) - totals.get("cancelled", 0) - totals.get("refunded", 0)))},
    })


# ---------- which supplier sells this cylinder (each supplier has its own price and deposit) ----------
@api_bp.post("/cylinders/<int:tid>/suppliers")
def cylinder_supplier_add(tid):
    data = body()
    sid = int_field(data.get("supplier_id"), "Supplier", field="supplier_id", minimum=1)
    price = money_field(data, "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        _supplier(db, sid)
        security = c["security_paise"] if data.get("security") in (None, "") else money_field(data, "security", "Security deposit")
        db.execute("INSERT INTO supplier_items (supplier_id, cylinder_type_id, purchase_price_paise, security_paise) VALUES (?,?,?,?) "
                   "ON CONFLICT(supplier_id, cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise, "
                   "security_paise=excluded.security_paise", (sid, tid, price, security))
    return jsonify({"ok": True}), 201


@api_bp.put("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_price(tid, sid):
    data = body()
    price = money_field(data, "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        link = _link(db, tid, sid)
        security = _security(link, c) if data.get("security") in (None, "") else money_field(data, "security", "Security deposit")
        db.execute("UPDATE supplier_items SET purchase_price_paise=?, security_paise=? WHERE supplier_id=? AND cylinder_type_id=?",
                   (price, security, sid, tid))   # cylinders already bought keep the price and deposit they were bought at
    return jsonify({"ok": True})


@api_bp.delete("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_remove(tid, sid):
    db = get_db()
    with transaction(db):   # old purchases keep their supplier; only the link is removed
        db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
    return jsonify({"ok": True})


@api_bp.post("/cylinders/<int:tid>/suppliers/<int:sid>/adjust")
def cylinder_supplier_adjust(tid, sid):
    """Type what you really have FROM THIS SUPPLIER. The size's total changes by the same difference."""
    data = body()
    full = int_field(data.get("full"), "Full cylinders", field="full", maximum=1_000_000)
    empty = int_field(data.get("empty"), "Empty cylinders", field="empty", maximum=1_000_000)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        link = _link(db, tid, sid)
        have_full = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM stock_lots WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()[0]
        d_full, d_empty = full - have_full, empty - link["empty_qty"]
        if d_full or d_empty:
            if c["full_qty"] + d_full < 0 or c["empty_qty"] + d_empty < 0:
                raise ApiError("That is more than the stock you have in total for this size. Use Adjust stock on the size first.", 409)
            mid = _movement(db, tid, "adjustment", full=d_full, empty=d_empty, note="Adjusted from supplier card")
            db.execute("UPDATE cylinder_types SET full_qty=full_qty+?, empty_qty=empty_qty+? WHERE id=?", (d_full, d_empty, tid))
            db.execute("UPDATE supplier_items SET empty_qty=? WHERE supplier_id=? AND cylinder_type_id=?", (empty, sid, tid))
            if d_full > 0:
                lid = lots.add_lot(db, tid, d_full, link["purchase_price_paise"], date.today().isoformat(), None, "adjustment")
                db.execute("UPDATE stock_lots SET supplier_id=? WHERE id=?", (sid, lid))
            elif d_full < 0:
                _take_full(db, tid, sid, -d_full, "adjustment", mid)
    return jsonify({"ok": True})


# ---------- damaged cylinders ----------
@api_bp.post("/stock/damaged/add")
def damaged_add():
    """Mark cylinders damaged. They leave the empty (or full) stock and their security deposit is cancelled."""
    data = body()
    source = data.get("source") or "empty"
    if source not in ("empty", "full"):
        raise ApiError("Choose whether the cylinders were empty or full.", field="source")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("Select at least one cylinder.")
    db = get_db()
    with transaction(db):
        supplier_id = _optional_supplier(db, data)
        for it in items:
            tid = int_field(it.get("cylinder_type_id"), "Cylinder", minimum=1)
            c = _cylinder(db, tid)
            qty = int_field(it.get("qty"), f"{c['name']} count", field=f"q{tid}", minimum=1, maximum=1_000_000)
            have = c["empty_qty"] if source == "empty" else c["full_qty"]
            if qty > have:
                raise ApiError(f"{c['name']}: only {have} {source} cylinder(s) in stock.", 409, field=f"q{tid}")
            dep = _default_deposit(db, it, tid, supplier_id, c)
            mid = _movement(db, tid, "damaged", full=-qty if source == "full" else 0,
                            empty=-qty if source == "empty" else 0, damaged=qty, note="Marked damaged")
            db.execute(f"UPDATE cylinder_types SET {source}_qty={source}_qty-?, damaged_qty=damaged_qty+? WHERE id=?", (qty, qty, tid))
            if source == "full":
                _take_full(db, tid, supplier_id, qty, "damaged", mid)
            else:
                _take_empty(db, tid, supplier_id, qty)
            _deposit_event(db, tid, supplier_id, "cancelled", qty, qty * dep, "Cylinder damaged")
    return jsonify({"ok": True})


@api_bp.post("/stock/damaged/send-back")
def damaged_send_back():
    """Record physical dispatch of already-damaged cylinders; no deposit money moves here."""
    data = body()
    dispatch_date = day_field(data, "date", "Dispatch date")
    note = text(data, "note", "Note", max_len=200)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("Select at least one damaged-cylinder row to send back.")

    db = get_db()
    with transaction(db):
        parsed = []
        seen_events = set()
        qty_by_type = {}

        # Validate every selected row before writing anything.
        for item in items:
            if not isinstance(item, dict):
                raise ApiError("Invalid damaged-cylinder dispatch row.")

            event_id = int_field(item.get("damage_event_id"), "Damage record", minimum=1)
            if event_id in seen_events:
                raise ApiError("A damaged-cylinder row was selected more than once.", 409)
            seen_events.add(event_id)

            event = db.execute(
                "SELECT d.id, d.cylinder_type_id, d.qty, d.amount_paise, "
                "COALESCE((SELECT SUM(di.qty) FROM damaged_cylinder_dispatch_items di "
                "          WHERE di.damage_event_id=d.id),0) AS dispatched_qty "
                "FROM cylinder_deposits d WHERE d.id=? AND d.kind='cancelled'",
                (event_id,),
            ).fetchone()
            if not event:
                raise ApiError("This damaged-cylinder record was not found.", 404)
            if event["qty"] <= 0:
                raise ApiError("This damaged-cylinder record has an invalid quantity.", 409)

            qty = int_field(item.get("qty"), "Dispatch quantity", field="qty", minimum=1, maximum=1_000_000)
            remaining = event["qty"] - event["dispatched_qty"]
            if qty > remaining:
                raise ApiError(f"Only {max(0, remaining)} cylinder(s) remain in this damaged batch.", 409)

            tid = event["cylinder_type_id"]
            _cylinder(db, tid)
            supplier_id = _optional_supplier(db, item)  # destination; does not alter the original damage event

            if item.get("deposit_reference") in (None, ""):
                deposit_reference = (event["amount_paise"] + (event["qty"] // 2)) // event["qty"]
            else:
                deposit_reference = money_field(
                    item, "deposit_reference", "Deposit reference", allow_zero=True
                )

            parsed.append({
                "event_id": event_id,
                "cylinder_type_id": tid,
                "qty": qty,
                "supplier_id": supplier_id,
                "deposit_reference_paise": deposit_reference,
            })
            qty_by_type[tid] = qty_by_type.get(tid, 0) + qty

        # Several damage batches can refer to the same cylinder size.
        # Their combined dispatch must still fit the current damaged stock.
        for tid, qty in qty_by_type.items():
            cylinder = _cylinder(db, tid)
            if qty > cylinder["damaged_qty"]:
                raise ApiError(
                    f"Only {cylinder['damaged_qty']} damaged cylinder(s) of {cylinder['name']} are currently in stock.",
                    409,
                )

        dispatch_id = db.execute(
            "INSERT INTO damaged_cylinder_dispatches(dispatch_date, note) VALUES(?,?)",
            (dispatch_date, note),
        ).lastrowid

        for item in parsed:
            tid = item["cylinder_type_id"]
            qty = item["qty"]
            sid = item["supplier_id"]
            supplier_name = _supplier(db, sid)["name"] if sid is not None else None

            db.execute(
                "INSERT INTO damaged_cylinder_dispatch_items "
                "(dispatch_id, damage_event_id, cylinder_type_id, supplier_id, qty, deposit_reference_paise) "
                "VALUES(?,?,?,?,?,?)",
                (dispatch_id, item["event_id"], tid, sid, qty, item["deposit_reference_paise"]),
            )

            changed = db.execute(
                "UPDATE cylinder_types SET damaged_qty=damaged_qty-? "
                "WHERE id=? AND damaged_qty>=?",
                (qty, tid, qty),
            ).rowcount
            if not changed:
                raise ApiError("Damaged stock changed while this dispatch was being saved. Reload and try again.", 409)

            movement_note = "Damaged cylinders sent back"
            if supplier_name:
                movement_note += f" to {supplier_name}"
            if note:
                movement_note += f" · {note}"
            _movement(
                db, tid, "damaged_send_back", ref_id=dispatch_id,
                damaged=-qty, note=movement_note,
            )

    return jsonify({"ok": True, "dispatch_id": dispatch_id, "date": dispatch_date, "items": len(parsed)})


# ---------- empty cylinders sent back to the supplier ----------
@api_bp.post("/cylinders/<int:tid>/send-back")
def cylinder_send_back(tid):
    """Good empty cylinders go back to a supplier and the security deposit comes back as real money."""
    data = body()
    mode = data.get("received_in") or "cash"
    if mode not in RECEIVED_IN:
        raise ApiError("Choose where the money was received.", field="received_in")
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        qty = int_field(data.get("qty"), "Cylinders", field="qty", minimum=1, maximum=1_000_000)
        if qty > c["empty_qty"]:
            raise ApiError(f"Only {c['empty_qty']} empty cylinder(s) in stock.", 409, field="qty")
        supplier_id = _optional_supplier(db, data)
        dep = _default_deposit(db, data, tid, supplier_id, c)
        _movement(db, tid, "sent_back", empty=-qty, note="Sent back to supplier")
        db.execute("UPDATE cylinder_types SET empty_qty=empty_qty-? WHERE id=?", (qty, tid))
        _take_empty(db, tid, supplier_id, qty)
        _deposit_event(db, tid, supplier_id, "refunded", qty, qty * dep, "Sent back to supplier", mode)
    return jsonify({"ok": True})