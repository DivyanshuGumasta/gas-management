"""Customer API: list, add / edit / delete, ledger, cylinders held, empties
returned, special prices.

Balance sign everywhere: + = customer owes us (udhaar / "To receive"),
                         - = customer has paid extra (advance).
Balance = opening + sum(active sales: total - paid) - sum(active payments).
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from db import get_db, transaction, sole_active_supplier_id
from money import format_inr, to_paise, to_rupees

from . import api_bp
from .util import (RECEIVED_IN, ApiError, body, day_field, gstin_field, int_field,
                   money_field, phone_field, state_code_field, text)

BALANCE_SQL = """c.opening_balance_paise
    + COALESCE((SELECT SUM(s.total_paise - s.paid_paise) FROM sales s
                WHERE s.customer_id = c.id AND s.status = 'active'), 0)
    - COALESCE((SELECT SUM(p.amount_paise) FROM payments p
                WHERE p.customer_id = c.id AND p.status = 'active'), 0)"""
HELD_SQL = "COALESCE((SELECT SUM(l.delta) FROM cylinder_ledger l WHERE l.customer_id = c.id), 0)"
SELECT = f"SELECT c.*, {BALANCE_SQL} AS balance, {HELD_SQL} AS held FROM customers c"


def _dict(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "address": r["address"],
        "billing_address": r["billing_address"],
        "gstin": r["gstin"],
        "state_code": r["state_code"],
        "note": r["note"],
        "type": r["type"],
        "type_label": r["type"].capitalize(),
        "opening_balance": to_rupees(r["opening_balance_paise"]),
        "balance": to_rupees(r["balance"]),
        "cylinders": r["held"],
        "created_at": r["created_at"],
    }


def customer_row(cid, include_inactive=False):
    sql = SELECT + " WHERE c.id = ?" + ("" if include_inactive else " AND c.active = 1")
    r = get_db().execute(sql, (cid,)).fetchone()
    if not r:
        raise ApiError("Customer not found.", 404)
    return r


def customer_dict(cid):
    return _dict(customer_row(cid))


def _parse_opening_held(db, held):
    """Validate opening cylinder holdings before any customer/stock row is written."""
    if not isinstance(held, list):
        raise ApiError("Held cylinders must be a list.", field="held")
    parsed, seen = [], set()
    for item in held:
        if not isinstance(item, dict):
            raise ApiError("Invalid held-cylinder row.", field="held")
        tid = int_field(item.get("cylinder_type_id"), "Cylinder size", minimum=1)
        cylinder = db.execute("SELECT * FROM cylinder_types WHERE id=? AND active=1", (tid,)).fetchone()
        if not cylinder:
            raise ApiError("Cylinder size not found or inactive.", 404, "cylinder_type_id")
        qty = int_field(item.get("qty"), "Held cylinder quantity", field="qty", minimum=1, maximum=100000)
        if "supplier_id" not in item:
            sid = sole_active_supplier_id(db)
        else:
            raw_sid = item.get("supplier_id")
            sid = None if raw_sid in (None, "", "0") else int_field(raw_sid, "Supplier", field="supplier_id", minimum=1)
        if sid is not None:
            if not db.execute("SELECT 1 FROM suppliers WHERE id=? AND active=1", (sid,)).fetchone():
                raise ApiError("Supplier not found or inactive.", 409, "supplier_id")
            if not db.execute("SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)).fetchone():
                raise ApiError(f"Supplier is not linked to {cylinder['name']} in Stock & Price.", 409, "supplier_id")
        key = (tid, sid)
        if key in seen:
            raise ApiError("The same cylinder size and supplier can appear only once.", 409, "held")
        seen.add(key)
        deposit_each = cylinder["security_paise"] if item.get("deposit_each") in (None, "") else money_field(
            item, "deposit_each", f"{cylinder['name']} deposit per cylinder", allow_zero=True)
        parsed.append({"tid": tid, "qty": qty, "supplier_id": sid, "deposit_each": deposit_each})
    return parsed


def _record_opening_held(db, customer_id, held):
    day = date.today().isoformat()
    for item in held:
        tid, qty, sid = item["tid"], item["qty"], item["supplier_id"]
        db.execute(
            "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
            "VALUES(?,?,?,'opening',NULL,?,?)",
            (customer_id, tid, qty, day, "Cylinders already with customer"),
        )
        db.execute("UPDATE cylinder_types SET with_customers_qty=with_customers_qty+? WHERE id=?", (qty, tid))
        db.execute(
            "INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,supplier_id,kind,qty,amount_paise,event_date,status,note) "
            "VALUES(?,?,NULL,?,'received',?,?,?,'active','Opening cylinders')",
            (customer_id, tid, sid, qty, qty * item["deposit_each"], day),
        )


def customer_holdings_for_type(db, customer_id, cylinder_type_id):
    """Return supplier-specific customer holdings plus legacy ledger-only unassigned stock."""
    cylinder = db.execute("SELECT name FROM cylinder_types WHERE id=?", (cylinder_type_id,)).fetchone()
    if not cylinder:
        return []
    events = db.execute(
        "SELECT e.supplier_id,s.name AS supplier_name, "
        "SUM(CASE e.kind WHEN 'received' THEN e.qty ELSE -e.qty END) AS qty, "
        "SUM(CASE e.kind WHEN 'received' THEN e.amount_paise ELSE -e.amount_paise END) AS amount "
        "FROM customer_deposit_events e LEFT JOIN suppliers s ON s.id=e.supplier_id "
        "WHERE e.customer_id=? AND e.cylinder_type_id=? AND e.status='active' "
        "GROUP BY e.supplier_id,s.name ORDER BY e.supplier_id",
        (customer_id, cylinder_type_id),
    ).fetchall()
    result, recorded_qty = [], 0
    for row in events:
        qty = max(0, int(row["qty"] or 0))
        amount = max(0, int(row["amount"] or 0))
        if qty <= 0:
            continue
        recorded_qty += qty
        each = int((Decimal(amount) / Decimal(qty)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        result.append({
            "cylinder_type_id": cylinder_type_id, "name": cylinder["name"],
            "supplier_id": row["supplier_id"], "supplier_name": row["supplier_name"],
            "qty": qty, "deposit_each": to_rupees(each), "deposit_total": to_rupees(amount),
        })
    ledger_qty = db.execute(
        "SELECT COALESCE(SUM(delta),0) FROM cylinder_ledger WHERE customer_id=? AND cylinder_type_id=?",
        (customer_id, cylinder_type_id),
    ).fetchone()[0]
    unassigned = max(0, int(ledger_qty or 0) - recorded_qty)
    if unassigned:
        result.append({"cylinder_type_id": cylinder_type_id, "name": cylinder["name"],
                       "supplier_id": None, "supplier_name": None, "qty": unassigned,
                       "deposit_each": "0.00", "deposit_total": "0.00"})
    return result


def _customer_holdings_payload(db, customer_id):
    rows = db.execute(
        "SELECT DISTINCT t.id,t.name,t.sort_order FROM cylinder_types t "
        "JOIN cylinder_ledger l ON l.cylinder_type_id=t.id "
        "WHERE l.customer_id=? ORDER BY t.sort_order,t.id", (customer_id,),
    ).fetchall()
    return [holding for row in rows for holding in customer_holdings_for_type(db, customer_id, row["id"])]


# ---------------------------------------------------------------- list
@api_bp.get("/customers")
def customers_list():
    q = (request.args.get("q") or "").strip()
    ctype = request.args.get("type")
    where, params = " WHERE c.active = 1", []
    if q:
        where += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.address LIKE ?)"
        params += [f"%{q}%"] * 3
    if ctype in ("retail", "wholesale"):
        where += " AND c.type = ?"
        params.append(ctype)
    rows = get_db().execute(SELECT + where + " ORDER BY c.name COLLATE NOCASE", params).fetchall()
    if request.args.get("owing") == "1":
        rows = [r for r in rows if r["balance"] > 0]
    return jsonify([_dict(r) for r in rows])


@api_bp.get("/customers/summary")
def customers_summary():
    rows = get_db().execute(SELECT + " WHERE c.active = 1").fetchall()
    owing = [r["balance"] for r in rows if r["balance"] > 0]
    advance = [-r["balance"] for r in rows if r["balance"] < 0]
    return jsonify(
        {
            "total_udhaar": to_rupees(sum(owing)),
            "owing_count": len(owing),
            "total_advance": to_rupees(sum(advance)),
            "customer_count": len(rows),
        }
    )


# ------------------------------------------------------ create / edit / delete
def _parse(data, self_id=None):
    name = text(data, "name", "Customer name", required=True, max_len=80)
    ctype = data.get("type", "retail")
    if ctype not in ("retail", "wholesale"):
        raise ApiError("Choose Retail or Wholesale.", field="type")
    phone = phone_field(data)
    kind = data.get("opening_type", "udhaar")
    if kind not in ("udhaar", "advance"):
        raise ApiError("Choose Udhaar or Advance.", field="opening_type")
    amount = money_field(data, "opening_amount", "Previous balance")
    dup = get_db().execute(
        "SELECT id FROM customers WHERE active = 1 AND lower(name) = lower(?) "
        "AND COALESCE(phone, '') = COALESCE(?, '') AND id IS NOT ?",
        (name, phone, self_id),
    ).fetchone()
    if dup:
        raise ApiError("A customer with this name and phone already exists.", 409, field="name")
    gstin = gstin_field(data)
    state_code = state_code_field(data)
    if gstin and not state_code:
        state_code = gstin[:2]
    if gstin and state_code != gstin[:2]:
        raise ApiError("Customer state code must match the first two digits of the GSTIN.", field="state_code")
    return {
        "name": name,
        "type": ctype,
        "phone": phone,
        "address": text(data, "address", "Address", max_len=200),
        "billing_address": text(data, "billing_address", "Billing address", max_len=250),
        "gstin": gstin,
        "state_code": state_code,
        "note": text(data, "note", "Note", max_len=500),
        "opening": amount if kind == "udhaar" else -amount,
    }


@api_bp.post("/customers")
def customer_create():
    data = body()
    f = _parse(data)
    db = get_db()
    with transaction(db):
        held = _parse_opening_held(db, data.get("held", []))
        cid = db.execute(
            "INSERT INTO customers (name, phone, address, type, opening_balance_paise, note, billing_address, gstin, state_code)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f["name"], f["phone"], f["address"], f["type"], f["opening"], f["note"],
             f["billing_address"], f["gstin"], f["state_code"]),
        ).lastrowid
        _record_opening_held(db, cid, held)
    return jsonify(customer_dict(cid)), 201


@api_bp.get("/customers/<int:cid>")
def customer_get(cid):
    return jsonify(customer_dict(cid))

@api_bp.get("/customers/<int:cid>/held-cylinders")
def customer_held_cylinders(cid):
    """Return the customer's currently held cylinder count, grouped by size."""
    customer_row(cid)
    rows = get_db().execute(
        "SELECT cylinder_type_id, COALESCE(SUM(delta),0) AS qty "
        "FROM cylinder_ledger WHERE customer_id=? GROUP BY cylinder_type_id",
        (cid,),
    ).fetchall()
    return jsonify({str(row["cylinder_type_id"]): max(0, row["qty"])
                    for row in rows if row["qty"] > 0})

