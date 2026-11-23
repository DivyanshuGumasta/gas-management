"""Persistent sales invoices. All money is stored in integer paise.

Product lines snapshot name, HSN, unit, selling rate and GST split. Refundable
customer cylinder deposits are recorded separately from taxable product lines
and separately from supplier deposits in cylinder_deposits.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json

from flask import jsonify, request

import lots
from db import get_db, next_number, transaction
from money import to_paise, to_rupees
from . import api_bp
from .business import business_dict, missing_business
from .customers import customer_row
from .stock import _movement
from .stock_suppliers import _optional_supplier, _security
from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, quantity_milli_field, text


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


def _deposit_balance(db, customer_id, cylinder_type_id):
    row = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'received' THEN qty ELSE -qty END),0) AS qty, "
        "COALESCE(SUM(CASE kind WHEN 'received' THEN amount_paise ELSE -amount_paise END),0) AS amount "
        "FROM customer_deposit_events WHERE customer_id=? AND cylinder_type_id=? AND status='active'",
        (customer_id, cylinder_type_id),
    ).fetchone()
    return max(0, row["qty"]), max(0, row["amount"])


def _held_cylinders(db, customer_id, cylinder_type_id):
    return db.execute(
        "SELECT COALESCE(SUM(delta),0) FROM cylinder_ledger WHERE customer_id=? AND cylinder_type_id=?",
        (customer_id, cylinder_type_id),
    ).fetchone()[0]


def _insert_line(db, sale_id, line_no, line):
    db.execute(
        "INSERT INTO sale_lines(sale_id,line_no,kind,action,cylinder_type_id,item_id,description,hsn,unit,"
        "qty_milli,rate_paise,gross_paise,discount_paise,taxable_paise,gst_rate_bp,cgst_paise,sgst_paise,"
        "igst_paise,amount_paise,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sale_id, line_no, line["kind"], line.get("action"), line.get("cylinder_type_id"), line.get("item_id"),
         line["description"], line.get("hsn"), line.get("unit", "NOS"), line.get("qty_milli", 0),
         line.get("rate_paise", 0), line.get("gross_paise", 0), line.get("discount_paise", 0),
         line.get("taxable_paise", 0), line.get("gst_rate_bp"), line.get("cgst_paise", 0),
         line.get("sgst_paise", 0), line.get("igst_paise", 0), line.get("amount_paise", 0), line.get("detail")),
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
        "taxable": to_rupees(row["taxable_paise"]), "gst_rate": (row["gst_rate_bp"] / 100 if row["gst_rate_bp"] is not None else None),
        "cgst": to_rupees(row["cgst_paise"]), "sgst": to_rupees(row["sgst_paise"]),
        "igst": to_rupees(row["igst_paise"]), "detail": row["detail"],
    }


def _sale_payload(db, sale):
    lines = db.execute("SELECT * FROM sale_lines WHERE sale_id=? ORDER BY line_no,id", (sale["id"],)).fetchall()
    try:
        business = json.loads(sale["business_snapshot_json"] or "{}")
        customer = json.loads(sale["customer_snapshot_json"] or "null")
    except (TypeError, ValueError):
        business, customer = {}, None
    created = sale["created_at"] or ""
    return {
        "id": sale["id"], "number": sale["number"], "date": sale["sale_date"],
        "time": created[11:16] if len(created) >= 16 else "",
        "status": _sale_status(sale), "customer": customer, "business": business,
        "place_state_code": sale["place_state_code"], "reverse_charge": bool(sale["reverse_charge"]),
        "note": sale["note"], "lines": [_line_payload(r) for r in lines],
        "subtotal": to_rupees(sale["subtotal_paise"]), "discount": to_rupees(sale["discount_paise"]),
        "taxable": to_rupees(sale["taxable_paise"]), "cgst": to_rupees(sale["cgst_paise"]),
        "sgst": to_rupees(sale["sgst_paise"]), "igst": to_rupees(sale["igst_paise"]),
        "gst": to_rupees(sale["gst_paise"]), "gst_percent": sale["gst_percent"],
        "deposit_received": to_rupees(sale["deposit_received_paise"]),
        "deposit_refunded": to_rupees(sale["deposit_refunded_paise"]),
        "total": to_rupees(sale["total_paise"]), "paid": to_rupees(sale["paid_paise"]),
        "due": to_rupees(max(0, sale["total_paise"] - sale["paid_paise"])),
        "received_in": sale["received_in"],
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
    rows = db.execute(
        "SELECT s.*,c.name AS customer_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE "
        + " AND ".join(where) + " ORDER BY s.sale_date DESC,s.id DESC LIMIT 500", args
    ).fetchall()
    live = [r for r in rows if r["status"] == "active"]
    summary = {
        "total": to_rupees(sum(r["total_paise"] for r in live)), "bills": len(live),
        "cylinders": db.execute(
            "SELECT COALESCE(SUM(qty_milli),0) FROM sale_lines l JOIN sales s ON s.id=l.sale_id "
            "WHERE s.status='active' AND l.action IN ('refill','new_full') "
            "AND s.id IN (" + ",".join("?" for _ in live) + ")", [r["id"] for r in live]
        ).fetchone()[0] // 1000 if live else 0,
        "udhaar": to_rupees(sum(max(0, r["total_paise"] - r["paid_paise"]) for r in live)),
    }
    result = []
    for r in rows:
        items = db.execute(
            "SELECT description,qty_milli,action FROM sale_lines WHERE sale_id=? "
            "AND action IN ('refill','new_full','item') ORDER BY line_no LIMIT 5", (r["id"],)
        ).fetchall()
        label = " · ".join(f"{Decimal(i['qty_milli'])/1000:g} x {i['description']}" for i in items)
        created = r["created_at"] or ""
        result.append({
            "id": r["id"], "number": r["number"], "date": r["sale_date"],
            "time": created[11:16] if len(created) >= 16 else "",
            "customer": r["customer_name"] or "Walk-in customer", "customer_id": r["customer_id"],
            "label": label or "Cylinder return / deposit settlement", "cylinders": 0,
            "total": to_rupees(r["total_paise"]),
            "due": to_rupees(max(0, r["total_paise"] - r["paid_paise"])), "status": _sale_status(r),
        })
    return jsonify({"summary": summary, "sales": result})


@api_bp.get("/sales/<int:sid>")
def sale_get(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)
    return jsonify(_sale_payload(db, row))


@api_bp.post("/sales")
def sale_create():
    data = body()
    db = get_db()
    business = business_dict(db)
    missing = missing_business(business)
    if missing:
        raise ApiError("Complete Invoice settings first: " + ", ".join(missing) + ".", 422)

    customer = None
    customer_row_data = None
    if data.get("customer_id") not in (None, ""):
        customer_row_data = customer_row(int_field(data["customer_id"], "Customer", minimum=1))
        customer = {
            "id": customer_row_data["id"], "name": customer_row_data["name"],
            "phone": customer_row_data["phone"], "address": customer_row_data["address"],
            "billing_address": customer_row_data["billing_address"] or customer_row_data["address"],
            "gstin": customer_row_data["gstin"], "state_code": customer_row_data["state_code"],
            "type": customer_row_data["type"],
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
    reverse_charge = data.get("reverse_charge", "no")
    if reverse_charge not in ("yes", "no"):
        raise ApiError("Choose whether reverse charge applies.", field="reverse_charge")
    if reverse_charge == "yes":
        raise ApiError(
            "Reverse-charge invoices are not enabled yet. Have the CA confirm the applicable treatment before issuing one.",
            422, "reverse_charge",
        )
    mode = data.get("payment", "paid")
    if mode not in ("paid", "partial", "credit"):
        raise ApiError("Choose a payment status.", field="payment")
    raw_lines = data.get("lines") or []
    raw_items = data.get("items") or []
    if not isinstance(raw_lines, list) or not isinstance(raw_items, list):
        raise ApiError("Invoice items are invalid.")

    with transaction(db):
        # Build all lines from authoritative product records, never from browser-supplied HSN/tax values.
        lines, actions, cylinder_totals = [], [], {}
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
            if customer and qty["empty_in"] + qty["damaged_in"] > _held_cylinders(db, customer["id"], tid):
                raise ApiError(f"{c['name']}: the customer does not hold that many cylinders.", 409)
            if customer and (qty["damaged_in"] or (qty["empty_in"] and raw.get("deposit_back"))):
                deposit_qty, _deposit_amount = _deposit_balance(db, customer["id"], tid)
                refund_qty = qty["empty_in"] if raw.get("deposit_back") else 0
                if refund_qty + qty["damaged_in"] > deposit_qty:
                    raise ApiError(f"{c['name']}: not enough outstanding customer security deposits for this return.", 409)

            rate = money_field({"rate": raw.get("rate", "0")}, "rate", f"{c['name']} selling price")
            security = money_field({"security": raw.get("security", to_rupees(c["security_paise"]))},
                                   "security", f"{c['name']} security deposit")
            action_entry = {"tid": tid, "qty": qty, "security": security}
            actions.append(action_entry)
            cylinder_totals[tid] = cylinder_totals.get(tid, {"refill": 0, "new_full": 0, "new_empty": 0, "empty_in": 0, "damaged_in": 0})
            for key, number in qty.items():
                cylinder_totals[tid][key] += number

            hsn = c["hsn"]
            rate_bp = c["gst_rate_bp"]
            if qty["refill"] or qty["new_full"]:
                if not hsn:
                    raise ApiError(f"Set an HSN/SAC code for {c['name']} in Stock & Price before invoicing.", 422, "hsn")
                if rate_bp is None:
                    raise ApiError(f"Set the GST rate for {c['name']} in Stock & Price before invoicing.", 422, "gst_rate")
                if rate_bp > 0 and not business.get("gstin"):
                    raise ApiError(
                        "The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.",
                        422, "gstin",
                    )
            for action in ("refill", "new_full"):
                n = qty[action]
                if not n:
                    continue
                gross = n * rate
                lines.append({"kind": "product", "action": action, "cylinder_type_id": tid,
                              "description": f"{c['name']} LPG refill" if action == "refill" else f"{c['name']} LPG",
                              "hsn": hsn, "unit": "NOS", "qty_milli": n * 1000,
                              "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": rate_bp,
                              "detail": "Refill" if action == "refill" else "New full cylinder gas component"})
                taxable_gross += gross
            for action in ("new_full", "new_empty"):
                n = qty[action]
                if not n:
                    continue
                if security and not customer:
                    raise ApiError("A customer must be selected for a refundable cylinder deposit.", 422)
                amount = n * security
                deposit_received += amount
                lines.append({"kind": "deposit", "action": action if action == "new_empty" else None,
                              "cylinder_type_id": tid, "description": f"Refundable cylinder security deposit — {c['name']}",
                              "unit": "NOS", "qty_milli": n * 1000, "rate_paise": security,
                              "gross_paise": amount, "amount_paise": amount, "detail": "Refundable security deposit"})

            if qty["empty_in"]:
                lines.append({"kind": "empty_in", "action": "empty_in", "cylinder_type_id": tid,
                              "description": f"Empty cylinder received — {c['name']}", "unit": "NOS",
                              "qty_milli": qty["empty_in"] * 1000, "detail": "Customer returned good empty cylinder"})
                if raw.get("deposit_back"):
                    available_qty, available_amount = _deposit_balance(db, customer["id"], tid)
                    n = qty["empty_in"]
                    if n > available_qty:
                        raise ApiError(f"{c['name']}: customer has only {available_qty} refundable deposit cylinder(s).", 409)
                    refund_each = money_field({"deposit_each": raw.get("deposit_each", "0")}, "deposit_each", "Refund per cylinder")
                    refund = refund_each * n
                    if refund > available_amount:
                        raise ApiError(f"{c['name']}: refund exceeds the customer's outstanding deposit.", 409)
                    deposit_refunded += refund
                    lines.append({"kind": "deposit_refund", "cylinder_type_id": tid,
                                  "description": f"Refund of cylinder security deposit — {c['name']}",
                                  "unit": "NOS", "qty_milli": n * 1000, "rate_paise": refund_each,
                                  "gross_paise": -refund, "amount_paise": -refund, "detail": "Refundable deposit returned"})

            if qty["damaged_in"]:
                n = qty["damaged_in"]
                available_qty, available_amount = _deposit_balance(db, customer["id"], tid)
                refund_qty = qty["empty_in"] if raw.get("deposit_back") else 0
                refund_amount_for_type = sum(-x["gross_paise"] for x in lines
                                             if x.get("kind") == "deposit_refund" and x.get("cylinder_type_id") == tid)
                remaining_deposit_qty = max(0, available_qty - refund_qty)
                remaining_deposit_amount = max(0, available_amount - refund_amount_for_type)
                if n > remaining_deposit_qty:
                    raise ApiError(f"{c['name']}: customer has only {remaining_deposit_qty} refundable deposit cylinder(s) to forfeit.", 409)
                forfeited = _round_ratio(remaining_deposit_amount * n, remaining_deposit_qty) if remaining_deposit_qty else 0
                lines.append({"kind": "deposit_forfeit", "action": "damaged_in", "cylinder_type_id": tid,
                              "description": f"Customer deposit forfeited — damaged {c['name']}", "unit": "NOS",
                              "qty_milli": n * 1000, "rate_paise": 0, "gross_paise": 0,
                              "amount_paise": 0, "forfeited_paise": forfeited,
                              "detail": f"Deposit retained: {to_rupees(forfeited)}"})

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
            if item["gst_rate_bp"] is None:
                raise ApiError(f"Set the GST rate for {item['name']} in Stock & Price before invoicing.", 422, "gst_rate")
            if item["gst_rate_bp"] > 0 and not business.get("gstin"):
                raise ApiError(
                    "The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.",
                    422, "gstin",
                )
            gross = _round_ratio(qty_milli * rate, 1000)
            taxable_gross += gross
            lines.append({"kind": "product", "action": "item", "item_id": iid, "description": item["name"],
                          "hsn": item["hsn"], "unit": item["unit"], "qty_milli": qty_milli,
                          "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": item["gst_rate_bp"],
                          "detail": item["unit"]})

        if not lines:
            raise ApiError("Add at least one product or cylinder return.")
        discount = money_field(data, "discount", "Discount")
        if discount > taxable_gross:
            raise ApiError("Discount cannot exceed the taxable product subtotal.", field="discount")

        # Allocate bill discount proportionally to taxable product lines; last line absorbs rounding remainder.
        left = discount
        tax_total = cgst_total = sgst_total = igst_total = taxable_total = 0
        product_rows = [line for line in lines if line["kind"] == "product"]
        for index, line in enumerate(product_rows):
            share = left if index == len(product_rows) - 1 else (discount * line["gross_paise"] // taxable_gross if taxable_gross else 0)
            left -= share
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
            cgst_total += cgst; sgst_total += sgst; igst_total += igst

        product_subtotal = taxable_gross
        total = taxable_total + tax_total + deposit_received - deposit_refunded
        if total < 0:
            mode = "paid"
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
        customer_snapshot = customer
        sale_id = db.execute(
            "INSERT INTO sales(number,customer_id,sale_date,created_at,subtotal_paise,discount_paise,gst_percent,"
            "gst_paise,total_paise,paid_paise,received_in,status,note,cgst_paise,sgst_paise,igst_paise,"
            "taxable_paise,deposit_received_paise,deposit_refunded_paise,place_state_code,reverse_charge,"
            "business_snapshot_json,customer_snapshot_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, customer["id"] if customer else None, day, now, product_subtotal, discount,
             (tax_total * 100 / taxable_total) if taxable_total else 0, tax_total, total, paid,
             received_in, "active", note, cgst_total, sgst_total, igst_total, taxable_total,
             deposit_received, deposit_refunded, place_state, int(reverse_charge == "yes"),
             json.dumps(business_snapshot, ensure_ascii=False), json.dumps(customer_snapshot, ensure_ascii=False)),
        ).lastrowid

        # Create printed line snapshots.
        for index, line in enumerate(lines, 1):
            _insert_line(db, sale_id, index, line)

        # Apply stock, customer cylinder ledger, deposit ledger and supplier-side damaged deposits.
        for action in actions:
            tid, q = action["tid"], action["qty"]
            c = db.execute("SELECT * FROM cylinder_types WHERE id=?", (tid,)).fetchone()
            full_delta = empty_delta = damaged_delta = 0
            take_full = q["refill"] + q["new_full"]
            if take_full:
                lots.consume_fifo(db, tid, take_full, "sale", sale_id)
                full_delta -= take_full
            if q["refill"]:
                empty_delta += q["refill"]
            if q["new_full"] or q["new_empty"]:
                held_add = q["new_full"] + q["new_empty"]
                db.execute("INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) VALUES(?,?,?,?,?,?,?)",
                           (customer["id"], tid, held_add, "sale", sale_id, day, "Cylinders issued on invoice " + number))
            if q["new_empty"]:
                empty_delta -= q["new_empty"]
            if q["empty_in"]:
                empty_delta += q["empty_in"]
                db.execute("INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) VALUES(?,?,?,?,?,?,?)",
                           (customer["id"], tid, -q["empty_in"], "sale", sale_id, day, "Good empties returned on invoice " + number))
            if q["damaged_in"]:
                damaged_delta += q["damaged_in"]
                db.execute("INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) VALUES(?,?,?,?,?,?,?)",
                           (customer["id"], tid, -q["damaged_in"], "sale", sale_id, day, "Damaged cylinders returned on invoice " + number))
                # Customer's deposit is forfeited; this never touches supplier deposits.
                n = q["damaged_in"]
                forfeiture_line = next(x for x in lines if x.get("kind") == "deposit_forfeit" and
                                       x.get("cylinder_type_id") == tid)
                forfeited = forfeiture_line.get("forfeited_paise", 0)
                db.execute("INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,kind,qty,amount_paise,event_date,note) VALUES(?,?,?,?,?,?,?,?)",
                           (customer["id"], tid, sale_id, "forfeited", n, forfeited, day, "Damaged cylinder deposit forfeited"))
                sid = _optional_supplier(db, {"supplier_id": data.get("damaged_supplier_id")} if data.get("damaged_supplier_id") not in (None, "") else {})
                active_suppliers = db.execute("SELECT COUNT(*) FROM suppliers WHERE active=1").fetchone()[0]
                if active_suppliers and sid is None:
                    raise ApiError("Choose which supplier's damaged cylinder deposit is being forfeited.", field="damaged_supplier_id")
                link = db.execute("SELECT * FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone() if sid else None
                if sid and not link:
                    raise ApiError(f"{c['name']} is not linked to the selected supplier in Stock & Price.", 409)
                if sid is not None:
                    supplier_deposit_qty = db.execute(
                        "SELECT COALESCE(SUM(CASE kind WHEN 'paid' THEN qty ELSE -qty END),0) "
                        "FROM cylinder_deposits WHERE cylinder_type_id=? AND supplier_id=? AND status='active'",
                        (tid, sid),
                    ).fetchone()[0]
                    if supplier_deposit_qty < n:
                        raise ApiError(
                            f"{c['name']}: only {max(0, supplier_deposit_qty)} supplier security-deposit cylinder(s) "
                            f"are still held for this supplier. Check the supplier deposit history before recording damage.",
                            409,
                        )
                    supplier_security = _security(link, c)
                    db.execute(
                        "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note,sale_id,status) "
                        "VALUES(?,?,'cancelled',?,?,?,?,'active')",
                        (tid, sid, n, supplier_security * n, "Customer returned damaged cylinder on " + number, sale_id),
                    )
            db.execute("UPDATE cylinder_types SET full_qty=full_qty+?,empty_qty=empty_qty+?,damaged_qty=damaged_qty+?,"
                       "with_customers_qty=with_customers_qty+? WHERE id=?",
                       (full_delta, empty_delta, damaged_delta, q["new_full"] + q["new_empty"] - q["empty_in"] - q["damaged_in"], tid))
            if full_delta or empty_delta or damaged_delta:
                _movement(db, tid, "sale", sale_id, full=full_delta, empty=empty_delta, damaged=damaged_delta,
                          note="Invoice " + number)

            # Customer deposit events are only liability changes; supplier deposits use another table.
            if q["new_full"] or q["new_empty"]:
                amount = (q["new_full"] + q["new_empty"]) * action["security"]
                # Record the cylinders even when the configured deposit is zero, so a later
                # good/damaged return can still reconcile the physical cylinder count.
                db.execute("INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,kind,qty,amount_paise,event_date,note) VALUES(?,?,?,?,?,?,?,?)",
                           (customer["id"], tid, sale_id, "received", q["new_full"] + q["new_empty"], amount, day, "Refundable cylinder deposit received"))
            if q["empty_in"] and any(x.get("kind") == "deposit_refund" and x.get("cylinder_type_id") == tid for x in lines):
                n = q["empty_in"]
                refund = sum(-x["gross_paise"] for x in lines if x.get("kind") == "deposit_refund" and x.get("cylinder_type_id") == tid)
                db.execute("INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,kind,qty,amount_paise,event_date,note) VALUES(?,?,?,?,?,?,?,?)",
                           (customer["id"], tid, sale_id, "refunded", n, refund, day, "Refundable cylinder deposit returned"))

            # Keep the legacy item table populated for existing customer/dashboard summaries.
            db.execute("INSERT INTO sale_items(sale_id,cylinder_type_id,mode,qty_out,qty_empty_in,rate_paise,amount_paise) VALUES(?,?,?,?,?,?,?)",
                       (sale_id, tid, "invoice", take_full, q["empty_in"] + q["damaged_in"], 0, 0))

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
    db = get_db()
    with transaction(db):
        sale = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
        if not sale:
            raise ApiError("Invoice not found.", 404)
        if sale["status"] == "cancelled":
            raise ApiError("This invoice is already cancelled.", 409)
        if sale["paid_paise"] != 0:
            raise ApiError(
                "This invoice has a payment or payout recorded. Paid invoices cannot be cancelled until a proper refund/credit-note workflow is available.",
                409,
            )
        dispatched = db.execute(
            "SELECT COUNT(*) FROM damaged_cylinder_dispatch_items di JOIN cylinder_deposits d ON d.id=di.damage_event_id "
            "WHERE d.sale_id=?", (sid,)
        ).fetchone()[0]
        if dispatched:
            raise ApiError("This invoice includes a damaged cylinder already dispatched to its supplier and cannot be cancelled.", 409)
        for line in db.execute("SELECT * FROM sale_lines WHERE sale_id=? AND action IS NOT NULL", (sid,)).fetchall():
            action, tid = line["action"], line["cylinder_type_id"]
            if action == "item":
                db.execute("UPDATE catalog_items SET stock_qty_milli=stock_qty_milli+? WHERE id=?", (line["qty_milli"], line["item_id"]))
                db.execute("INSERT INTO catalog_sale_movements(sale_id,item_id,quantity_delta_milli,kind,note) VALUES(?,?,?,'sale_cancel',?)",
                           (sid, line["item_id"], line["qty_milli"], "Cancellation of " + sale["number"]))
                continue
            qty = line["qty_milli"] // 1000
            full_delta = empty_delta = damaged_delta = held_delta = 0
            if action == "refill":
                full_delta, empty_delta = qty, -qty
            elif action == "new_full":
                full_delta, held_delta = qty, -qty
            elif action == "new_empty":
                empty_delta, held_delta = qty, -qty
            elif action == "empty_in":
                empty_delta, held_delta = -qty, qty
            elif action == "damaged_in":
                damaged_delta, held_delta = -qty, qty
            db.execute("UPDATE cylinder_types SET full_qty=full_qty+?,empty_qty=empty_qty+?,damaged_qty=damaged_qty+?,"
                       "with_customers_qty=with_customers_qty+? WHERE id=?",
                       (full_delta, empty_delta, damaged_delta, held_delta, tid))
            if held_delta and sale["customer_id"]:
                db.execute("INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) VALUES(?,?,?,?,?,?,?)",
                           (sale["customer_id"], tid, held_delta, "sale_cancel", sid, sale["sale_date"], "Cancellation of " + sale["number"]))
            if full_delta or empty_delta or damaged_delta:
                _movement(db, tid, "sale_cancel", sid, full=full_delta, empty=empty_delta,
                          damaged=damaged_delta, note="Cancellation of " + sale["number"])
        lots.restore(db, "sale", sid)
        db.execute("UPDATE customer_deposit_events SET status='reversed' WHERE sale_id=?", (sid,))
        db.execute("UPDATE cylinder_deposits SET status='reversed' WHERE sale_id=?", (sid,))
        db.execute("UPDATE sales SET status='cancelled',cancelled_at=datetime('now','localtime') WHERE id=?", (sid,))
    return jsonify({"ok": True})


def business_state_codes():
    from .util import STATES
    return set(STATES)