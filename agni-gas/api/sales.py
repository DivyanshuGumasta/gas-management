"""Persistent sales invoices. All money is stored in integer paise.

Product lines snapshot name, HSN, unit, selling rate and GST split. Refundable
customer cylinder deposits are recorded separately from taxable product lines
and separately from supplier deposits in cylinder_deposits.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from io import BytesIO
from flask import jsonify, request, send_file

import lots
from db import get_db, next_number, transaction
from money import amount_in_words, to_paise, to_rupees
from . import api_bp
from .business import business_dict, missing_business
from .customers import customer_holdings_for_type, customer_row
from .stock import _movement
from .stock_suppliers import (_give_empty, _security, _take_empty, _take_full, _supplier)
from .util import (ApiError, RECEIVED_IN, body, day_field, gst_rate_text,
                   int_field, money_field, quantity_milli_field, text, STATES)

def _round_ratio(numerator, denominator):
    if denominator <= 0:
        return 0
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _qty(value, label):
    return int_field(value if value not in (None, "") else 0, label, minimum=0, maximum=100000)


def _money(raw, label, allow_zero=True):
    try:
        value = to_paise(raw)
    except (ValueError, TypeError, ArithmeticError):
        raise ApiError(f"{label} is not a valid amount.", field=label)
    if value < 0 or (value == 0 and not allow_zero):
        raise ApiError(f"{label} must be {'zero or more' if allow_zero else 'more than zero'}.", field=label)
    return value

def _time_label(created_at):
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
    except (TypeError, ValueError):
        return ""


def _resolve_supplier(db, raw, field, tid, cylinder_name, customer_id=None, is_return=False):
    """Resolve explicit, sole-active, or inferable return supplier; validate its link."""
    value = raw.get(field) if isinstance(raw, dict) else None
    sid = None if value in (None, "", "0") else int_field(value, "Supplier", field=field, minimum=1)
    active = [r["id"] for r in db.execute("SELECT id FROM suppliers WHERE active=1 ORDER BY id").fetchall()]
    if sid is None and len(active) == 1:
        sid = active[0]
    elif sid is None and len(active) > 1 and is_return and customer_id:
        held = customer_holdings_for_type(db, customer_id, tid)
        candidates = {r["supplier_id"] for r in held if r["supplier_id"] is not None and r["qty"] > 0}
        if len(candidates) == 1:
            sid = next(iter(candidates))
    if sid is None and len(active) > 1:
        action_word = "return" if is_return else "use"
        raise ApiError(f"Choose which supplier's cylinder to {action_word} ({cylinder_name}).", 422, field)
    if sid is not None:
        _supplier(db, sid)
        if not db.execute("SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)).fetchone():
            raise ApiError(f"{cylinder_name} is not linked to the selected supplier in Stock & Price.", 409, field)
    return sid


def _return_sources(db, customer_id, tid, return_supplier_id, qty, cylinder_name):
    """Allocate returns to matching supplier holdings first, then unassigned holdings."""
    if qty <= 0:
        return []
    rows = customer_holdings_for_type(db, customer_id, tid)
    priority = [return_supplier_id]
    if None not in priority:
        priority.append(None)
    remaining, allocations = qty, []
    for sid in priority:
        row = next((r for r in rows if r["supplier_id"] == sid), None)
        if not row or row["qty"] <= 0:
            continue
        take = min(remaining, row["qty"])
        if take:
            allocations.append({"supplier_id": sid, "qty": take,
                                "available_qty": row["qty"],
                                "available_paise": to_paise(row["deposit_total"])})
            remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise ApiError(f"{cylinder_name}: the customer does not hold enough cylinders from the selected supplier or unassigned stock.", 409)
    return allocations


def _split_return_sources(sources, good_qty, damaged_qty):
    """Split a single physical allocation in good-first order to prevent double use."""
    good, damaged = [], []
    good_left, damaged_left = good_qty, damaged_qty
    for source in sources:
        source_qty = int(source["available_qty"])
        source_amount = int(source["available_paise"])
        if good_left and source_qty:
            take = min(good_left, source_qty)
            amount = source_amount if take == source_qty else _round_ratio(source_amount * take, source_qty)
            good.append({"supplier_id": source["supplier_id"], "qty": take,
                         "available_qty": source_qty, "available_paise": source_amount})
            source_qty -= take
            source_amount -= amount
            good_left -= take
        if damaged_left and source_qty:
            take = min(damaged_left, source_qty)
            damaged.append({"supplier_id": source["supplier_id"], "qty": take,
                            "available_qty": source_qty, "available_paise": source_amount})
            damaged_left -= take
    if good_left or damaged_left:
        raise ApiError("The customer's held-cylinder allocation changed while saving this invoice.", 409)
    return good, damaged


def _allocate_discount(lines, discount, gross_total):
    """Allocate a proportional discount by largest remainder, exactly to the paise."""
    if not lines:
        return []
    if discount < 0 or discount > gross_total:
        raise ValueError("Discount must be between zero and the taxable subtotal.")
    if gross_total == 0:
        return [0 for _ in lines]
    shares, remainders = [], []
    allocated = 0
    for index, line in enumerate(lines):
        share, remainder = divmod(discount * line["gross_paise"], gross_total)
        share = min(line["gross_paise"], share)
        shares.append(share)
        remainders.append((remainder, index))
        allocated += share
    left = discount - allocated
    for _remainder, index in sorted(remainders, key=lambda item: (-item[0], item[1])):
        if left <= 0:
            break
        if shares[index] < lines[index]["gross_paise"]:
            shares[index] += 1
            left -= 1
    if left:
        raise ValueError("Could not allocate the discount exactly.")
    return shares


def _supplier_deposit_balance(db, tid, sid):
    row = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'paid' THEN qty ELSE -qty END),0) AS qty, "
        "COALESCE(SUM(CASE kind WHEN 'paid' THEN amount_paise ELSE -amount_paise END),0) AS amount "
        "FROM cylinder_deposits WHERE cylinder_type_id=? AND supplier_id=? AND status='active'",
        (tid, sid),
    ).fetchone()
    return max(0, int(row["qty"] or 0)), max(0, int(row["amount"] or 0))


def _line_label_amount(detail):
    if not detail:
        return "0.00"
    raw = str(detail).split(":", 1)[-1].strip().replace("Rs.", "").replace("Rs", "").replace(",", "")
    try:
        return to_rupees(to_paise(raw))
    except (ValueError, TypeError, ArithmeticError):
        return "0.00"


def _held_cylinders(db, customer_id, cylinder_type_id):
    return db.execute(
        "SELECT COALESCE(SUM(delta),0) FROM cylinder_ledger WHERE customer_id=? AND cylinder_type_id=?",
        (customer_id, cylinder_type_id),
    ).fetchone()[0]


def _insert_line(db, sale_id, line_no, line):
    db.execute(
        "INSERT INTO sale_lines(sale_id,line_no,kind,action,cylinder_type_id,item_id,supplier_id,description,hsn,unit,"
        "qty_milli,rate_paise,gross_paise,discount_paise,taxable_paise,gst_rate_bp,cgst_paise,sgst_paise,"
        "igst_paise,amount_paise,retained_paise,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sale_id, line_no, line["kind"], line.get("action"), line.get("cylinder_type_id"), line.get("item_id"),
         line.get("supplier_id"), line["description"], line.get("hsn"), line.get("unit", "NOS"),
         line.get("qty_milli", 0), line.get("rate_paise", 0), line.get("gross_paise", 0),
         line.get("discount_paise", 0), line.get("taxable_paise", 0), line.get("gst_rate_bp"),
         line.get("cgst_paise", 0), line.get("sgst_paise", 0), line.get("igst_paise", 0),
         line.get("amount_paise", 0), line.get("retained_paise", 0), line.get("detail")),
    )


def _sale_status(row):
    if row["status"] == "cancelled":
        return "cancelled"
    if row["paid_paise"] >= row["total_paise"]:
        return "paid"
    return "udhaar" if row["paid_paise"] == 0 else "partial"


def _line_payload(row):
    qty = Decimal(row["qty_milli"] or 0) / Decimal(1000)
    return {
        "kind": row["kind"], "action": row["action"], "name": row["description"],
        "hsn": row["hsn"], "qty": str(qty.normalize()), "unit": row["unit"],
        "rate": to_rupees(row["rate_paise"]), "amount": to_rupees(row["amount_paise"]),
        "taxable": to_rupees(row["taxable_paise"]), "gst_rate": gst_rate_text(row["gst_rate_bp"]),
        "supplier_id": row["supplier_id"], "retained": to_rupees(row["retained_paise"]),
        "cgst": to_rupees(row["cgst_paise"]), "sgst": to_rupees(row["sgst_paise"]),
        "igst": to_rupees(row["igst_paise"]), "detail": row["detail"],
    }


def _sale_payload(db, sale):
    rows = db.execute("SELECT * FROM sale_lines WHERE sale_id=? ORDER BY line_no,id", (sale["id"],)).fetchall()
    legacy = not rows
    try:
        business = json.loads(sale["business_snapshot_json"] or "{}") or {}
        customer = json.loads(sale["customer_snapshot_json"] or "null")
    except (TypeError, ValueError):
        business, customer = {}, None

    if legacy:
        business = {}
        if not customer and sale["customer_id"]:
            live_customer = db.execute(
                "SELECT id,name,phone,address FROM customers WHERE id=?", (sale["customer_id"],)
            ).fetchone()
            if live_customer:
                customer = {"id": live_customer["id"], "name": live_customer["name"],
                            "phone": live_customer["phone"], "address": live_customer["address"],
                            "billing_address": live_customer["address"]}
        legacy_rows = db.execute(
            "SELECT si.*,ct.name FROM sale_items si JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
            "WHERE si.sale_id=? ORDER BY si.id", (sale["id"],)
        ).fetchall()
        line_payloads = [{
            "kind": "product", "action": "refill", "name": row["name"], "hsn": None,
            "qty": str(int(row["qty_out"] or 0)), "unit": "NOS",
            "rate": to_rupees(row["rate_paise"]), "amount": to_rupees(row["amount_paise"]),
            "taxable": to_rupees(row["amount_paise"]), "gst_rate": None,
            "cgst": "0.00", "sgst": "0.00", "igst": "0.00",
            "detail": row["mode"], "supplier_id": None,
        } for row in legacy_rows]
    else:
        line_payloads = [_line_payload(row) for row in rows]

    retained_total = sum(int(row["retained_paise"] or 0) for row in rows)
    tax_summary = {
        "taxable": to_rupees(sale["taxable_paise"]), "cgst": to_rupees(sale["cgst_paise"]),
        "sgst": to_rupees(sale["sgst_paise"]), "igst": to_rupees(sale["igst_paise"]),
        "gst": to_rupees(sale["gst_paise"]),
    }
    grouped = {}
    for line in line_payloads:
        if line.get("kind") != "product":
            continue
        key = (line.get("name"), line.get("hsn"), line.get("gst_rate"), line.get("rate"), line.get("unit"))
        group = grouped.setdefault(key, {**line, "qty": Decimal("0"), "amount": Decimal("0"),
                                         "taxable": Decimal("0"), "cgst": Decimal("0"),
                                         "sgst": Decimal("0"), "igst": Decimal("0")})
        for field in ("qty", "amount", "taxable", "cgst", "sgst", "igst"):
            group[field] += Decimal(str(line.get(field) or 0))
    grouped_lines = []
    for group in grouped.values():
        for field in ("qty",):
            group[field] = str(group[field].normalize())
        for field in ("amount", "taxable", "cgst", "sgst", "igst"):
            group[field] = format(group[field].quantize(Decimal("0.01")), "f")
        grouped_lines.append(group)
    return {
        "id": sale["id"], "number": sale["number"], "date": sale["sale_date"],
        "title": "TAX INVOICE" if business.get("gstin") else "INVOICE",
        "place_state_name": STATES.get(sale["place_state_code"]),
        "business_state_name": STATES.get(business.get("state_code")),
        "customer_state_name": STATES.get((customer or {}).get("state_code")),
        "tax_summary": tax_summary, "grouped_lines": grouped_lines,
        "retained_deposits": to_rupees(retained_total),
        "amount_in_words": amount_in_words(sale["total_paise"]),
        "paid_label": ("Paid back" if sale["total_paise"] < 0 else
                       ("Not paid" if int(sale["paid_paise"] or 0) == 0 else
                        ("Paid in bank / UPI" if sale["received_in"] == "bank" else "Paid in cash"))),
        "time": _time_label(sale["created_at"]), "status": _sale_status(sale),
        "customer": customer, "business": business, "legacy": legacy,
        "place_state_code": sale["place_state_code"], "reverse_charge": False,
        "note": sale["note"], "lines": line_payloads,
        "subtotal": to_rupees(sale["subtotal_paise"]), "discount": to_rupees(sale["discount_paise"]),
        "taxable": to_rupees(sale["taxable_paise"]), "cgst": to_rupees(sale["cgst_paise"]),
        "sgst": to_rupees(sale["sgst_paise"]), "igst": to_rupees(sale["igst_paise"]),
        "gst": to_rupees(sale["gst_paise"]), "gst_percent": sale["gst_percent"],
        "deposit_received": to_rupees(sale["deposit_received_paise"]),
        "deposit_refunded": to_rupees(sale["deposit_refunded_paise"]),
        "total": to_rupees(sale["total_paise"]), "paid": to_rupees(sale["paid_paise"]),
        "due": to_rupees(max(0, sale["total_paise"] - sale["paid_paise"])),
        "received_in": sale["received_in"], "cancel_reason": sale["cancel_reason"],
        "cancelled_at": sale["cancelled_at"],
        "cancelled_at_label": (datetime.strptime(sale["cancelled_at"], "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y · %I:%M %p")
                               if sale["cancelled_at"] else None),
    }


@api_bp.get("/sales")
def sales_list():
    db = get_db()
    where, args = ["1=1"], []
    day_from, day_to = request.args.get("from"), request.args.get("to")
    q = (request.args.get("q") or "").strip()
    if day_from:
        where.append("s.sale_date>=?"); args.append(day_from)
    if day_to:
        where.append("s.sale_date<=?"); args.append(day_to)
    if q:
        where.append("(s.number LIKE ? OR COALESCE(c.name,'Walk-in customer') LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])
    clause = " AND ".join(where)

    counts = db.execute(
        "SELECT COUNT(*) AS total_rows FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE " + clause,
        args,
    ).fetchone()["total_rows"]
    aggregate = db.execute(
        "SELECT COUNT(*) AS bills, "
        "COALESCE(SUM(CASE WHEN COALESCE(s.taxable_paise,0)=0 AND NOT EXISTS(" 
        "SELECT 1 FROM sale_lines l WHERE l.sale_id=s.id) THEN s.total_paise "
        "ELSE COALESCE(s.taxable_paise,0)+COALESCE(s.gst_paise,0) END),0) AS sales_value, "
        "COALESCE(SUM(s.deposit_received_paise-s.deposit_refunded_paise),0) AS deposits, "
        "COALESCE(SUM(MAX(s.total_paise-s.paid_paise,0)),0) AS udhaar "
        "FROM sales s LEFT JOIN customers c ON c.id=s.customer_id "
        "WHERE s.status='active' AND " + clause,
        args,
    ).fetchone()
    cylinder_total = db.execute(
        "SELECT COALESCE(SUM(l.qty_milli),0) FROM sale_lines l JOIN sales s ON s.id=l.sale_id "
        "LEFT JOIN customers c ON c.id=s.customer_id WHERE s.status='active' "
        "AND l.action IN ('refill','new_full') AND " + clause,
        args,
    ).fetchone()[0]
    legacy_cylinders = db.execute(
        "SELECT COALESCE(SUM(si.qty_out),0) FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        "LEFT JOIN customers c ON c.id=s.customer_id WHERE s.status='active' "
        "AND NOT EXISTS(SELECT 1 FROM sale_lines l WHERE l.sale_id=s.id) AND " + clause,
        args,
    ).fetchone()[0]

    rows = db.execute(
        "SELECT s.*,c.name AS customer_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE "
        + clause + " ORDER BY s.sale_date DESC,s.id DESC LIMIT 500", args
    ).fetchall()
    result = []
    for row in rows:
        products = db.execute(
            "SELECT description,qty_milli,action FROM sale_lines WHERE sale_id=? AND kind='product' "
            "ORDER BY line_no LIMIT 5", (row["id"],)
        ).fetchall()
        detail_lines = db.execute(
            "SELECT kind,action,qty_milli,amount_paise,detail,description FROM sale_lines "
            "WHERE sale_id=? ORDER BY line_no", (row["id"],)
        ).fetchall()
        if products:
            label = " · ".join(
                f"{Decimal(x['qty_milli'])/Decimal(1000):g} x {x['description']}" for x in products
            )
            count = sum(int(x["qty_milli"] or 0) for x in products if x["action"] in ("refill", "new_full")) // 1000
        else:
            good = next((x for x in detail_lines if x["kind"] == "empty_in"), None)
            damaged = next((x for x in detail_lines if x["kind"] == "deposit_forfeit"), None)
            refund = sum(-int(x["amount_paise"] or 0) for x in detail_lines if x["kind"] == "deposit_refund")
            retained = sum(int(x["retained_paise"] or 0) for x in detail_lines)
            new_empty = next((x for x in detail_lines if x["kind"] == "deposit" and x["action"] == "new_empty"), None)
            if damaged:
                label = "Damaged cylinder returned · deposit retained Rs " + _line_label_amount(damaged["detail"])
            elif good and refund and retained:
                label = "Empty returned · refunded Rs " + to_rupees(refund) + " · retained Rs " + to_rupees(retained)
            elif good and refund:
                label = "Empty returned · deposit refunded Rs " + to_rupees(refund)
            elif good and retained:
                label = "Empty returned · deposit retained Rs " + to_rupees(retained)
            elif good:
                label = "Empty returned"
            elif new_empty:
                label = "Empty cylinder given · deposit Rs " + to_rupees(new_empty["amount_paise"])
            else:
                legacy = db.execute(
                    "SELECT ct.name,si.qty_out FROM sale_items si JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
                    "WHERE si.sale_id=? AND si.qty_out>0 ORDER BY si.id LIMIT 5", (row["id"],)
                ).fetchall()
                label = " · ".join(f"{x['qty_out']} x {x['name']}" for x in legacy) or "Legacy sale"
            count = db.execute("SELECT COALESCE(SUM(qty_out),0) FROM sale_items WHERE sale_id=?", (row["id"],)).fetchone()[0]
        sales_value = (row["total_paise"] if not detail_lines and row["taxable_paise"] == 0 else
                       row["taxable_paise"] + row["gst_paise"])
        result.append({
            "id": row["id"], "number": row["number"], "date": row["sale_date"],
            "time": _time_label(row["created_at"]),
            "customer": row["customer_name"] or "Walk-in customer", "customer_id": row["customer_id"],
            "label": label, "cylinders": count, "total": to_rupees(row["total_paise"]),
            "sales_value": to_rupees(sales_value),
            "deposit_received": to_rupees(row["deposit_received_paise"]),
            "deposit_refunded": to_rupees(row["deposit_refunded_paise"]),
            "due": to_rupees(max(0, row["total_paise"] - row["paid_paise"])), "status": _sale_status(row),
        })
    return jsonify({
        "summary": {"total": to_rupees(aggregate["sales_value"]), "bills": aggregate["bills"],
                    "cylinders": cylinder_total // 1000 + legacy_cylinders,
                    "deposits_held_change": to_rupees(aggregate["deposits"]),
                    "udhaar": to_rupees(aggregate["udhaar"])},
        "sales": result, "truncated": counts > len(rows),
    })


@api_bp.get("/sales/<int:sid>")
def sale_get(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)
    return jsonify(_sale_payload(db, row))

@api_bp.get("/sales/<int:sid>/pdf")
def sale_pdf(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)

    try:
        from invoice_pdf import build_invoice_pdf
    except ImportError as exc:
        raise ApiError("PDF support is not installed. Run pip install -r requirements.txt.", 503) from exc

    pdf_data = build_invoice_pdf(_sale_payload(db, row))
    safe_number = "".join(ch for ch in row["number"] if ch.isalnum() or ch in "-_") or str(sid)
    return send_file(
        BytesIO(pdf_data), mimetype="application/pdf", as_attachment=True,
        download_name=f"Invoice-{safe_number}.pdf", max_age=0,
    )

@api_bp.post("/sales")
def sale_create():
    data = body()
    db = get_db()
    business = business_dict(db)
    missing = missing_business(business)
    if missing:
        raise ApiError("Complete Invoice settings first: " + ", ".join(missing) + ".", 422)

    customer = None
    if data.get("customer_id") not in (None, ""):
        current = customer_row(int_field(data["customer_id"], "Customer", minimum=1))
        customer = {
            "id": current["id"], "name": current["name"], "phone": current["phone"],
            "address": current["address"], "billing_address": current["billing_address"] or current["address"],
            "gstin": current["gstin"], "state_code": current["state_code"], "type": current["type"],
        }
    place_state = (data.get("place_state_code") or (customer and customer["state_code"]) or
                   (customer and customer["gstin"] and customer["gstin"][:2]) or business["state_code"])
    if place_state not in business_state_codes():
        raise ApiError("Choose a valid place-of-supply state code.", field="place_state_code")
    interstate = place_state != business["state_code"]
    day = day_field(data)
    note = text(data, "note", "Note", max_len=500)
    received_in = data.get("received_in", "cash")
    if received_in not in RECEIVED_IN:
        raise ApiError("Choose cash or bank / UPI.", field="received_in")
    # Reverse charge is unsupported; ignore any stale browser value.
    mode = data.get("payment", "paid")
    if mode not in ("paid", "partial", "credit"):
        raise ApiError("Choose a payment status.", field="payment")
    raw_lines, raw_items = data.get("lines") or [], data.get("items") or []
    if not isinstance(raw_lines, list) or not isinstance(raw_items, list):
        raise ApiError("Invoice items are invalid.")

    with transaction(db):
        lines, actions = [], []
        deposit_received = deposit_refunded = 0
        taxable_gross = 0
        seen_cylinders = set()
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise ApiError("Invalid cylinder row.")
            tid = int_field(raw.get("cylinder_type_id"), "Cylinder", minimum=1)
            if tid in seen_cylinders:
                raise ApiError("A cylinder size can appear only once on an invoice.", 409)
            seen_cylinders.add(tid)
            c = db.execute("SELECT * FROM cylinder_types WHERE id=? AND active=1", (tid,)).fetchone()
            if not c:
                raise ApiError("Cylinder type not found.", 404)
            qty = {k: _qty(raw.get(k), k.replace("_", " ").title()) for k in
                   ("refill", "new_full", "new_empty", "empty_in", "damaged_in")}
            if not any(qty.values()):
                continue
            if qty["refill"] + qty["new_full"] > c["full_qty"]:
                raise ApiError(f"{c['name']}: only {c['full_qty']} full cylinder(s) are available.", 409)
            if qty["new_empty"] > c["empty_qty"]:
                raise ApiError(f"{c['name']}: only {c['empty_qty']} empty cylinder(s) are available.", 409)
            if (qty["new_full"] or qty["new_empty"] or qty["empty_in"] or qty["damaged_in"]) and not customer:
                raise ApiError("Select a customer for cylinder deposits and cylinder returns.", field="customer_id")

            held_qty = _held_cylinders(db, customer["id"], tid) if customer else 0
            returned_qty = qty["empty_in"] + qty["damaged_in"]
            # A tracked cylinder used for refill cannot also be counted as a
            # separate good/damaged return on the same row. Refill remains
            # allowed when the customer has no recorded holdings at all.
            refill_reserved = min(qty["refill"], max(0, held_qty))
            if returned_qty + refill_reserved > held_qty:
                raise ApiError(
                    f"{c['name']}: a cylinder already used for refill cannot also be returned on this invoice.", 409)
            if returned_qty > held_qty:
                raise ApiError(
                    f"{c['name']}: the customer holds only {held_qty} cylinder(s). "
                    "A good or damaged return needs a cylinder already held by this customer.", 409)

            stock_sid = None
            if qty["refill"] or qty["new_full"] or qty["new_empty"]:
                stock_sid = _resolve_supplier(db, raw, "supplier_id", tid, c["name"],
                                              customer["id"] if customer else None, False)
            if qty["new_empty"] and stock_sid is not None:
                link = db.execute(
                    "SELECT empty_qty FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?",
                    (stock_sid, tid),
                ).fetchone()
                if not link or int(link["empty_qty"] or 0) < qty["new_empty"]:
                    available = int(link["empty_qty"] or 0) if link else 0
                    raise ApiError(
                        f"{c['name']}: supplier has only {available} empty cylinder(s) available.",
                        409, "supplier_id")
            return_sid, good_sources, damaged_sources = None, [], []
            if returned_qty:
                return_raw = dict(raw)
                if return_raw.get("return_supplier_id") in (None, "", "0") and qty["damaged_in"]:
                    if data.get("damaged_supplier_id") not in (None, "", "0"):
                        return_raw["return_supplier_id"] = data["damaged_supplier_id"]
                return_sid = _resolve_supplier(db, return_raw, "return_supplier_id", tid,
                                               c["name"], customer["id"], True)
                sources = _return_sources(db, customer["id"], tid, return_sid, returned_qty, c["name"])
                good_sources, damaged_sources = _split_return_sources(sources, qty["empty_in"], qty["damaged_in"])

            rate = money_field({"rate": raw.get("rate", "0")}, "rate", f"{c['name']} selling price")
            security = money_field({"security": raw.get("security", to_rupees(c["security_paise"]))},
                                   "security", f"{c['name']} security deposit")
            action_entry = {"tid": tid, "qty": qty, "security": security,
                            "stock_supplier_id": stock_sid, "return_supplier_id": return_sid,
                            "good_sources": good_sources, "damaged_sources": damaged_sources}
            actions.append(action_entry)

            hsn = c["hsn"]
            rate_bp = c["gst_rate_bp"]
            if qty["refill"] or qty["new_full"]:
                if not hsn:
                    raise ApiError(f"Set an HSN/SAC code for {c['name']} in Stock & Price before invoicing.", 422, "hsn")
                if rate_bp is None:
                    raise ApiError(f"Set the GST rate for {c['name']} in Stock & Price before invoicing.", 422, "gst_rate")
                if rate_bp > 0 and not business.get("gstin"):
                    raise ApiError("The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.", 422, "gstin")

            for action in ("refill", "new_full"):
                n = qty[action]
                if not n:
                    continue
                gross = n * rate
                lines.append({"kind": "product", "action": action, "cylinder_type_id": tid,
                              "supplier_id": stock_sid,
                              "description": f"{c['name']} LPG refill" if action == "refill" else f"{c['name']} LPG",
                              "hsn": hsn, "unit": "NOS", "qty_milli": n * 1000,
                              "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": rate_bp,
                              "detail": "Refill" if action == "refill" else "New full cylinder gas component"})
                taxable_gross += gross

            for action in ("new_full", "new_empty"):
                n = qty[action]
                if not n:
                    continue
                amount = n * security
                deposit_received += amount
                lines.append({"kind": "deposit", "action": action if action == "new_empty" else None,
                              "cylinder_type_id": tid, "supplier_id": stock_sid,
                              "description": f"Refundable cylinder security deposit — {c['name']}",
                              "unit": "NOS", "qty_milli": n * 1000, "rate_paise": security,
                              "gross_paise": amount, "amount_paise": amount, "detail": "Refundable security deposit"})

            if qty["empty_in"]:
                lines.append({"kind": "empty_in", "action": "empty_in", "cylinder_type_id": tid,
                              "supplier_id": return_sid,
                              "description": f"Empty cylinder received — {c['name']}", "unit": "NOS",
                              "qty_milli": qty["empty_in"] * 1000,
                              "detail": "Customer returned good empty cylinder"})
                if raw.get("deposit_back", True) is not False:
                    good_left, refund_total, refund_events, remainder_events = qty["empty_in"], 0, [], []
                    explicit_each = raw.get("deposit_each") not in (None, "")
                    explicit_refund_each = (money_field({"deposit_each": raw.get("deposit_each")},
                                                        "deposit_each", "Refund per cylinder", allow_zero=True)
                                            if explicit_each else None)
                    for source in good_sources:
                        if good_left <= 0:
                            break
                        take = min(good_left, source["qty"])
                        source_qty, source_amount = source["available_qty"], source["available_paise"]
                        source_cap = source_amount if take == source_qty else _round_ratio(source_amount * take, source_qty)
                        refund = explicit_refund_each * take if explicit_each else source_cap
                        if refund > source_cap:
                            raise ApiError(f"{c['name']}: refund exceeds the recorded deposit for the returned cylinder(s).", 409)
                        refund_total += refund
                        refund_events.append((source["supplier_id"], take, refund))
                        if source_cap > refund:
                            remainder_events.append((source["supplier_id"], 0, source_cap - refund))
                        good_left -= take
                    if good_left:
                        raise ApiError(f"{c['name']}: not enough refundable customer deposits for this return.", 409)
                    deposit_refunded += refund_total
                    refund_each = _round_ratio(refund_total, qty["empty_in"]) if qty["empty_in"] else 0
                    lines.append({"kind": "deposit_refund", "cylinder_type_id": tid, "supplier_id": return_sid,
                                  "description": f"Refund of cylinder security deposit — {c['name']}",
                                  "unit": "NOS", "qty_milli": qty["empty_in"] * 1000,
                                  "rate_paise": refund_each, "gross_paise": -refund_total,
                                  "amount_paise": -refund_total, "retained_paise": sum(x[2] for x in remainder_events),
                                  "detail": "Refundable deposit returned"})
                    action_entry["refund_events"] = refund_events
                    action_entry["forfeiture_events"] = action_entry.get("forfeiture_events", []) + remainder_events
                else:
                    good_left, forfeited_events = qty["empty_in"], []
                    for source in good_sources:
                        if good_left <= 0:
                            break
                        take = min(good_left, source["qty"])
                        source_qty, source_amount = source["available_qty"], source["available_paise"]
                        forfeited = source_amount if take == source_qty else _round_ratio(source_amount * take, source_qty)
                        forfeited_events.append((source["supplier_id"], take, forfeited))
                        good_left -= take
                    if good_left:
                        raise ApiError(f"{c['name']}: not enough customer-held deposits to close the returned cylinders.", 409)
                    action_entry["forfeiture_events"] = action_entry.get("forfeiture_events", []) + forfeited_events
                    retained_total = sum(x[2] for x in forfeited_events)
                    lines.append({"kind": "deposit_retained", "cylinder_type_id": tid, "supplier_id": return_sid,
                                  "description": f"Customer deposit retained — returned {c['name']}",
                                  "unit": "NOS", "qty_milli": qty["empty_in"] * 1000,
                                  "gross_paise": 0, "amount_paise": 0, "retained_paise": retained_total,
                                  "detail": f"Deposit retained: {to_rupees(retained_total)}"})

            if qty["damaged_in"]:
                damaged_left, forfeited_total, forfeiture_events = qty["damaged_in"], 0, []
                for source in damaged_sources:
                    if damaged_left <= 0:
                        break
                    take = min(damaged_left, source["qty"])
                    source_qty, source_amount = source["available_qty"], source["available_paise"]
                    forfeited = source_amount if take == source_qty else _round_ratio(source_amount * take, source_qty)
                    forfeited_total += forfeited
                    forfeiture_events.append((source["supplier_id"], take, forfeited))
                    damaged_left -= take
                if damaged_left:
                    raise ApiError(f"{c['name']}: not enough customer-held deposits to forfeit for this damaged return.", 409)
                lines.append({"kind": "deposit_forfeit", "action": "damaged_in", "cylinder_type_id": tid,
                              "supplier_id": return_sid,
                              "description": f"Security deposit retained — damaged {c['name']}", "unit": "NOS",
                              "qty_milli": qty["damaged_in"] * 1000, "rate_paise": 0,
                              "gross_paise": 0, "amount_paise": 0, "retained_paise": forfeited_total,
                              "detail": f"Security deposit retained: {to_rupees(forfeited_total)}"})
                action_entry["forfeiture_events"] = action_entry.get("forfeiture_events", []) + forfeiture_events

        seen_items = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ApiError("Invalid catalogue item row.")
            iid = int_field(raw.get("item_id"), "Item", minimum=1)
            if iid in seen_items:
                raise ApiError("A catalogue item can appear only once on an invoice.", 409)
            seen_items.add(iid)
            item = db.execute("SELECT * FROM catalog_items WHERE id=? AND active=1", (iid,)).fetchone()
            if not item:
                raise ApiError("Catalogue item not found.", 404)
            qty_milli = quantity_milli_field(raw.get("qty"), item["unit"], allow_zero=False)
            if qty_milli > item["stock_qty_milli"]:
                raise ApiError(f"{item['name']}: insufficient stock.", 409)
            rate = money_field({"rate": raw.get("rate", "0")}, "rate", f"{item['name']} selling price")
            if not item["hsn"]:
                raise ApiError(f"Set an HSN/SAC code for {item['name']} in Stock & Price before invoicing.", 422, "hsn")
            item_rate_bp = item["gst_rate_bp"]
            if item_rate_bp is None:
                raise ApiError(f"Set the GST rate for {item['name']} in Stock & Price before invoicing.", 422, "gst_rate")
            if item_rate_bp > 0 and not business.get("gstin"):
                raise ApiError("The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.", 422, "gstin")
            gross = _round_ratio(qty_milli * rate, 1000)
            taxable_gross += gross
            lines.append({"kind": "product", "action": "item", "item_id": iid, "description": item["name"],
                          "hsn": item["hsn"], "unit": item["unit"], "qty_milli": qty_milli,
                          "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": item_rate_bp,
                          "detail": item["unit"]})

        if not lines:
            raise ApiError("Add at least one product or cylinder return.")
        discount = money_field(data, "discount", "Discount")
        if discount > taxable_gross:
            raise ApiError("Discount cannot exceed the taxable product subtotal.", field="discount")
        product_rows = [line for line in lines if line["kind"] == "product"]
        shares = _allocate_discount(product_rows, discount, taxable_gross)
        tax_total = cgst_total = sgst_total = igst_total = taxable_total = 0
        for line, share in zip(product_rows, shares):
            taxable = line["gross_paise"] - share
            gst = _round_ratio(taxable * line["gst_rate_bp"], 10000)
            if interstate:
                igst, cgst, sgst = gst, 0, 0
            else:
                cgst = (gst + 1) // 2
                sgst = gst - cgst
                igst = 0
            line.update({"discount_paise": share, "taxable_paise": taxable, "cgst_paise": cgst,
                         "sgst_paise": sgst, "igst_paise": igst, "amount_paise": taxable + gst})
            taxable_total += taxable
            tax_total += gst
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst

        product_subtotal = taxable_gross
        total = taxable_total + tax_total + deposit_received - deposit_refunded
        if total < 0:
            paid = total
        elif mode == "paid":
            paid = total
        elif mode == "credit":
            if not customer:
                raise ApiError("Walk-in invoices must be paid immediately.", field="payment")
            paid = 0
        else:
            if not customer:
                raise ApiError("Walk-in invoices must be paid immediately.", field="payment")
            paid = money_field(data, "paid", "Amount paid", allow_zero=False)
            if not 0 < paid < total:
                raise ApiError("Amount paid must be greater than zero and less than the invoice total.", field="paid")

        prefix = business.get("invoice_prefix") or "S"
        number = next_number(db, "sale", prefix)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        business_snapshot = dict(business)
        business_snapshot.pop("state_name", None)
        sale_id = db.execute(
            "INSERT INTO sales(number,customer_id,sale_date,created_at,subtotal_paise,discount_paise,gst_percent,"
            "gst_paise,total_paise,paid_paise,received_in,status,note,cgst_paise,sgst_paise,igst_paise,"
            "taxable_paise,deposit_received_paise,deposit_refunded_paise,place_state_code,reverse_charge,"
            "business_snapshot_json,customer_snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, customer["id"] if customer else None, day, now, product_subtotal, discount,
             (tax_total * 100 / taxable_total) if taxable_total else 0, tax_total, total, paid,
             received_in, "active", note, cgst_total, sgst_total, igst_total, taxable_total,
             deposit_received, deposit_refunded, place_state, 0,
             json.dumps(business_snapshot, ensure_ascii=False), json.dumps(customer, ensure_ascii=False)),
        ).lastrowid

        for index, line in enumerate(lines, 1):
            _insert_line(db, sale_id, index, line)

        # Apply all physical, customer-ledger and deposit changes inside this invoice transaction.
        for action in actions:
            tid, q = action["tid"], action["qty"]
            c = db.execute("SELECT * FROM cylinder_types WHERE id=?", (tid,)).fetchone()
            stock_sid, return_sid = action["stock_supplier_id"], action["return_supplier_id"]
            full_delta = empty_delta = damaged_delta = 0
            take_full = q["refill"] + q["new_full"]
            if take_full:
                _take_full(db, tid, stock_sid, take_full, "sale", sale_id)
                full_delta -= take_full
            if q["refill"]:
                empty_delta += q["refill"]
                _give_empty(db, tid, stock_sid, q["refill"])
            if q["new_empty"]:
                empty_delta -= q["new_empty"]
                _take_empty(db, tid, stock_sid, q["new_empty"])
            if q["empty_in"]:
                empty_delta += q["empty_in"]
                _give_empty(db, tid, return_sid, q["empty_in"])
                db.execute(
                    "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
                    "VALUES(?,?,?,'sale',?,?,?)",
                    (customer["id"], tid, -q["empty_in"], sale_id, day, "Good empties returned on invoice " + number),
                )
            if q["damaged_in"]:
                damaged_delta += q["damaged_in"]
                db.execute(
                    "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
                    "VALUES(?,?,?,'sale',?,?,?)",
                    (customer["id"], tid, -q["damaged_in"], sale_id, day, "Damaged cylinders returned on invoice " + number),
                )
                if return_sid is not None:
                    supplier_qty, supplier_amount = _supplier_deposit_balance(db, tid, return_sid)
                    if supplier_qty < q["damaged_in"]:
                        raise ApiError(
                            f"{c['name']}: only {supplier_qty} supplier security-deposit cylinder(s) remain for this supplier.",
                            409, "return_supplier_id")
                    supplier_forfeit = supplier_amount if q["damaged_in"] == supplier_qty else _round_ratio(
                        supplier_amount * q["damaged_in"], supplier_qty)
                    db.execute(
                        "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note,sale_id,status) "
                        "VALUES(?,?,'cancelled',?,?,?,?,'active')",
                        (tid, return_sid, q["damaged_in"], supplier_forfeit,
                         "Customer returned damaged cylinder on " + number, sale_id),
                    )
            if q["new_full"] or q["new_empty"]:
                issued = q["new_full"] + q["new_empty"]
                db.execute(
                    "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
                    "VALUES(?,?,?,'sale',?,?,?)",
                    (customer["id"], tid, issued, sale_id, day, "Cylinders issued on invoice " + number),
                )
                db.execute(
                    "INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,supplier_id,kind,qty,amount_paise,event_date,note) "
                    "VALUES(?,?,?,?,'received',?,?,?,?)",
                    (customer["id"], tid, sale_id, stock_sid, issued, issued * action["security"], day,
                     "Refundable cylinder deposit received"),
                )
            for source_sid, source_qty, refund in action.get("refund_events", []):
                db.execute(
                    "INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,supplier_id,kind,qty,amount_paise,event_date,note) "
                    "VALUES(?,?,?,?,'refunded',?,?,?,?)",
                    (customer["id"], tid, sale_id, source_sid, source_qty, refund, day,
                     "Refundable cylinder deposit returned"),
                )
            for source_sid, source_qty, forfeited in action.get("forfeiture_events", []):
                db.execute(
                    "INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,supplier_id,kind,qty,amount_paise,event_date,note) "
                    "VALUES(?,?,?,?,'forfeited',?,?,?,?)",
                    (customer["id"], tid, sale_id, source_sid, source_qty, forfeited, day,
                     "Customer cylinder deposit forfeited on return"),
                )
            held_delta = q["new_full"] + q["new_empty"] - q["empty_in"] - q["damaged_in"]
            db.execute(
                "UPDATE cylinder_types SET full_qty=full_qty+?,empty_qty=empty_qty+?,damaged_qty=damaged_qty+?,"
                "with_customers_qty=with_customers_qty+? WHERE id=?",
                (full_delta, empty_delta, damaged_delta, held_delta, tid),
            )
            if full_delta or empty_delta or damaged_delta:
                _movement(db, tid, "sale", sale_id, full=full_delta, empty=empty_delta,
                          damaged=damaged_delta, note="Invoice " + number)
            db.execute(
                "INSERT INTO sale_items(sale_id,cylinder_type_id,mode,qty_out,qty_empty_in,rate_paise,amount_paise) "
                "VALUES(?,?,?,?,?,?,?)",
                (sale_id, tid, "invoice", take_full, q["empty_in"] + q["damaged_in"], 0, 0),
            )

        for line in lines:
            if line.get("action") == "item":
                iid, q_milli = line["item_id"], line["qty_milli"]
                db.execute("UPDATE catalog_items SET stock_qty_milli=stock_qty_milli-? WHERE id=? AND stock_qty_milli>=?",
                           (q_milli, iid, q_milli))
                if db.execute("SELECT changes()").fetchone()[0] != 1:
                    raise ApiError("Catalogue stock changed while saving. Reload and try again.", 409)
                db.execute("INSERT INTO catalog_sale_movements(sale_id,item_id,quantity_delta_milli,kind,note) VALUES(?,?,?,'sale',?)",
                           (sale_id, iid, -q_milli, "Invoice " + number))

    return jsonify({"id": sale_id, "number": number}), 201


@api_bp.post("/sales/<int:sid>/cancel")
def sale_cancel(sid):
    data = body()
    reason = text(data, "reason", "Cancellation reason", max_len=200)
    db = get_db()
    with transaction(db):
        sale = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
        if not sale:
            raise ApiError("Invoice not found.", 404)
        if sale["status"] == "cancelled":
            raise ApiError("This invoice is already cancelled.", 409)
        dispatched = db.execute(
            "SELECT COUNT(*) FROM damaged_cylinder_dispatch_items di "
            "JOIN cylinder_deposits d ON d.id=di.damage_event_id WHERE d.sale_id=?", (sid,)
        ).fetchone()[0]
        if dispatched:
            raise ApiError("This invoice includes a damaged cylinder already dispatched to its supplier and cannot be cancelled.", 409)

        all_lines = db.execute("SELECT * FROM sale_lines WHERE sale_id=? ORDER BY line_no,id", (sid,)).fetchall()
        if not all_lines:
            legacy_items = db.execute("SELECT COUNT(*) FROM sale_items WHERE sale_id=?", (sid,)).fetchone()[0]
            if legacy_items:
                raise ApiError(
                    "This legacy invoice has no supplier-aware line snapshots, so its stock cannot be reversed safely. "
                    "It remains unchanged.", 409)
            raise ApiError("This legacy invoice has no reversible stock detail. It remains unchanged.", 409)
        lines = [line for line in all_lines if line["action"] is not None]
        deltas = {}
        for line in lines:
            action, tid = line["action"], line["cylinder_type_id"]
            if action == "item":
                continue
            qty = int(line["qty_milli"] or 0) // 1000
            d = deltas.setdefault(tid, {"full": 0, "empty": 0, "damaged": 0, "held": 0})
            if action == "refill": d["full"] += qty; d["empty"] -= qty
            elif action == "new_full": d["full"] += qty; d["held"] -= qty
            elif action == "new_empty": d["empty"] += qty; d["held"] -= qty
            elif action == "empty_in": d["empty"] -= qty; d["held"] += qty
            elif action == "damaged_in": d["damaged"] -= qty; d["held"] += qty

        for tid, delta in deltas.items():
            current = db.execute(
                "SELECT full_qty,empty_qty,damaged_qty,with_customers_qty FROM cylinder_types WHERE id=?", (tid,)
            ).fetchone()
            if not current:
                raise ApiError("A cylinder size from this invoice no longer exists.", 409)
            for key in ("full", "empty", "damaged"):
                if current[key + "_qty"] + delta[key] < 0:
                    raise ApiError(f"Cannot cancel this invoice: reversing it would make {key} stock negative.", 409)
            if current["with_customers_qty"] + delta["held"] < 0:
                raise ApiError("Cannot cancel this invoice: reversing it would make customer-held cylinder stock negative.", 409)
            if sale["customer_id"] and delta["held"]:
                held_now = _held_cylinders(db, sale["customer_id"], tid)
                if held_now + delta["held"] < 0:
                    raise ApiError("Cannot cancel this invoice: the customer has already returned one or more of these cylinders.", 409)

        supplier_empty_to_take = {}
        for line in lines:
            if line["action"] in ("refill", "empty_in") and line["supplier_id"] is not None:
                key = (line["cylinder_type_id"], line["supplier_id"])
                supplier_empty_to_take[key] = supplier_empty_to_take.get(key, 0) + int(line["qty_milli"] or 0) // 1000
            if line["supplier_id"] is not None and line["action"] in ("refill", "new_empty", "empty_in"):
                if not db.execute("SELECT 1 FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?",
                                  (line["cylinder_type_id"], line["supplier_id"])).fetchone():
                    raise ApiError("Cannot cancel this invoice: a supplier/cylinder link used by it has been removed.", 409)
        for (tid, supplier_id), qty in supplier_empty_to_take.items():
            link = db.execute("SELECT empty_qty FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?",
                              (tid, supplier_id)).fetchone()
            if not link or link["empty_qty"] < qty:
                raise ApiError("Cannot cancel this invoice: the supplier's empty-cylinder stock has changed or its link was removed.", 409)

        for line in lines:
            action, tid, sid_line = line["action"], line["cylinder_type_id"], line["supplier_id"]
            if action == "item":
                db.execute("UPDATE catalog_items SET stock_qty_milli=stock_qty_milli+? WHERE id=?",
                           (line["qty_milli"], line["item_id"]))
                db.execute("INSERT INTO catalog_sale_movements(sale_id,item_id,quantity_delta_milli,kind,note) VALUES(?,?,?,'sale_cancel',?)",
                           (sid, line["item_id"], line["qty_milli"], "Cancellation of " + sale["number"]))
                continue
            qty = int(line["qty_milli"] or 0) // 1000
            full_delta = empty_delta = damaged_delta = held_delta = 0
            if action == "refill":
                full_delta, empty_delta = qty, -qty
                _take_empty(db, tid, sid_line, qty)
            elif action == "new_full":
                full_delta, held_delta = qty, -qty
            elif action == "new_empty":
                empty_delta, held_delta = qty, -qty
                _give_empty(db, tid, sid_line, qty)
            elif action == "empty_in":
                empty_delta, held_delta = -qty, qty
                _take_empty(db, tid, sid_line, qty)
            elif action == "damaged_in":
                damaged_delta, held_delta = -qty, qty
            db.execute(
                "UPDATE cylinder_types SET full_qty=full_qty+?,empty_qty=empty_qty+?,damaged_qty=damaged_qty+?,"
                "with_customers_qty=with_customers_qty+? WHERE id=?",
                (full_delta, empty_delta, damaged_delta, held_delta, tid),
            )
            if held_delta and sale["customer_id"]:
                db.execute(
                    "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (sale["customer_id"], tid, held_delta, "sale_cancel", sid, sale["sale_date"],
                     "Cancellation of " + sale["number"]),
                )
            if full_delta or empty_delta or damaged_delta:
                _movement(db, tid, "sale_cancel", sid, full=full_delta, empty=empty_delta,
                          damaged=damaged_delta, note="Cancellation of " + sale["number"])

        lots.restore(db, "sale", sid)
        db.execute("UPDATE customer_deposit_events SET status='reversed' WHERE sale_id=?", (sid,))
        db.execute("UPDATE cylinder_deposits SET status='reversed' WHERE sale_id=?", (sid,))
        db.execute("UPDATE sales SET status='cancelled',cancelled_at=datetime('now','localtime'),cancel_reason=? WHERE id=?",
                   (reason, sid))
        refund = max(0, int(sale["paid_paise"] or 0))
    reversal = int(sale["paid_paise"] or 0)
    return jsonify({"ok": True, "refund": to_rupees(abs(reversal)),
                    "refund_direction": "collect" if reversal < 0 else "refund",
                    "received_in": sale["received_in"]})


def business_state_codes():
    from .util import STATES
    return set(STATES)