@api_bp.get("/customers/<int:cid>/holdings")
def customer_holdings(cid):
    customer_row(cid, include_inactive=True)
    return jsonify(_customer_holdings_payload(get_db(), cid))


@api_bp.post("/customers/<int:cid>/opening-cylinders")
def customer_opening_cylinders(cid):
    customer_row(cid)
    data = body()
    held = data.get("held")
    if not isinstance(held, list) or not held:
        raise ApiError("Add at least one opening cylinder row.", field="held")
    db = get_db()
    with transaction(db):
        parsed = _parse_opening_held(db, held)
        _record_opening_held(db, cid, parsed)
    return jsonify(_customer_holdings_payload(db, cid))


@api_bp.put("/customers/<int:cid>")
def customer_update(cid):
    old = customer_row(cid)
    data = body()
    f = _parse(data, self_id=cid)
    for key in ("billing_address", "gstin", "state_code"):
        if key not in data:
            f[key] = old[key]
    db = get_db()
    with transaction(db):
        db.execute(
            "UPDATE customers SET name=?, phone=?, address=?, type=?, opening_balance_paise=?, note=?,"
            " billing_address=?, gstin=?, state_code=? WHERE id=?",
            (f["name"], f["phone"], f["address"], f["type"], f["opening"], f["note"],
             f["billing_address"], f["gstin"], f["state_code"], cid),
        )
    return jsonify(customer_dict(cid))


@api_bp.delete("/customers/<int:cid>")
def customer_delete(cid):
    """Allowed only when balance is clear and no cylinders are held.
    Customers with history are hidden (kept for old bills and reports);
    customers never used are removed completely."""
    db = get_db()
    c = customer_row(cid)
    if c["balance"] > 0:
        raise ApiError(f"{c['name']} still owes you {format_inr(c['balance'])}. Receive the payment first.", 409)
    if c["balance"] < 0:
        raise ApiError(f"{c['name']} has {format_inr(-c['balance'])} paid in advance. Settle it first.", 409)
    if c["held"] != 0:
        raise ApiError(f"{c['name']} still has {c['held']} cylinder(s). Record return of empties first.", 409)
    has_history = db.execute(
        "SELECT (SELECT COUNT(*) FROM sales WHERE customer_id = :c) + "
        "(SELECT COUNT(*) FROM payments WHERE customer_id = :c) + "
        "(SELECT COUNT(*) FROM cylinder_ledger WHERE customer_id = :c)",
        {"c": cid},
    ).fetchone()[0]
    with transaction(db):
        if has_history or c["opening_balance_paise"]:
            db.execute("UPDATE customers SET active = 0 WHERE id = ?", (cid,))
        else:
            db.execute("DELETE FROM customer_prices WHERE customer_id = ?", (cid,))
            db.execute("DELETE FROM customers WHERE id = ?", (cid,))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- ledger
@api_bp.get("/customers/<int:cid>/ledger")
def customer_ledger(cid):
    db = get_db()
    c = customer_row(cid, include_inactive=True)
    opening = c["opening_balance_paise"]
    rows = [{
        "kind": "opening", "date": None, "detail": "Opening balance", "sub": None,
        "sale": to_rupees(opening) if opening > 0 else None,
        "paid": to_rupees(-opening) if opening < 0 else None,
        "balance": to_rupees(opening), "status": "active",
    }]

    events = []
    for s in db.execute(
        "SELECT id, number, sale_date, created_at, total_paise, paid_paise, status FROM sales "
        "WHERE customer_id = ?", (cid,)
    ):
        items = db.execute(
            "SELECT si.qty_out, t.name FROM sale_items si JOIN cylinder_types t ON t.id = si.cylinder_type_id "
            "WHERE si.sale_id = ? AND si.qty_out > 0 ORDER BY si.id", (s["id"],)
        ).fetchall()
        events.append(((s["sale_date"], s["created_at"], 0, s["id"]), {
            "kind": "sale", "id": s["id"], "date": s["sale_date"], "detail": f"Sale {s['number']}",
            "sub": ", ".join(f"{i['qty_out']} x {i['name']}" for i in items) or None,
            "sale": to_rupees(s["total_paise"]),
            "paid": to_rupees(s["paid_paise"]) if s["paid_paise"] else None,
            "status": s["status"], "delta": s["total_paise"] - s["paid_paise"],
        }))
    for p in db.execute(
        "SELECT id, number, payment_date, created_at, amount_paise, received_in, note, status "
        "FROM payments WHERE customer_id = ?", (cid,)
    ):
        sub = RECEIVED_IN.get(p["received_in"], p["received_in"]) + (f" · {p['note']}" if p["note"] else "")
        events.append(((p["payment_date"], p["created_at"], 1, p["id"]), {
            "kind": "payment", "id": p["id"], "date": p["payment_date"],
            "detail": f"Payment received {p['number']}", "sub": sub, "sale": None,
            "paid": to_rupees(p["amount_paise"]), "status": p["status"], "delta": -p["amount_paise"],
        }))

    running = opening
    for _, e in sorted(events, key=lambda x: x[0]):
        if e["status"] == "active":          # cancelled entries are shown but never counted
            running += e["delta"]
        e["balance"] = to_rupees(running)
        del e["delta"]
        rows.append(e)
    return jsonify({"rows": rows, "closing_balance": to_rupees(running)})


# ------------------------------------------------------- cylinders held
def _held(db, cid):
    return db.execute(
        "SELECT l.cylinder_type_id AS id, t.name, SUM(l.delta) AS qty FROM cylinder_ledger l "
        "JOIN cylinder_types t ON t.id = l.cylinder_type_id WHERE l.customer_id = ? "
        "GROUP BY l.cylinder_type_id HAVING SUM(l.delta) <> 0 ORDER BY t.sort_order, t.id", (cid,)
    ).fetchall()


def _cylinders_payload(db, cid):
    held = _held(db, cid)
    history = db.execute(
        "SELECT l.entry_date, l.delta, l.ref_type, l.note, t.name, s.number AS sale_number "
        "FROM cylinder_ledger l JOIN cylinder_types t ON t.id = l.cylinder_type_id "
        "LEFT JOIN sales s ON l.ref_type = 'sale' AND s.id = l.ref_id "
        "WHERE l.customer_id = ? ORDER BY l.entry_date DESC, l.id DESC LIMIT 100", (cid,)
    ).fetchall()
    label = {"return": "Empties returned", "opening": "Opening"}
    return {
        "total": sum(h["qty"] for h in held),
        "held": [{"cylinder_type_id": h["id"], "name": h["name"], "qty": h["qty"]} for h in held],
        "history": [{
            "date": h["entry_date"], "type": h["name"], "delta": h["delta"], "note": h["note"],
            "detail": f"Sale {h['sale_number']}" if h["sale_number"] else label.get(h["ref_type"], "Adjustment"),
        } for h in history],
    }


@api_bp.get("/customers/<int:cid>/cylinders")
def customer_cylinders(cid):
    customer_row(cid, include_inactive=True)
    return jsonify(_cylinders_payload(get_db(), cid))


@api_bp.post("/customers/<int:cid>/return-empties")
def return_empties(cid):
    customer_row(cid)
    raise ApiError("Record returns from Sales → New sale so deposits stay correct.", 410)


# ------------------------------------------------------- special prices
def _prices_payload(db, c):
    special = {r["cylinder_type_id"]: r["price_paise"] for r in db.execute(
        "SELECT cylinder_type_id, price_paise FROM customer_prices WHERE customer_id = ?", (c["id"],))}
    col = "wholesale_price_paise" if c["type"] == "wholesale" else "sale_price_paise"
    return [{
        "cylinder_type_id": t["id"], "name": t["name"], "default_price": to_rupees(t[col]),
        "special_price": to_rupees(special[t["id"]]) if t["id"] in special else None,
    } for t in db.execute(
        f"SELECT id, name, {col} FROM cylinder_types WHERE active = 1 ORDER BY sort_order, id")]


@api_bp.get("/customers/<int:cid>/prices")
def customer_prices(cid):
    return jsonify(_prices_payload(get_db(), customer_row(cid, include_inactive=True)))


@api_bp.put("/customers/<int:cid>/prices")
def customer_prices_save(cid):
    db = get_db()
    c = customer_row(cid)
    prices = body().get("prices")
    if not isinstance(prices, dict):
        raise ApiError("Send the prices to save.")
    valid = {r["id"] for r in db.execute("SELECT id FROM cylinder_types")}
    parsed = {}
    for key, value in prices.items():
        tid = int_field(key, "Cylinder type", minimum=1)
        if tid not in valid:
            raise ApiError("Unknown cylinder size.", 404)
        if value is None or str(value).strip() == "":
            parsed[tid] = None
        else:
            parsed[tid] = money_field({f"price_{tid}": value}, f"price_{tid}", "Price", allow_zero=False)
    with transaction(db):
        for tid, paise in parsed.items():
            if paise is None:
                db.execute("DELETE FROM customer_prices WHERE customer_id=? AND cylinder_type_id=?", (cid, tid))
            else:
                db.execute(
                    "INSERT INTO customer_prices (customer_id, cylinder_type_id, price_paise) VALUES (?,?,?) "
                    "ON CONFLICT(customer_id, cylinder_type_id) DO UPDATE SET price_paise = excluded.price_paise",
                    (cid, tid, paise))
    return jsonify(_prices_payload(db, c))
