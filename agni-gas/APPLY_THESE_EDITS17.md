# APPLY_THESE_EDITS17 — v0.6: HSN/GST setup + permanent customer invoices

Paths are relative to `agni-gas/`. **Base:** GitHub `main` commit `f9f111f` (the v0.5.0 frontend-only Sales iteration). This patch keeps the v0.5 two-tab Sales layout and turns its temporary in-memory API into a persistent invoice workflow.

**A** = create/replace whole files. **B** = small edits. **C** = delete one file. Apply the sections in order. Back up `data/agni.db` before starting. Do not apply the earlier generic `APPLY_THESE_EDITS17.md`; this is the concrete replacement.

## What changes

* HSN/SAC and GST rate become editable fields on cylinder and catalogue-item records in Stock & Price. They appear in muted text beside product names. No HSN or rate is guessed or pre-filled.
* Saving a bill creates a permanent invoice number and database rows. Every invoice line snapshots description, HSN, unit, rate, discount allocation and tax split. Later product/customer edits do not rewrite old invoices.
* GST is calculated per taxable product line. CGST/SGST or IGST is selected using the place-of-supply state code. A product with missing HSN or GST rate cannot be included in a finalized invoice.
* Refundable customer security deposits are shown separately from taxable products. Customer deposits have their own ledger, independent from `cylinder_deposits` (agency ↔ supplier).
* Good empty returns can refund a customer's deposit. A damaged customer return forfeits the customer's deposit, moves the cylinder into damaged stock, and records the supplier-side deposit forfeiture against the selected supplier (defaulting to the sole active supplier). The existing damaged-cylinder dispatch workflow still only records physical dispatch; it does not refund any deposit.
* A new Invoice settings page stores agency details. With a GSTIN, the printout says TAX INVOICE; without one, it says INVOICE (and the backend blocks non-zero GST). The page does not invent agency details.
* The invoice printout uses the existing Agni Gas styling and browser print / Save as PDF.

## Important accounting choices

1. Supplier deposits remain in `cylinder_deposits`; customer deposits go to the new `customer_deposit_events` table. Never combine them.
2. Deposits are not added to taxable product values or GST calculations. They are included separately in the amount payable/refundable.
3. HSN and GST rate are independent. The agency/CA must enter and verify the correct values in Stock & Price.
4. A product HSN may be left blank during setup, but a taxable product line cannot be finalized until its HSN and GST rate are configured.
5. Tax rates are configuration values. No LPG HSN or GST rate is hardcoded.
6. Reverse-charge invoices are intentionally blocked for now. The Yes/No field is present, but the backend will not finalize a Yes invoice until the agency's CA confirms and the correct RCM tax/payment treatment is implemented.
7. Invoice cancellation is only allowed when no payment or payout was recorded. A paid invoice needs a proper refund/credit-note workflow; this patch refuses to silently reverse a paid bill without recording the money movement.
8. This patch does not push anything to GitHub.

---

# A. CREATE / REPLACE WHOLE FILES

## A1. Create `api/business.py`
Paste the complete file:

```python
"""Agency invoice details stored in the existing settings table."""
from flask import jsonify

from db import get_db, transaction
from . import api_bp
from .util import STATES, ApiError, body, gstin_field, state_code_field, text

FIELDS = (
    "name", "address", "gstin", "state_code", "phone", "email",
    "bank_name", "bank_account", "bank_ifsc", "terms", "invoice_prefix",
)
PREFIX = "business."


def business_dict(db):
    values = {
        r["key"][len(PREFIX):]: r["value"]
        for r in db.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'business.%'"
        )
    }
    result = {name: values.get(name) or None for name in FIELDS}
    result["invoice_prefix"] = result["invoice_prefix"] or "S"
    result["state_name"] = STATES.get(result["state_code"])
    return result


def missing_business(values):
    required = (("name", "Agency name"), ("address", "Agency address"),
                ("state_code", "Agency state"))
    return [label for key, label in required if not values.get(key)]


@api_bp.get("/business")
def business_get():
    return jsonify(business_dict(get_db()))


@api_bp.put("/business")
def business_save():
    data = body()
    values = {
        "name": text(data, "name", "Agency name", required=True, max_len=120),
        "address": text(data, "address", "Agency address", required=True, max_len=300),
        "gstin": gstin_field(data, required=False),
        "state_code": state_code_field(data, required=True),
        "phone": text(data, "phone", "Phone", max_len=30),
        "email": text(data, "email", "Email", max_len=120),
        "bank_name": text(data, "bank_name", "Bank name", max_len=100),
        "bank_account": text(data, "bank_account", "Bank account", max_len=40),
        "bank_ifsc": text(data, "bank_ifsc", "IFSC", max_len=20),
        "terms": text(data, "terms", "Terms", max_len=500),
        "invoice_prefix": text(data, "invoice_prefix", "Invoice prefix", max_len=8) or "S",
    }
    if values["gstin"] and values["gstin"][:2] != values["state_code"]:
        raise ApiError("Agency state must match the first two digits of its GSTIN.", field="state_code")
    if not values["invoice_prefix"].isalnum():
        raise ApiError("Invoice prefix can contain letters and numbers only.", field="invoice_prefix")
    db = get_db()
    with transaction(db):
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (PREFIX + key, value),
            )
    return jsonify(business_dict(db))
```

## A2. Create `api/sales.py`
This replaces the mock route with the persistent backend. Paste the complete file:

```python
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
```

## A3. Create `templates/business.html`
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">
<div class="page-head">
  <div><h1 class="page-title">Invoice settings</h1><p class="st-sub">Business details printed on customer tax invoices</p></div>
  <a class="btn btn-white" href="/sales">Back to Sales</a>
</div>
<div class="card biz-card">
  <div id="biz-error" class="banner banner-error" hidden><span></span></div>
  <form id="biz-form" novalidate>
    <div class="biz-grid">
      <label class="field"><span>Agency / legal business name *</span><input class="input" name="name" maxlength="120" required></label>
      <label class="field"><span>GSTIN (if registered)</span><input class="input" name="gstin" maxlength="15" autocapitalize="characters"></label>
      <label class="field biz-wide"><span>Registered business address *</span><textarea class="textarea" name="address" maxlength="300" required></textarea></label>
      <label class="field"><span>State code *</span><input class="input" name="state_code" maxlength="2" inputmode="numeric" placeholder="e.g. 22" required><small class="hint">Must match the first two digits of the agency GSTIN.</small></label>
      <label class="field"><span>Invoice number prefix</span><input class="input" name="invoice_prefix" maxlength="8" value="S"></label>
      <label class="field"><span>Phone</span><input class="input" name="phone" maxlength="30"></label>
      <label class="field"><span>Email</span><input class="input" name="email" maxlength="120" type="email"></label>
      <label class="field"><span>Bank name</span><input class="input" name="bank_name" maxlength="100"></label>
      <label class="field"><span>Bank account</span><input class="input" name="bank_account" maxlength="40"></label>
      <label class="field"><span>Bank IFSC</span><input class="input" name="bank_ifsc" maxlength="20"></label>
      <label class="field biz-wide"><span>Terms / payment notes</span><textarea class="textarea" name="terms" maxlength="500"></textarea></label>
    </div>
    <p class="hint">These details are copied into each invoice when it is created. Editing them later does not change previous invoices.</p>
    <div class="form-actions"><button class="btn btn-dark" type="submit">Save invoice settings</button></div>
  </form>
</div>
{% endblock %}
{% block scripts %}<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script><script src="{{ url_for('static', filename='js/business.js') }}"></script>{% endblock %}
```

## A4. Create `static/js/business.js`
```javascript
(function () {
  const form = document.getElementById('biz-form');
  const error = document.getElementById('biz-error');
  const fields = ['name','gstin','address','state_code','phone','email','bank_name','bank_account','bank_ifsc','terms','invoice_prefix'];
  function show(message) { error.hidden = !message; error.querySelector('span').textContent = message || ''; }
  async function load() {
    try {
      const data = await Api.get('/api/business');
      fields.forEach((key) => { if (form.elements[key]) form.elements[key].value = data[key] || (key === 'invoice_prefix' ? 'S' : ''); });
    } catch (e) { show('Could not load invoice settings. ' + e.message); }
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); show('');
    const payload = {};
    fields.forEach((key) => { payload[key] = form.elements[key].value.trim(); });
    const button = form.querySelector('[type="submit"]'); button.disabled = true;
    try { await Api.put('/api/business', payload); Cust.toast('Invoice settings saved'); }
    catch (e) { show(e.message || 'Could not save invoice settings.'); }
    finally { button.disabled = false; }
  });
  load();
})();
```

## A5. Replace `static/js/sales_new.js`
Delete everything in the existing file and paste:

```javascript
// New sale / tax invoice. GST and HSN are read from Stock & Price, never typed per bill.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const state = { customer: null, cylinders: [], goods: [], suppliers: [], business: null, special: {}, saving: false, loaded: false };
  const cyl = {}, good = {};
  const cents = (v) => { const n = Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) && n > 0 ? Math.round(n * 100) : 0; };
  const rs = (p) => fmt.money((p / 100).toFixed(2));
  const num = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0; };
  const showError = (m) => { $("sn-error-text").textContent = m || ""; $("sn-error").hidden = !m; if (m) window.scrollTo({ top: 0, behavior: "smooth" }); };
  const bp = (p) => p == null || p === "" ? null : Math.round(Number(p) * 100);

  function listRate(c) {
    if (state.special[c.id] != null) return state.special[c.id];
    return state.customer && state.customer.type === "wholesale" ? c.wholesale_price : c.sale_price;
  }
  function itemRate(it) { return state.customer && state.customer.type === "wholesale" && Number(it.wholesale_price) ? it.wholesale_price : it.sale_price; }
  function resetRates() {
    state.cylinders.forEach((c) => { cyl[c.id].rate = listRate(c); });
    state.goods.forEach((g) => { good[g.id].rate = itemRate(g); });
    renderAll();
  }
  function productLines() {
    const out = [];
    state.cylinders.forEach((c) => {
      const s = cyl[c.id], rate = cents(s.rate), rateBp = bp(c.gst_rate);
      if (s.refill) out.push({ gross: s.refill * rate, rateBp, name: c.name, hsn: c.hsn });
      if (s.new_full) out.push({ gross: s.new_full * rate, rateBp, name: c.name, hsn: c.hsn });
    });
    state.goods.forEach((g) => {
      const s = good[g.id], q = Number(s.qty || 0);
      if (q > 0) out.push({ gross: Math.round(q * cents(s.rate)), rateBp: bp(g.gst_rate), name: g.name, hsn: g.hsn });
    });
    return out;
  }
  function taxSummary() {
    const lines = productLines(), gross = lines.reduce((a, l) => a + l.gross, 0);
    const discount = Math.min(cents($("sn-discount").value), gross);
    const place = ($("sn-place-state").value || (state.customer && (state.customer.state_code || (state.customer.gstin || "").slice(0, 2))) || (state.business && state.business.state_code) || "").trim();
    const interstate = !!(state.business && place && place !== state.business.state_code);
    let remaining = discount, taxable = 0, gst = 0, cgst = 0, sgst = 0, igst = 0;
    lines.forEach((line, i) => {
      const share = i === lines.length - 1 ? remaining : (gross ? Math.floor(discount * line.gross / gross) : 0);
      remaining -= share;
      const base = line.gross - share;
      const tax = line.rateBp == null ? 0 : Math.round(base * line.rateBp / 10000);
      taxable += base; gst += tax;
      if (interstate) igst += tax;
      else { const half = Math.ceil(tax / 2); cgst += half; sgst += tax - half; }
    });
    const depositIn = state.cylinders.reduce((a, c) => a + (cyl[c.id].new_full + cyl[c.id].new_empty) * cents(cyl[c.id].security), 0);
    const depositBack = state.cylinders.reduce((a, c) => {
      const s = cyl[c.id]; return a + (state.customer && s.dep_back ? s.empty_in * cents(s.dep_each) : 0);
    }, 0);
    return { lines, gross, discount, taxable, gst, cgst, sgst, igst, depositIn, depositBack,
      total: taxable + gst + depositIn - depositBack, interstate, place };
  }
  function taxConfigError() {
    const lines = productLines();
    if (lines.length && (!state.business || !state.business.name || !state.business.address || !state.business.state_code)) {
      return "Complete the agency details in Sales → Invoice settings before creating an invoice.";
    }
    for (const l of lines) {
      if (!l.hsn) return "Add an HSN/SAC code for " + l.name + " in Stock & Price before creating this invoice.";
      if (l.rateBp == null) return "Set a GST rate for " + l.name + " in Stock & Price before creating this invoice.";
      if (l.rateBp > 0 && state.business && !state.business.gstin) {
        return "The agency GSTIN is missing. Verify registration status and tax settings in Invoice settings with the CA.";
      }
    }
    if ($("sn-reverse-charge").value === "yes") {
      return "Reverse-charge invoices are not enabled yet. Have the CA confirm the applicable treatment before issuing one.";
    }
    return "";
  }
  const anything = () => state.cylinders.some((c) => {
    const s = cyl[c.id]; return s.refill || s.new_full || s.new_empty || s.empty_in || s.damaged_in;
  }) || state.goods.some((g) => Number(good[g.id].qty) > 0);

  function stepper(field, id, value, minusCls, plusCls) {
    return '<div class="pn-stepper"><button type="button" class="pn-step ' + minusCls + '" data-step="-1" data-f="' + field + '" data-id="' + id + '" aria-label="Less">−</button>' +
      '<input type="number" min="0" step="1" inputmode="numeric" value="' + value + '" data-f="' + field + '" data-id="' + id + '">' +
      '<button type="button" class="pn-step ' + plusCls + '" data-step="1" data-f="' + field + '" data-id="' + id + '" aria-label="More">+</button></div>';
  }
  function taxLabel(x) {
    return '<small class="sn-product-tax">' + (x.hsn ? 'HSN ' + esc(x.hsn) : 'HSN not set') + ' · ' +
      (x.gst_rate == null ? 'GST not set' : 'GST ' + esc(x.gst_rate) + '%') + '</small>';
  }
  function cylinderCard(c) {
    const s = cyl[c.id], used = s.refill + s.new_full, over = used > c.full;
    return '<article class="pn-item sn-card" data-cid="' + c.id + '">' +
      '<div class="sn-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(c.name) + '</b>' + taxLabel(c) + '<small>Full: ' + c.full + ' · Empty: ' + c.empty + '</small></div>' +
      '<button type="button" class="sn-price" data-edit-price="' + c.id + '" title="Tap to change the selling price">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button></div>' +
      '<div class="pn-qty-line"><div><b>Refill</b><small>Full cylinder supplied, customer returns an empty</small></div>' + stepper("refill", c.id, s.refill, "pn-step-minus", "pn-step-plus") + '</div>' +
      '<div class="pn-qty-line"><div><b>Good empty in</b><small>Customer returns a usable empty cylinder</small></div>' + stepper("empty_in", c.id, s.empty_in, "pn-step-minus", "sn-step-orange") + '</div>' +
      (s.empty_in && state.customer ? '<label class="sn-depback"><input type="checkbox" data-depback="' + c.id + '"' + (s.dep_back ? ' checked' : '') + '><span><b>Refund customer security deposit</b><small>Refund for ' + s.empty_in + ' returned cylinder(s)</small></span>' +
        (s.dep_back ? '<span class="pn-rate sn-dep-each"><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.dep_each) + '" data-f="dep_each" data-id="' + c.id + '"></span></span>' : '') + '</label>' : '') +
      (state.customer ? '<div class="pn-qty-line"><div><b>Damaged cylinder in</b><small>Customer deposit is forfeited; cylinder moves to damaged stock</small></div>' + stepper("damaged_in", c.id, s.damaged_in, "pn-step-minus", "sn-step-orange") + '</div>' : '') +
      (over ? '<p class="sn-warn">Only ' + c.full + ' full cylinder(s) in stock.</p>' : '') +
      '<button type="button" class="pn-bought-toggle sn-toggle' + (s.open ? ' on' : '') + '" data-toggle="' + c.id + '">Sell new cylinder or empty ' + (s.open ? '▴' : '▾') + '</button>' +
      (s.open ? '<div class="sn-more"><label class="pn-rate sn-dep"><small>Refundable security deposit (per cylinder)</small><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.security) + '" data-f="security" data-id="' + c.id + '"></span></label>' +
        '<div class="pn-qty-line"><div><b>New full cylinder</b><small>Gas price plus refundable security deposit</small></div>' + stepper("new_full", c.id, s.new_full, "pn-step-minus", "pn-step-plus") + '</div>' +
        '<div class="pn-qty-line"><div><b>Empty cylinder only</b><small>Refundable security deposit only</small></div>' + stepper("new_empty", c.id, s.new_empty, "pn-step-minus", "pn-step-plus") + '</div></div>' : '') +
      '<div class="pn-item-footer"><span>Taxable product amount (deposit separate)</span><b data-amt="' + c.id + '">' + rs((s.refill + s.new_full) * cents(s.rate)) + '</b></div></article>';
  }
  function goodCard(g) {
    const s = good[g.id];
    return '<article class="sn-good" data-gid="' + g.id + '"><div class="pn-item-title"><b>' + esc(g.name) + '</b>' + taxLabel(g) + '<small>In stock: ' + esc(g.qty) + ' ' + esc(g.unit) + '</small></div>' +
      '<button type="button" class="sn-price" data-edit-gprice="' + g.id + '">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button>' +
      '<label class="sn-qty"><small>Quantity (' + esc(g.unit) + ')</small><input type="number" min="0" step="any" inputmode="decimal" value="' + (s.qty || '') + '" placeholder="0" data-gqty="' + g.id + '"></label>' +
      '<b class="sn-gamt" data-gamt="' + g.id + '">' + rs(Math.round(Number(s.qty || 0) * cents(s.rate))) + '</b></article>';
  }
  function renderCylinders() {
    $("sn-cylinders").innerHTML = state.cylinders.length ? state.cylinders.map(cylinderCard).join("") : '<div class="pn-empty">No cylinder sizes yet. Add them in Stock &amp; Price first.</div>';
  }
  function renderGoods() {
    $("sn-items-panel").hidden = !state.goods.length;
    $("sn-goods").innerHTML = state.goods.map(goodCard).join("");
  }
  const renderAll = () => { renderCylinders(); renderGoods(); update(); };

  function update() {
    const t = taxSummary();
    state.cylinders.forEach((c) => {
      const el = document.querySelector('[data-amt="' + c.id + '"]');
      if (el) el.textContent = rs((cyl[c.id].refill + cyl[c.id].new_full) * cents(cyl[c.id].rate));
    });
    state.goods.forEach((g) => { const el = document.querySelector('[data-gamt="' + g.id + '"]'); if (el) el.textContent = rs(Math.round(Number(good[g.id].qty || 0) * cents(good[g.id].rate))); });
    $("sn-subtotal").textContent = rs(t.gross);
    $("sn-disc-row").hidden = !t.discount; $("sn-disc-show").textContent = '- ' + rs(t.discount);
    $("sn-gst-label").textContent = 'GST'; $("sn-gst-show").textContent = rs(t.gst);
    $("sn-gst-amount").value = (t.gst / 100).toFixed(2);
    $("sn-tax-split").textContent = t.interstate ? 'IGST: ' + rs(t.igst) : 'CGST: ' + rs(t.cgst) + ' · SGST: ' + rs(t.sgst);
    $("sn-deposit-in-row").hidden = !t.depositIn; $("sn-deposit-in-show").textContent = '+ ' + rs(t.depositIn);
    $("sn-back-row").hidden = !t.depositBack; $("sn-back-show").textContent = '- ' + rs(t.depositBack);
    $("sn-total-label").textContent = t.total < 0 ? 'Given back to customer' : 'Total payable';
    $("sn-total").textContent = rs(Math.abs(t.total));
    const pay = $("sn-payment");
    [...pay.options].forEach((o) => { if (o.value !== 'paid') o.disabled = !state.customer || t.total <= 0; });
    if (t.total <= 0) pay.value = 'paid';
    const mode = pay.value, paid = $("sn-paid");
    paid.disabled = mode !== 'partial';
    if (mode === 'paid') paid.value = t.total ? (Math.abs(t.total) / 100).toFixed(2) : '';
    if (mode === 'credit') paid.value = '';
    $("sn-paid-label").textContent = t.total < 0 ? 'Amount paid back now' : 'Amount received now';
    $("sn-pay-hint").textContent = state.customer ? 'Udhaar is added to ' + state.customer.name + '’s balance.' : 'Walk-in sales must be paid immediately.';
    const due = mode === 'paid' ? 0 : t.total - (mode === 'credit' ? 0 : cents(paid.value));
    $("sn-due-row").hidden = !(state.customer && due > 0); $("sn-due").textContent = rs(Math.max(0, due));
    const damaged = state.cylinders.some((c) => cyl[c.id].damaged_in > 0);
    $("sn-damaged-supplier-wrap").hidden = !damaged || state.suppliers.length <= 1;
    const noCustomerForDeposit = !state.customer && state.cylinders.some((c) => cyl[c.id].new_full || cyl[c.id].new_empty || cyl[c.id].empty_in || cyl[c.id].damaged_in);
    const configError = taxConfigError();
    $("sn-tax-warning").textContent = configError || (noCustomerForDeposit ? 'Select a customer before issuing a cylinder or processing a cylinder return.' : '');
    $("sn-tax-warning").hidden = !$("sn-tax-warning").textContent;
    const over = state.cylinders.some((c) => cyl[c.id].refill + cyl[c.id].new_full > c.full || cyl[c.id].new_empty > c.empty);
    const supplierMissing = damaged && state.suppliers.length > 1 && !$("sn-damaged-supplier").value;
    $("sn-save").disabled = state.saving || !anything() || !!configError || noCustomerForDeposit || over || supplierMissing;
  }

  async function setCustomer(c) {
    state.customer = c || null; state.special = {};
    $("sn-cust-avatar").textContent = c ? fmt.initials(c.name) : 'W';
    $("sn-cust-name").textContent = c ? c.name : 'Walk-in customer';
    $("sn-cust-meta").textContent = c ? ((c.type === 'wholesale' ? 'Wholesale' : 'Retail') + (c.phone ? ' · ' + c.phone : '')) : 'Cash sale, no udhaar';
    const b = Number(c && c.balance) || 0, tag = $("sn-cust-balance");
    tag.className = 'bal ' + (b > 0 ? 'bal-red' : b < 0 ? 'bal-green' : 'bal-clear');
    tag.textContent = !c ? '' : b > 0 ? fmt.money(b) + ' · To receive' : b < 0 ? fmt.money(-b) + ' · Paid extra' : 'Clear';
    $("sn-walkin").hidden = !c;
    $("sn-place-state").value = c ? (c.state_code || (c.gstin || '').slice(0, 2) || state.business.state_code) : state.business.state_code;
    if (c) {
      try { (await Api.get('/api/customers/' + c.id + '/prices')).forEach((p) => { if (p.special_price != null) state.special[p.cylinder_type_id] = p.special_price; }); }
      catch (_) { /* standard retail/wholesale prices remain usable */ }
    }
    resetRates();
  }
  function inlinePrice(btn, get, set) {
    const input = document.createElement('input'); input.className = 'sn-price-input'; input.type = 'number'; input.min = '0'; input.step = '0.01'; input.value = get();
    btn.replaceWith(input); input.focus(); input.select();
    const done = () => { set(input.value === '' ? get() : input.value); renderAll(); };
    input.addEventListener('blur', done);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  }
  document.addEventListener('click', (e) => {
    const step = e.target.closest('[data-step]');
    if (step) { const s = cyl[step.dataset.id], f = step.dataset.f; s[f] = Math.max(0, s[f] + Number(step.dataset.step)); renderCylinders(); update(); return; }
    const toggle = e.target.closest('[data-toggle]');
    if (toggle) { cyl[toggle.dataset.toggle].open = !cyl[toggle.dataset.toggle].open; renderCylinders(); return; }
    const price = e.target.closest('[data-edit-price]');
    if (price) { const id = price.dataset.editPrice; inlinePrice(price, () => cyl[id].rate, (v) => { cyl[id].rate = v; }); return; }
    const itemPrice = e.target.closest('[data-edit-gprice]');
    if (itemPrice) { const id = itemPrice.dataset.editGprice; inlinePrice(itemPrice, () => good[id].rate, (v) => { good[id].rate = v; }); }
  });
  $("sn-cylinders").addEventListener('change', (e) => {
    const t = e.target; if (!t.dataset.f) return;
    const s = cyl[t.dataset.id]; s[t.dataset.f] = (t.dataset.f === 'security' || t.dataset.f === 'dep_each') ? t.value : num(t.value);
    renderCylinders(); update();
  });
  $("sn-cylinders").addEventListener('change', (e) => { const id = e.target.dataset.depback; if (!id) return; cyl[id].dep_back = e.target.checked; renderCylinders(); update(); });
  $("sn-goods").addEventListener('input', (e) => { const id = e.target.dataset.gqty; if (!id) return; good[id].qty = e.target.value; update(); });
  ['sn-discount', 'sn-paid', 'sn-payment', 'sn-place-state', 'sn-damaged-supplier'].forEach((id) => { $(id).addEventListener('input', update); $(id).addEventListener('change', update); });
  $("sn-payment").addEventListener('change', update);
  $("sn-discount").addEventListener('input', (e) => Cust.cleanMoneyInput && Cust.cleanMoneyInput(e.target));
  $("sn-cust-pick").addEventListener('click', () => UI.selectCustomer(setCustomer));
  $("sn-walkin").addEventListener('click', () => setCustomer(null));
  $("sn-add-cust").addEventListener('click', () => Cust.openCustomerForm({ onSaved: (res) => setCustomer(res && res.id ? res : null) }));

  $("sn-form").addEventListener('submit', async (e) => {
    e.preventDefault(); showError('');
    if (state.saving) return;
    state.saving = true; update();
    const lines = state.cylinders.map((c) => ({ cylinder_type_id: c.id,
      refill: cyl[c.id].refill, new_full: cyl[c.id].new_full, new_empty: cyl[c.id].new_empty,
      empty_in: cyl[c.id].empty_in, damaged_in: cyl[c.id].damaged_in,
      deposit_back: !!(state.customer && cyl[c.id].dep_back && cyl[c.id].empty_in),
      deposit_each: String(cyl[c.id].dep_each), rate: String(cyl[c.id].rate), security: String(cyl[c.id].security) }))
      .filter((l) => l.refill || l.new_full || l.new_empty || l.empty_in || l.damaged_in);
    const items = state.goods.filter((g) => Number(good[g.id].qty) > 0)
      .map((g) => ({ item_id: g.id, qty: String(good[g.id].qty), rate: String(good[g.id].rate) }));
    try {
      const r = await Api.post('/api/sales', {
        customer_id: state.customer ? state.customer.id : null, date: $("sn-date").value,
        place_state_code: $("sn-place-state").value, reverse_charge: $("sn-reverse-charge").value,
        lines, items, discount: $("sn-discount").value.trim(), payment: $("sn-payment").value,
        received_in: $("sn-received").value, paid: $("sn-paid").value.trim(),
        damaged_supplier_id: $("sn-damaged-supplier").value, note: $("sn-note").value.trim(),
      });
      window.location.href = '/sales/' + r.id + '?new=1';
    } catch (ex) { state.saving = false; update(); showError(ex.message || 'Could not save the invoice.'); }
  });

  async function start() {
    if (state.loaded) { renderAll(); return; }
    state.loaded = true;
    $("sn-date").value = Cust.today(); $("sn-date").max = Cust.today();
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
    try {
      const [stock, extra, business] = await Promise.all([
        Api.get('/api/stock'), Api.get('/api/stock/extra'), Api.get('/api/business'),
      ]);
      state.cylinders = stock.cylinders; state.goods = stock.items; state.suppliers = extra.suppliers || []; state.business = business;
      $("sn-place-state").value = business.state_code || '';
      $("sn-damaged-supplier").innerHTML = '<option value="">Choose supplier</option>' + state.suppliers.map((s) => '<option value="' + s.id + '">' + esc(s.name) + '</option>').join('');
      if (state.suppliers.length === 1) $("sn-damaged-supplier").value = String(state.suppliers[0].id);
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, damaged_in: 0,
        rate: c.sale_price, security: c.security, open: false, dep_back: false, dep_each: c.security }; });
      state.goods.forEach((g) => { good[g.id] = { qty: '', rate: g.sale_price }; });
    } catch (ex) { showError('Could not load invoice settings or stock. ' + ex.message); $("sn-save").disabled = true; return; }
    renderAll();
    const pre = new URLSearchParams(location.search).get('customer');
    if (pre) { try { await setCustomer(await Api.get('/api/customers/' + pre)); } catch (_) { /* remain walk-in */ } }
  }
  window.SalesNew = { open: start };
})();
```

## A6. Replace `templates/sale_detail.html`
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">
<div id="rc-error" class="banner banner-error" hidden><span></span><button class="btn btn-ghost btn-sm" id="rc-retry" type="button">Retry</button></div>
<div id="rc-main" hidden>
  <div class="page-head rc-screen-head">
    <div class="title-block"><a class="back-btn" href="/sales" aria-label="Back to Sales"><i data-cicon="chevronLeft"></i></a>
      <div><h1 id="rc-title">Invoice</h1><small id="rc-sub"></small></div>
    </div>
    <button class="btn btn-danger-outline" id="rc-cancel" type="button">Cancel invoice</button>
  </div>
  <div class="rc-wrap rc-invoice-wrap">
    <div class="rc-banner rc-saved" id="rc-saved" hidden><i data-cicon="check"></i>Invoice saved. Print or save as PDF.</div>
    <div class="rc-banner rc-void" id="rc-void" hidden>This invoice has been cancelled. It is retained for audit history and is not valid for payment.</div>
    <article class="rc-paper rc-tax-invoice" id="rc-paper">
      <div class="rc-stamp" id="rc-stamp" hidden>CANCELLED</div>
      <header class="rc-invoice-head">
        <div><h2 class="rc-biz" id="rc-biz-name"></h2><p id="rc-biz-address"></p><p id="rc-biz-contact"></p><b id="rc-biz-gstin"></b></div>
        <div class="rc-doc-type"><strong id="rc-doc-type">INVOICE</strong><small id="rc-copy-label">Customer copy</small></div>
      </header>
      <div class="rc-invoice-meta">
        <div><span>Invoice number</span><b id="rc-number"></b></div>
        <div><span>Invoice date</span><b id="rc-date"></b></div>
        <div><span>Place of supply</span><b id="rc-place"></b></div>
        <div><span>Reverse charge</span><b id="rc-rcm"></b></div>
      </div>
      <section class="rc-bill-to"><b>Bill to</b><strong id="rc-customer"></strong><span id="rc-customer-address"></span><span id="rc-customer-gstin"></span></section>
      <div class="rc-table-wrap">
        <table class="rc-table rc-invoice-table">
          <thead><tr><th>#</th><th>Description</th><th>HSN/SAC</th><th class="num">Qty</th><th>Unit</th><th class="num">Rate</th><th class="num">Taxable</th><th class="num">GST %</th><th class="num">Tax</th><th class="num">Amount</th></tr></thead>
          <tbody id="rc-lines"></tbody>
        </table>
      </div>
      <div class="rc-invoice-bottom">
        <section class="rc-tax-summary"><b>Tax summary</b><div id="rc-tax-rows"></div></section>
        <section class="rc-sums" id="rc-sums"></section>
      </div>
      <div class="rc-amount-words" id="rc-words"></div>
      <div class="rc-invoice-footer">
        <div><b>Payment / bank details</b><p id="rc-bank"></p><p id="rc-terms"></p></div>
        <div class="rc-sign"><b>For <span id="rc-sign-name"></span></b><div></div><small>Authorized signatory</small></div>
      </div>
      <p class="rc-thanks">Thank you for your business.</p>
    </article>
    <div class="rc-actions">
      <button class="btn btn-dark" id="rc-print" type="button">Print / Save PDF</button>
      <button class="btn btn-whatsapp" id="rc-wa" type="button">WhatsApp</button>
      <a class="btn btn-orange" href="/sales?tab=new"><i data-icon="plus"></i>New sale</a>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script>
<script src="{{ url_for('static', filename='js/sale_detail.js') }}"></script>
{% endblock %}
```

## A7. Replace `static/js/sale_detail.js`
```javascript
// Printable customer tax invoice. All values come from the saved invoice snapshots.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split('/').pop());
  const justSaved = new URLSearchParams(location.search).get('new') === '1';
  let sale = null;
  const rupees = (n) => fmt.money(n);
  function indianWords(value) {
    const ones = ['Zero','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen'];
    const tens = ['', '', 'Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety'];
    const underHundred = (n) => n < 20 ? ones[n] : tens[Math.floor(n / 10)] + (n % 10 ? ' ' + ones[n % 10] : '');
    function words(n) {
      if (n < 100) return underHundred(n);
      const parts = [];
      if (n >= 10000000) { parts.push(words(Math.floor(n / 10000000)) + ' Crore'); n %= 10000000; }
      if (n >= 100000) { parts.push(words(Math.floor(n / 100000)) + ' Lakh'); n %= 100000; }
      if (n >= 1000) { parts.push(words(Math.floor(n / 1000)) + ' Thousand'); n %= 1000; }
      if (n >= 100) { parts.push(ones[Math.floor(n / 100)] + ' Hundred'); n %= 100; }
      if (n) parts.push(underHundred(n));
      return parts.join(' ');
    }
    return words(Math.floor(Math.abs(value)));
  }
  const label = (line) => {
    if (line.kind === 'deposit' || line.kind === 'deposit_refund' || line.kind === 'deposit_forfeit' || line.kind === 'empty_in') return line.name;
    return line.name + (line.detail ? ' — ' + line.detail : '');
  };
  const taxAmount = (line) => Number(line.cgst || 0) + Number(line.sgst || 0) + Number(line.igst || 0);

  function lineRow(line, index) {
    const informational = line.kind === 'empty_in' || line.kind === 'deposit_forfeit';
    const amount = Number(line.amount || 0);
    const tax = taxAmount(line);
    return '<tr' + (informational ? ' class="rc-info-line"' : '') + '><td>' + (index + 1) + '</td>' +
      '<td>' + esc(label(line)) + (line.detail && line.kind !== 'product' ? '<small>' + esc(line.detail) + '</small>' : '') + '</td>' +
      '<td>' + esc(line.hsn || '—') + '</td><td class="num">' + esc(line.qty) + '</td><td>' + esc(line.unit || '—') + '</td>' +
      '<td class="num">' + (informational ? '—' : esc(rupees(line.rate))) + '</td>' +
      '<td class="num">' + (line.kind === 'product' ? esc(rupees(line.taxable)) : '—') + '</td>' +
      '<td class="num">' + (line.gst_rate == null ? '—' : esc(String(line.gst_rate)) + '%') + '</td>' +
      '<td class="num">' + (tax ? esc(rupees(tax.toFixed ? tax.toFixed(2) : tax)) : '—') + '</td>' +
      '<td class="num"><b>' + (amount < 0 ? '− ' : '') + (informational ? '—' : esc(rupees(Math.abs(amount)))) + '</b></td></tr>';
  }
  function sumRow(labelText, value, cls, prefix) {
    return '<div class="' + (cls || '') + '"><span>' + labelText + '</span><b>' + (prefix || '') + esc(rupees(value)) + '</b></div>';
  }
  function render() {
    const b = sale.business || {}, c = sale.customer || null, cancelled = sale.status === 'cancelled';
    $('rc-main').hidden = false;
    $('rc-title').textContent = 'Invoice ' + sale.number;
    $('rc-sub').textContent = Cust.date(sale.date) + ' · ' + sale.time;
    $('rc-number').textContent = sale.number;
    $('rc-date').textContent = Cust.date(sale.date);
    $('rc-place').textContent = sale.place_state_code || '—';
    $('rc-rcm').textContent = sale.reverse_charge ? 'Yes' : 'No';
    $('rc-biz-name').textContent = b.name || '';
    $('rc-doc-type').textContent = b.gstin ? 'TAX INVOICE' : 'INVOICE';
    $('rc-copy-label').textContent = b.gstin ? 'Original for recipient' : 'Customer copy';
    $('rc-biz-address').textContent = b.address || '';
    $('rc-biz-contact').textContent = [b.phone, b.email].filter(Boolean).join(' · ');
    $('rc-biz-gstin').textContent = b.gstin ? 'GSTIN: ' + b.gstin : '';
    $('rc-customer').textContent = c ? c.name : 'Walk-in customer';
    $('rc-customer-address').textContent = c ? (c.billing_address || c.address || '') : '';
    $('rc-customer-gstin').textContent = c && c.gstin ? 'GSTIN: ' + c.gstin : 'Unregistered customer';
    $('rc-lines').innerHTML = sale.lines.map(lineRow).join('');

    const taxRows = [];
    if (Number(sale.cgst)) taxRows.push(sumRow('CGST', sale.cgst));
    if (Number(sale.sgst)) taxRows.push(sumRow('SGST', sale.sgst));
    if (Number(sale.igst)) taxRows.push(sumRow('IGST', sale.igst));
    if (!taxRows.length) taxRows.push('<div><span>GST</span><b>—</b></div>');
    $('rc-tax-rows').innerHTML = taxRows.join('');

    const rows = [sumRow('Product subtotal', sale.subtotal)];
    if (Number(sale.discount)) rows.push(sumRow('Discount', sale.discount, 'rc-negative', '− '));
    rows.push(sumRow('Taxable value', sale.taxable));
    rows.push(sumRow('Total GST', sale.gst));
    if (Number(sale.deposit_received)) rows.push(sumRow('Refundable security deposit received', sale.deposit_received));
    if (Number(sale.deposit_refunded)) rows.push(sumRow('Refundable security deposit refunded', sale.deposit_refunded, 'rc-negative', '− '));
    const total = Number(sale.total);
    rows.push(sumRow(total < 0 ? 'Amount to be paid back' : 'Invoice total payable', Math.abs(total), 'rc-total'));
    rows.push(sumRow(total < 0 ? 'Paid back' : 'Amount received', Math.abs(Number(sale.paid)), ''));
    if (Number(sale.due) > 0 && !cancelled) rows.push(sumRow('Balance due', sale.due, 'rc-due'));
    $('rc-sums').innerHTML = rows.join('');
    $('rc-bank').textContent = [b.bank_name, b.bank_account ? 'A/c ' + b.bank_account : '', b.bank_ifsc ? 'IFSC ' + b.bank_ifsc : ''].filter(Boolean).join(' · ');
    $('rc-terms').textContent = b.terms || '';
    $('rc-sign-name').textContent = b.name || '';
    const totalPaise = Math.round(Math.abs(Number(sale.total)) * 100);
    const words = 'Rupees ' + indianWords(Math.floor(totalPaise / 100)) +
      (totalPaise % 100 ? ' and ' + indianWords(totalPaise % 100) + ' Paise' : '') + ' Only';
    $('rc-words').textContent = (Number(sale.total) < 0 ? 'Refund payable: ' : 'Amount in words: ') + words;
    $('rc-words').hidden = false;
    $('rc-saved').hidden = !(justSaved && !cancelled);
    $('rc-void').hidden = !cancelled;
    $('rc-stamp').hidden = !cancelled;
    $('rc-cancel').hidden = cancelled;
    $('rc-paper').classList.toggle('is-void', cancelled);
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
  }
  async function load() {
    $('rc-error').hidden = true;
    try { sale = await Api.get('/api/sales/' + sid); render(); }
    catch (e) { $('rc-main').hidden = true; $('rc-error').hidden = false; $('rc-error').querySelector('span').textContent = 'Could not load invoice. ' + e.message; }
  }
  function whatsappText() {
    const lines = sale.lines.filter((x) => x.kind !== 'empty_in' && x.kind !== 'deposit_forfeit')
      .map((x) => '• ' + x.qty + ' x ' + label(x) + ' = ' + rupees(x.amount));
    return ['*' + (sale.business && sale.business.name || 'Agency') + '*', 'Invoice ' + sale.number + ' · ' + Cust.date(sale.date), '']
      .concat(lines, ['', 'Total: ' + rupees(Math.abs(Number(sale.total))), 'Paid: ' + rupees(Math.abs(Number(sale.paid)))],
        Number(sale.due) > 0 ? ['Balance due: ' + rupees(sale.due)] : [], ['']).join('\n');
  }
  $('rc-wa').addEventListener('click', () => {
    const digits = ((sale.customer && sale.customer.phone) || '').replace(/\D/g, '');
    const phone = digits.length === 10 ? '91' + digits : digits;
    window.open('https://wa.me/' + phone + '?text=' + encodeURIComponent(whatsappText()), '_blank', 'noopener');
  });
  $('rc-print').addEventListener('click', () => window.print());
  $('rc-retry').addEventListener('click', load);
  $('rc-cancel').addEventListener('click', () => Cust.openConfirm({
    title: 'Cancel this invoice?', danger: true, confirmLabel: 'Cancel invoice', cancelLabel: 'Keep invoice',
    message: 'Stock and customer cylinder balances will be reversed. The original invoice remains in history, marked cancelled. A damaged cylinder already dispatched to a supplier cannot be cancelled.',
    onConfirm: async () => { await Api.post('/api/sales/' + sid + '/cancel', {}); Cust.toast('Invoice cancelled'); await load(); },
  }));
  load();
})();
```

## A8. Create `tests/test_sales_invoice.py`
```python
"""v0.6 HSN/tax-invoice/customer-deposit regression tests. GSTINs are test fixtures only."""
import importlib
import os
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InvoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "invoice-test.db")
        import app as app_module
        importlib.reload(app_module)
        self.app_module = app_module
        self.client = app_module.app.test_client()
        import db
        self.db = db
        self.conn = db.connect()
        self.assertEqual(self.client.put("/api/business", json={
            "name": "Test LPG Agency", "address": "1 Test Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "state_code": "22", "invoice_prefix": "T",
        }).status_code, 200)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def make_cylinder(self):
        result = self.client.post("/api/cylinders", json={
            "weight_kg": "8.6", "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": "500", "full": "5", "empty": "2",
            "hsn": "27111910", "gst_rate": "18",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()

    def make_customer(self):
        result = self.client.post("/api/customers", json={
            "name": "Test Restaurant", "type": "wholesale", "phone": "9876543210",
            "address": "Durg", "billing_address": "Restaurant Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "state_code": "22",
            "opening_type": "udhaar", "opening_amount": "0",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()

    def sell(self, cylinder, customer, **counts):
        line = {"cylinder_type_id": cylinder["id"], "rate": "100", "security": "500",
                "refill": 0, "new_full": 0, "new_empty": 0, "empty_in": 0,
                "damaged_in": 0, "deposit_each": "500"}
        line.update(counts)
        return self.client.post("/api/sales", json={
            "customer_id": customer["id"] if customer else None,
            "date": date.today().isoformat(), "place_state_code": "22",
            "lines": [line], "items": [], "discount": "0", "payment": "paid",
            "received_in": "cash", "paid": "0", "reverse_charge": "no",
        })

    def test_product_hsn_is_snapshotted_and_tax_is_split(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        invoice_id = response.get_json()["id"]
        detail = self.client.get(f"/api/sales/{invoice_id}").get_json()
        self.assertEqual(detail["lines"][0]["hsn"], "27111910")
        self.assertEqual(detail["cgst"], "9.00")
        self.assertEqual(detail["sgst"], "9.00")
        self.assertEqual(detail["igst"], "0.00")
        self.assertEqual(detail["total"], "118.00")

        changed = self.client.put(f"/api/cylinders/{cylinder['id']}", json={
            "weight_kg": "8.6", "hsn": "27111200", "gst_rate": "5",
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())
        old_detail = self.client.get(f"/api/sales/{invoice_id}").get_json()
        self.assertEqual(old_detail["lines"][0]["hsn"], "27111910")
        self.assertEqual(old_detail["lines"][0]["gst_rate"], 18)

    def test_new_full_deposit_is_separate_from_taxable_value(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        detail = self.client.get(f"/api/sales/{response.get_json()['id']}").get_json()
        self.assertEqual(detail["subtotal"], "100.00")
        self.assertEqual(detail["gst"], "18.00")
        self.assertEqual(detail["deposit_received"], "500.00")
        self.assertEqual(detail["total"], "618.00")
        deposit = self.conn.execute(
            "SELECT kind,qty,amount_paise,status FROM customer_deposit_events WHERE customer_id=?",
            (customer["id"],),
        ).fetchone()
        self.assertEqual((deposit["kind"], deposit["qty"], deposit["amount_paise"], deposit["status"]),
                         ("received", 1, 50000, "active"))

    def test_good_empty_refund_updates_only_customer_deposit_ledger(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        sale = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(sale.status_code, 201, sale.get_json())
        returned = self.sell(cylinder, customer, empty_in=1, deposit_back=True)
        self.assertEqual(returned.status_code, 201, returned.get_json())
        detail = self.client.get(f"/api/sales/{returned.get_json()['id']}").get_json()
        self.assertEqual(detail["deposit_refunded"], "500.00")
        events = self.conn.execute(
            "SELECT kind,amount_paise,status FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([e["kind"] for e in events], ["received", "refunded"])
        self.assertEqual([e["amount_paise"] for e in events], [50000, 50000])
        # The supplier deposit ledger is untouched by a normal customer deposit refund.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0], 0)

    def test_damaged_customer_return_forfeits_customer_deposit_and_marks_stock(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())
        events = self.conn.execute(
            "SELECT kind,amount_paise,status FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([e["kind"] for e in events], ["received", "forfeited"])
        stock = self.client.get("/api/stock").get_json()
        c = next(x for x in stock["cylinders"] if x["id"] == cylinder["id"])
        self.assertEqual(c["damaged"], 1)
        # With no suppliers in this isolated test, no supplier security event is fabricated.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0], 0)

    def test_damaged_customer_return_forfeits_the_matching_supplier_deposit(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin) VALUES(?,?)",
            ("Go Gas Test", "22AAAAA0000A1Z5"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
            "VALUES(?,?,?,?,0)", (supplier_id, cylinder["id"], 7000, 50000),
        )
        self.conn.execute(
            "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note) "
            "VALUES(?,?,'paid',5,250000,'Supplier purchase security')",
            (cylinder["id"], supplier_id),
        )
        self.conn.commit()

        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())

        supplier_events = self.conn.execute(
            "SELECT kind,qty,amount_paise,status FROM cylinder_deposits "
            "WHERE supplier_id=? ORDER BY id", (supplier_id,),
        ).fetchall()
        self.assertEqual(
            [(r["kind"], r["qty"], r["amount_paise"], r["status"]) for r in supplier_events],
            [("paid", 5, 250000, "active"), ("cancelled", 1, 50000, "active")],
        )

    def test_damaged_customer_return_cannot_overforfeit_supplier_deposit(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin) VALUES(?,?)",
            ("Go Gas Test", "22AAAAA0000A1Z5"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
            "VALUES(?,?,?,?,0)", (supplier_id, cylinder["id"], 7000, 50000),
        )
        self.conn.commit()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())

        before_full = self.conn.execute(
            "SELECT with_customers_qty,damaged_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)
        ).fetchone()
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 409, damaged.get_json())
        after_full = self.conn.execute(
            "SELECT with_customers_qty,damaged_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)
        ).fetchone()
        self.assertEqual(tuple(before_full), tuple(after_full))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM customer_deposit_events WHERE kind='forfeited'"
        ).fetchone()[0], 0)

    def test_missing_product_hsn_or_gst_blocks_final_invoice(self):
        result = self.client.post("/api/cylinders", json={
            "weight_kg": "7.7", "sale_price": "100", "full": "2", "empty": "0",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        cylinder = result.get_json()
        response = self.client.post("/api/sales", json={
            "date": date.today().isoformat(), "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "payment": "paid", "received_in": "cash",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("HSN", response.get_json()["error"])


    def test_nonzero_gst_requires_agency_gstin(self):
        cylinder = self.make_cylinder()
        self.assertEqual(self.client.put("/api/business", json={
            "name": "Test LPG Agency", "address": "1 Test Road, Durg", "state_code": "22",
            "invoice_prefix": "T",
        }).status_code, 200)
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.sell(cylinder, None, refill=1)
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertIn("GSTIN", response.get_json()["error"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], before)

    def test_reverse_charge_is_not_silently_treated_as_forward_charge(self):
        cylinder = self.make_cylinder()
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.client.post("/api/sales", json={
            "date": date.today().isoformat(), "place_state_code": "22", "reverse_charge": "yes",
            "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "payment": "paid", "received_in": "cash",
        })
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertIn("Reverse-charge", response.get_json()["error"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], before)

    def test_duplicate_cylinder_rows_are_rejected(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        before = self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0]
        payload = {
            "customer_id": customer["id"], "date": date.today().isoformat(), "place_state_code": "22",
            "payment": "paid", "received_in": "cash", "lines": [
                {"cylinder_type_id": cylinder["id"], "refill": 3, "rate": "100"},
                {"cylinder_type_id": cylinder["id"], "refill": 3, "rate": "100"},
            ], "items": [],
        }
        response = self.client.post("/api/sales", json=payload)
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0], before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)

    def test_zero_security_still_tracks_issued_cylinder_for_damage_return(self):
        cylinder = self.client.post("/api/cylinders", json={
            "weight_kg": "7.7", "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": "0", "full": "2", "empty": "0",
            "hsn": "27111910", "gst_rate": "18",
        }).get_json()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1, security="0")
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())
        events = self.conn.execute(
            "SELECT kind,qty,amount_paise FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([(e["kind"], e["qty"], e["amount_paise"]) for e in events],
                         [("received", 1, 0), ("forfeited", 1, 0)])

    def test_paid_invoice_cannot_be_cancelled_without_refund_workflow(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
        before = self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0]
        cancelled = self.client.post(f"/api/sales/{sale_id}/cancel", json={})
        self.assertEqual(cancelled.status_code, 409, cancelled.get_json())
        self.assertEqual(self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0], before)

    def test_unpaid_credit_invoice_can_be_cancelled_and_restores_stock(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.client.post("/api/sales", json={
            "customer_id": customer["id"], "date": date.today().isoformat(), "place_state_code": "22",
            "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "discount": "0", "payment": "credit", "received_in": "cash", "paid": "0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
        before = self.conn.execute("SELECT full_qty,empty_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()
        self.assertEqual((before["full_qty"], before["empty_qty"]), (4, 3))
        cancelled = self.client.post(f"/api/sales/{sale_id}/cancel", json={})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        after = self.conn.execute("SELECT full_qty,empty_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()
        self.assertEqual((after["full_qty"], after["empty_qty"]), (5, 2))
        self.assertEqual(self.conn.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()[0], "cancelled")

    def test_failed_stock_validation_does_not_create_invoice(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.sell(cylinder, customer, refill=99)
        self.assertEqual(response.status_code, 409)
        after = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
```

---

# B. SMALL EDITS

## B1. `schema.sql` — append the invoice tables
Go to the very end of `schema.sql` and append this SQL:

```sql

-- v0.6: persistent customer invoice lines. Every printable detail is a snapshot.
CREATE TABLE IF NOT EXISTS sale_lines (
    id              INTEGER PRIMARY KEY,
    sale_id         INTEGER NOT NULL REFERENCES sales(id),
    line_no         INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    action          TEXT,
    cylinder_type_id INTEGER REFERENCES cylinder_types(id),
    item_id         INTEGER REFERENCES catalog_items(id),
    description     TEXT NOT NULL,
    hsn             TEXT,
    unit            TEXT NOT NULL DEFAULT 'NOS',
    qty_milli       INTEGER NOT NULL DEFAULT 0,
    rate_paise      INTEGER NOT NULL DEFAULT 0,
    gross_paise     INTEGER NOT NULL DEFAULT 0,
    discount_paise  INTEGER NOT NULL DEFAULT 0,
    taxable_paise   INTEGER NOT NULL DEFAULT 0,
    gst_rate_bp     INTEGER,
    cgst_paise      INTEGER NOT NULL DEFAULT 0,
    sgst_paise      INTEGER NOT NULL DEFAULT 0,
    igst_paise      INTEGER NOT NULL DEFAULT 0,
    amount_paise    INTEGER NOT NULL DEFAULT 0,
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sale_lines_sale ON sale_lines(sale_id, line_no);

-- Customer security deposits are independent of the agency's supplier deposits.
-- received/refunded/forfeited rows are never deleted; a cancelled invoice reverses the row.
CREATE TABLE IF NOT EXISTS customer_deposit_events (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    sale_id         INTEGER REFERENCES sales(id),
    kind            TEXT NOT NULL CHECK (kind IN ('received','refunded','forfeited')),
    qty             INTEGER NOT NULL DEFAULT 0,
    amount_paise    INTEGER NOT NULL DEFAULT 0,
    event_date      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','reversed')),
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_customer_deposits_customer
    ON customer_deposit_events(customer_id, cylinder_type_id, status);
CREATE INDEX IF NOT EXISTS idx_customer_deposits_sale ON customer_deposit_events(sale_id);

-- Ordinary catalogue stock movements caused by sales and sale cancellations.
CREATE TABLE IF NOT EXISTS catalog_sale_movements (
    id                   INTEGER PRIMARY KEY,
    sale_id              INTEGER NOT NULL REFERENCES sales(id),
    item_id              INTEGER NOT NULL REFERENCES catalog_items(id),
    moved_at             TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    quantity_delta_milli INTEGER NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('sale','sale_cancel')),
    note                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_catalog_sale_movements_item
    ON catalog_sale_movements(item_id, moved_at);
```

## B2. `db.py` — additive v0.6 migrations
Find this exact block inside `init_db()`:

```python
        with open(resource_path("schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
```

Immediately **after** it, insert:

```python
        # v0.6: HSN/GST setup, customer invoice details and permanent invoice snapshots.
        migrations = {
            "cylinder_types": {
                "hsn": "TEXT",
                "gst_rate_bp": "INTEGER",
            },
            "catalog_items": {
                "hsn": "TEXT",
                "gst_rate_bp": "INTEGER",
            },
            "customers": {
                "gstin": "TEXT",
                "state_code": "TEXT",
                "billing_address": "TEXT",
            },
            "sales": {
                "cgst_paise": "INTEGER NOT NULL DEFAULT 0",
                "sgst_paise": "INTEGER NOT NULL DEFAULT 0",
                "igst_paise": "INTEGER NOT NULL DEFAULT 0",
                "taxable_paise": "INTEGER NOT NULL DEFAULT 0",
                "deposit_received_paise": "INTEGER NOT NULL DEFAULT 0",
                "deposit_refunded_paise": "INTEGER NOT NULL DEFAULT 0",
                "place_state_code": "TEXT",
                "reverse_charge": "INTEGER NOT NULL DEFAULT 0",
                "business_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "customer_snapshot_json": "TEXT NOT NULL DEFAULT 'null'",
            },
            "cylinder_deposits": {
                "sale_id": "INTEGER REFERENCES sales(id)",
                "status": "TEXT NOT NULL DEFAULT 'active'",
            },
        }
        for table, columns in migrations.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
```

This adds columns without rebuilding existing tables. The new tables themselves are created by B1. Existing bills and customer records keep their old data; their new snapshot fields receive safe defaults.

## B3. `api/util.py` — add HSN, GST rate, GSTIN and state validators
Append this complete block to the very end of `api/util.py`:

```python

# ---------- GST / HSN reference validation (v0.6) ----------
STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}


def hsn_field(data, key="hsn"):
    """Return HSN/SAC as text; optional on product setup, required by invoice logic."""
    value = data.get(key)
    value = "" if value is None else str(value).strip().replace(" ", "")
    if not value:
        return None
    if not re.fullmatch(r"[0-9]{2,10}", value):
        raise ApiError("HSN/SAC must contain 2 to 10 digits.", field=key)
    return value


def gst_rate_bp_field(data, key="gst_rate"):
    """Convert a percentage (e.g. 18 or 5.5) into integer basis points."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    raw = data.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ApiError("GST rate must be a valid percentage.", field=key)
    if not value.is_finite() or value < 0 or value > 100:
        raise ApiError("GST rate must be between 0 and 100 percent.", field=key)
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def state_code_field(data, key="state_code", required=False):
    raw = data.get(key)
    value = "" if raw is None else str(raw).strip()
    if not value:
        if required:
            raise ApiError("Choose a state code.", field=key)
        return None
    if value not in STATES:
        raise ApiError("Choose a valid two-digit Indian state code.", field=key)
    return value


def gstin_field(data, key="gstin", required=False):
    value = (data.get(key) or "")
    value = str(value).strip().upper()
    if not value:
        if required:
            raise ApiError("GSTIN is required for invoice settings.", field=key)
        return None
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        raise ApiError("Enter a valid 15-character GSTIN.", field=key)
    if value[:2] not in STATES:
        raise ApiError("GSTIN contains an unknown state code.", field=key)
    return value
```

## B4. `api/stock.py` — expose and save HSN/GST on stock products

### B4.1 Imports
Find:

```python
from .util import (ApiError, body, int_field, money_field, quantity_from_milli,
                   quantity_milli_field, text)
```

Replace with:

```python
from .util import (ApiError, body, gst_rate_bp_field, hsn_field, int_field,
                   money_field, quantity_from_milli, quantity_milli_field, text)
```

### B4.2 Cylinder response
In `_cylinder_dict`, find:

```python
        "id": r["id"], "name": r["name"], "kg": r["kg"],
```

Replace with:

```python
        "id": r["id"], "name": r["name"], "kg": r["kg"], "hsn": r["hsn"],
        "gst_rate": None if r["gst_rate_bp"] is None else str(r["gst_rate_bp"] / 100),
```

### B4.3 Catalogue-item response
In `_item_dict`, find:

```python
        "id": r["id"], "name": r["name"], "unit": r["unit"], "qty": quantity_from_milli(r["stock_qty_milli"]),
```

Replace with:

```python
        "id": r["id"], "name": r["name"], "unit": r["unit"], "qty": quantity_from_milli(r["stock_qty_milli"]),
        "hsn": r["hsn"], "gst_rate": None if r["gst_rate_bp"] is None else str(r["gst_rate_bp"] / 100),
```

### B4.4 Cylinder creation
Inside `cylinder_create()`, immediately after the `prices = {...}` block, add:

```python
    hsn = hsn_field(data)
    gst_rate_bp = gst_rate_bp_field(data)
```

Find the cylinder `UPDATE` statement:

```python
        db.execute("UPDATE cylinder_types SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?, security_paise=?,"
                   " full_qty=?, empty_qty=? WHERE id=?",
                   (prices["sale_price"], prices["wholesale_price"], prices["purchase_price"], prices["security"], full, empty, tid))
```

Replace with:

```python
        db.execute("UPDATE cylinder_types SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?, security_paise=?,"
                   " full_qty=?, empty_qty=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (prices["sale_price"], prices["wholesale_price"], prices["purchase_price"], prices["security"],
                    full, empty, hsn, gst_rate_bp, tid))
```

### B4.5 Cylinder editing
In `cylinder_rename()`, find:

```python
    _cylinder(db, tid)
    with transaction(db):
```

Replace with:

```python
    current = _cylinder(db, tid)
    hsn = hsn_field(data) if "hsn" in data else current["hsn"]
    gst_rate_bp = gst_rate_bp_field(data) if "gst_rate" in data else current["gst_rate_bp"]
    with transaction(db):
```

Then find:

```python
        db.execute("UPDATE cylinder_types SET name=?, kg=? WHERE id=?", (label, weight, tid))
```

Replace with:

```python
        db.execute("UPDATE cylinder_types SET name=?, kg=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (label, weight, hsn, gst_rate_bp, tid))
```

### B4.6 Catalogue-item creation
Inside `item_create()`, after the `sale, wholesale, buy = ...` block, add:

```python
    hsn = hsn_field(data)
    gst_rate_bp = gst_rate_bp_field(data)
```

Find:

```python
        db.execute("UPDATE catalog_items SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?, stock_qty_milli=? WHERE id=?",
                   (sale, wholesale, buy, qty, iid))
```

Replace with:

```python
        db.execute("UPDATE catalog_items SET sale_price_paise=?, wholesale_price_paise=?, purchase_price_paise=?,"
                   " stock_qty_milli=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (sale, wholesale, buy, qty, hsn, gst_rate_bp, iid))
```

### B4.7 Catalogue-item editing
In `item_edit()`, find:

```python
    _item(db, iid)
    with transaction(db):
```

Replace with:

```python
    current = _item(db, iid)
    hsn = hsn_field(data) if "hsn" in data else current["hsn"]
    gst_rate_bp = gst_rate_bp_field(data) if "gst_rate" in data else current["gst_rate_bp"]
    with transaction(db):
```

Then find:

```python
        db.execute("UPDATE catalog_items SET name=?, unit=? WHERE id=?", (name, unit, iid))
```

Replace with:

```python
        db.execute("UPDATE catalog_items SET name=?, unit=?, hsn=?, gst_rate_bp=? WHERE id=?",
                   (name, unit, hsn, gst_rate_bp, iid))
```

### B4.8 Catalogue-item sale history
Inside `stock_history()`, find the existing catalogue history query (the one beginning with `SELECT 'a' || a.id AS key` and followed by a `UNION ALL SELECT 'p' || c.id`). Replace its SQL string with:

```python
            "SELECT 'a' || a.id AS key, a.id, a.moved_at, a.kind, a.note, a.quantity_delta_milli AS d, i.name, i.unit, NULL AS number "
            "FROM catalog_adjustments a JOIN catalog_items i ON i.id=a.item_id "
            "UNION ALL SELECT 'p' || c.id, c.id, c.moved_at, 'purchase', c.note, c.quantity_delta_milli, i.name, i.unit, p.number "
            "FROM catalog_stock_movements c JOIN catalog_items i ON i.id=c.item_id JOIN purchases p ON p.id=c.purchase_id "
            "UNION ALL SELECT 's' || m.id, m.id, m.moved_at, m.kind, m.note, m.quantity_delta_milli, i.name, i.unit, s.number "
            "FROM catalog_sale_movements m JOIN catalog_items i ON i.id=m.item_id JOIN sales s ON s.id=m.sale_id "
            "ORDER BY 3 DESC, 2 DESC LIMIT ?", (limit + 1,)
```

## B5. `api/customers.py` — save customer GST details for reuse

### B5.1 Imports
Find the `.util` import and replace it with:

```python
from .util import (RECEIVED_IN, ApiError, body, day_field, gstin_field, int_field,
                   money_field, phone_field, state_code_field, text)
```

### B5.2 Customer response
Inside `_dict(r)`, after the `"address": r["address"],` line, add:

```python
        "billing_address": r["billing_address"],
        "gstin": r["gstin"],
        "state_code": r["state_code"],
```

### B5.3 Customer parser
Inside `_parse()`, before the `return { ... }`, add:

```python
    gstin = gstin_field(data)
    state_code = state_code_field(data)
    if gstin and not state_code:
        state_code = gstin[:2]
    if gstin and state_code != gstin[:2]:
        raise ApiError("Customer state code must match the first two digits of the GSTIN.", field="state_code")
```

Inside the returned dictionary, after the existing `"address": ...` item, add:

```python
        "billing_address": text(data, "billing_address", "Billing address", max_len=250),
        "gstin": gstin,
        "state_code": state_code,
```

### B5.4 Customer creation
Find the `INSERT INTO customers` statement and replace it with:

```python
        cid = db.execute(
            "INSERT INTO customers (name, phone, address, type, opening_balance_paise, note, billing_address, gstin, state_code)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f["name"], f["phone"], f["address"], f["type"], f["opening"], f["note"],
             f["billing_address"], f["gstin"], f["state_code"]),
        ).lastrowid
```

### B5.5 Customer editing
Replace the start of `customer_update()`:

```python
    customer_row(cid)
    f = _parse(body(), self_id=cid)
    db = get_db()
```

with:

```python
    old = customer_row(cid)
    data = body()
    f = _parse(data, self_id=cid)
    for key in ("billing_address", "gstin", "state_code"):
        if key not in data:
            f[key] = old[key]
    db = get_db()
```

Then replace its `UPDATE customers` statement with:

```python
        db.execute(
            "UPDATE customers SET name=?, phone=?, address=?, type=?, opening_balance_paise=?, note=?,"
            " billing_address=?, gstin=?, state_code=? WHERE id=?",
            (f["name"], f["phone"], f["address"], f["type"], f["opening"], f["note"],
             f["billing_address"], f["gstin"], f["state_code"], cid),
        )
```

## B6. `static/js/customers_common.js` — add customer tax details to Add/Edit

### B6.1 Add the fields
In `openCustomerForm()`, find the existing address field HTML:

```javascript
      '<label class="field"><span>Address (optional)</span><input class="input" name="address" maxlength="200" autocomplete="off"></label>' +
```

Replace it with:

```javascript
      '<label class="field"><span>Address (optional)</span><input class="input" name="address" maxlength="200" autocomplete="off"></label>' +
      '<label class="field"><span>Billing address (optional)</span><input class="input" name="billing_address" maxlength="250" autocomplete="off"></label>' +
      '<div class="two"><label class="field"><span>GSTIN (optional)</span><input class="input" name="gstin" maxlength="15" autocapitalize="characters" autocomplete="off"></label>' +
      '<label class="field"><span>GST state code (optional)</span><input class="input" name="state_code" maxlength="2" inputmode="numeric" placeholder="e.g. 22"></label></div>' +
```

### B6.2 Populate fields on edit
After:

```javascript
      q("address").value = customer.address || "";
```

add:

```javascript
      q("billing_address").value = customer.billing_address || "";
      q("gstin").value = customer.gstin || "";
      q("state_code").value = customer.state_code || "";
```

### B6.3 Include them in the payload
In the `payload` object inside the form submit handler, replace:

```javascript
        name, type: f.type, phone: q("phone").value.trim(), address: q("address").value.trim(),
        opening_type: f.otype, opening_amount: q("opening_amount").value.trim(), note: q("note").value.trim(),
```

with:

```javascript
        name, type: f.type, phone: q("phone").value.trim(), address: q("address").value.trim(),
        billing_address: q("billing_address").value.trim(), gstin: q("gstin").value.trim().toUpperCase(),
        state_code: q("state_code").value.trim(),
        opening_type: f.otype, opening_amount: q("opening_amount").value.trim(), note: q("note").value.trim(),
```

## B7. `api/stock_suppliers.py` — ignore reversed supplier deposit events

These changes ensure that cancelling a sale containing a damaged-cylinder return reverses the supplier-side deposit forfeiture without deleting its audit row.

1. In `_held()`, change the SQL suffix:

```python
        "WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
```

to:

```python
        "WHERE cylinder_type_id=? AND supplier_id=? AND status='active'", (tid, sid)).fetchone()
```

2. Change the `totals` query from:

```python
    totals = {k: v for k, v in db.execute("SELECT kind, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits GROUP BY kind")}
```

to:

```python
    totals = {k: v for k, v in db.execute("SELECT kind, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits WHERE status='active' GROUP BY kind")}
```

3. In the `by_mode` query, change:

```python
        "SELECT received_in, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits WHERE kind='refunded' GROUP BY 1")}
```

to:

```python
        "SELECT received_in, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits WHERE kind='refunded' AND status='active' GROUP BY 1")}
```

4. In the `damaged` summary subquery, change:

```python
        "WHERE d.cylinder_type_id=c.id AND d.kind='cancelled'),0) AS lost FROM cylinder_types c "
```

to:

```python
        "WHERE d.cylinder_type_id=c.id AND d.kind='cancelled' AND d.status='active'),0) AS lost FROM cylinder_types c "
```

5. In the `damage_batches` query, change:

```python
        "WHERE d.kind='cancelled' AND c.active=1 "
```

to:

```python
        "WHERE d.kind='cancelled' AND d.status='active' AND c.active=1 "
```

6. In `damaged_send_back()`, find the event lookup:

```python
                "FROM cylinder_deposits d WHERE d.id=? AND d.kind='cancelled'",
```

Replace it with:

```python
                "FROM cylinder_deposits d WHERE d.id=? AND d.kind='cancelled' AND d.status='active'",
```

This prevents a reversed customer-damage event from being physically dispatched again through a stale or manually crafted API request.

## B8. `api/__init__.py` — register the real API, remove the mock

Find:

```python
from . import customers, dashboard, payments, suppliers, purchases, stock, stock_suppliers, mock_sales  # noqa: E402,F401
```

Replace with:

```python
from . import customers, dashboard, payments, suppliers, purchases, stock, stock_suppliers, sales, business  # noqa: E402,F401
```

## B9. `app.py` — add Invoice settings page

In `PAGES`, immediately after the `/sales` entry, add:

```python
    "/business": ("business.html", "sales", "Invoice settings", "Agency details printed on customer invoices"),
```

Do not remove the existing `/sales/new` redirect or `/sales/<sale_id>` detail route.

## B10. `templates/sales.html` — invoice settings, state and tax summary

### B10.1 Add an Invoice settings link
Inside the `div` with `id="sl-head-actions"`, immediately after its opening tag, add:

```html
    <a class="btn btn-white" href="/business">Invoice settings</a>
```

### B10.2 Replace the manual GST-rate input
Find the existing two-column block containing the `sn-gst` GST rate input and `sn-gst-amount` readonly input. Replace that entire block with:

```html
        <div class="two">
          <label class="field"><span>Place of supply state code</span><input class="input" id="sn-place-state" maxlength="2" inputmode="numeric" placeholder="State code"></label>
          <label class="field"><span>Reverse charge</span><select class="select" id="sn-reverse-charge"><option value="no">No</option><option value="yes">Yes</option></select></label>
        </div>
        <label class="field"><span>GST (calculated from each product's Stock &amp; Price settings)</span>
          <div class="pn-amount pn-readonly"><i>Rs</i><input class="input" id="sn-gst-amount" value="0.00" readonly></div>
          <small class="hint" id="sn-tax-split">CGST / SGST or IGST will appear here.</small>
        </label>
```

### B10.3 Add damaged-return supplier selector
Immediately before the existing `Note (optional)` label, add:

```html
        <label class="field" id="sn-damaged-supplier-wrap" hidden><span>Supplier for damaged cylinder return</span>
          <select class="select" id="sn-damaged-supplier"><option value="">Choose supplier</option></select>
          <small class="hint">The supplier-side security deposit for these damaged cylinders is forfeited.</small>
        </label>
        <p class="hint" id="sn-tax-warning" hidden></p>
```

### B10.4 Add refundable deposits to the totals
Inside `.pn-totals`, after the existing discount row and before the GST row, add:

```html
          <div id="sn-deposit-in-row" hidden><span>Refundable security deposit received</span><b id="sn-deposit-in-show">+ Rs 0</b></div>
```

Keep the existing `sn-back-row`; it shows a customer deposit refund.

## B11. `static/js/stock.js` — enter/edit and display HSN/GST

### B11.1 Show cylinder HSN under its name
Find this part of `cylinderCard()`:

```javascript
      '<span class="st-card-name">' + esc(c.name) + "</span>" + (c.low ? '<span class="st-low">LOW</span>' : "") + "</div>" +
```

Replace with:

```javascript
      '<span class="st-card-name">' + esc(c.name) + '</span>' +
      (c.hsn ? '<small class="st-card-hsn">HSN ' + esc(c.hsn) + (c.gst_rate == null ? '' : ' · GST ' + esc(c.gst_rate) + '%') + '</small>' : (c.gst_rate == null ? '' : '<small class="st-card-hsn">GST ' + esc(c.gst_rate) + '%</small>')) +
      (c.low ? '<span class="st-low">LOW</span>' : '') + "</div>" +
```

### B11.2 Show item HSN under its name
In `itemCard()`, find:

```javascript
      '<span><span class="st-card-name">' + esc(it.name) + '</span><br><span class="st-card-unit">Sold per ' + esc(it.unit) + "</span></span>" +
```

Replace with:

```javascript
      '<span><span class="st-card-name">' + esc(it.name) + '</span><br><span class="st-card-unit">Sold per ' + esc(it.unit) + "</span>" +
      (it.hsn ? '<small class="st-card-hsn">HSN ' + esc(it.hsn) + (it.gst_rate == null ? '' : ' · GST ' + esc(it.gst_rate) + '%') + '</small>' : (it.gst_rate == null ? '' : '<small class="st-card-hsn">GST ' + esc(it.gst_rate) + '%</small>')) + '</span>' +
```

### B11.3 Add HSN/GST inputs to Add cylinder
In `addCylinder()`, add these fields after the existing Security field:

```javascript
        { name: "hsn", label: "HSN / SAC code", kind: "text", placeholder: "Enter the code confirmed by your CA" },
        { name: "gst_rate", label: "GST rate (%)", kind: "text", placeholder: "e.g. 18" },
```

### B11.4 Add HSN/GST inputs to Add item
In `addItem()`, add these fields after the existing `purchase_price` field:

```javascript
        { name: "hsn", label: "HSN / SAC code", kind: "text", placeholder: "Enter the confirmed code" },
        { name: "gst_rate", label: "GST rate (%)", kind: "text", placeholder: "e.g. 18" },
```

### B11.5 Make cylinder HSN/GST editable later
In `edit(kind, id)`, inside the cylinder branch, replace its `fields` array with:

```javascript
        fields: [
          { name: "weight_kg", label: "Cylinder weight (kg)", kind: "qty", value: c.kg, required: true, suffix: "kg" },
          { name: "hsn", label: "HSN / SAC code", kind: "text", value: c.hsn || "" },
          { name: "gst_rate", label: "GST rate (%)", kind: "text", value: c.gst_rate == null ? "" : c.gst_rate },
        ],
```

### B11.6 Make catalogue-item HSN/GST editable later
In the item branch of `edit(kind, id)`, add these fields after the existing Unit field:

```javascript
          { name: "hsn", label: "HSN / SAC code", kind: "text", value: it.hsn || "" },
          { name: "gst_rate", label: "GST rate (%)", kind: "text", value: it.gst_rate == null ? "" : it.gst_rate },
```

## B12. `static/css/stock.css` — muted HSN label
Append:

```css
.st-card-hsn { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; font-weight: 500; }
```

## B13. `static/css/sales.css` — invoice layout and print styling
Append:

```css
/* v0.6 product tax details and invoice settings */
.sn-product-tax { display: block; margin-top: 2px; color: var(--muted); font-size: 9px; font-weight: 500; }
.sn-tax-warning { display: block; padding: 8px 10px; border-radius: 8px; background: #fff4e9; color: #98511e; font-size: 11px; }
.biz-card { max-width: 900px; padding: 22px; }
.biz-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }
.biz-wide { grid-column: 1 / -1; }
.biz-grid textarea { min-height: 76px; }
.form-actions { display: flex; justify-content: flex-end; margin-top: 16px; }
.rc-invoice-wrap { max-width: 960px; }
.rc-tax-invoice { padding: 26px 28px; border-radius: 4px; color: #20202a; }
.rc-invoice-head { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 14px; border-bottom: 1px solid #d7d7df; }
.rc-invoice-head p { margin: 4px 0; font-size: 11px; white-space: pre-line; }
.rc-doc-type { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; white-space: nowrap; }
.rc-doc-type strong { font-size: 16px; letter-spacing: .06em; }
.rc-doc-type small { color: var(--muted); font-size: 10px; }
.rc-invoice-meta { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; padding: 14px 0; border-bottom: 1px solid #d7d7df; }
.rc-invoice-meta div { display: flex; flex-direction: column; gap: 3px; }
.rc-invoice-meta span, .rc-bill-to > b { color: var(--muted); font-size: 10px; }
.rc-invoice-meta b { font-size: 11px; }
.rc-bill-to { display: grid; gap: 4px; padding: 13px 0; border-bottom: 1px solid #d7d7df; font-size: 11px; }
.rc-table-wrap { width: 100%; overflow-x: auto; }
.rc-invoice-table { min-width: 760px; }
.rc-invoice-table th { background: #f4f4f7; border-bottom: 1px solid #d7d7df; padding: 8px 5px; font-size: 9px; }
.rc-invoice-table td { border-bottom: 1px solid #ececf1; padding: 8px 5px; font-size: 10px; }
.rc-invoice-table .num { text-align: right; white-space: nowrap; }
.rc-info-line { color: #666; }
.rc-invoice-bottom { display: grid; grid-template-columns: minmax(0,1fr) minmax(260px,360px); gap: 20px; padding: 14px 0; }
.rc-tax-summary { font-size: 10px; }
.rc-tax-summary > b { display: block; margin-bottom: 7px; }
.rc-tax-summary div, .rc-sums div { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
.rc-tax-summary span, .rc-sums span { color: #666; }
.rc-sums { padding: 0; gap: 2px; font-size: 10px; }
.rc-total { border-top: 1px solid #aaa; margin-top: 5px; padding-top: 8px !important; font-size: 13px; }
.rc-negative b { color: #23804a; }
.rc-amount-words { padding: 9px 0; border-top: 1px solid #ddd; font-size: 10px; }
.rc-invoice-footer { display: grid; grid-template-columns: 1fr 220px; gap: 30px; padding-top: 18px; font-size: 10px; }
.rc-invoice-footer p { margin: 5px 0; white-space: pre-line; }
.rc-sign { display: flex; flex-direction: column; justify-content: flex-end; text-align: center; }
.rc-sign div { height: 48px; border-bottom: 1px solid #777; }
.rc-sign small { margin-top: 5px; color: #666; }
.rc-thanks { margin-top: 16px; }
@media (max-width: 700px) {
  .biz-grid { grid-template-columns: 1fr; }
  .biz-wide { grid-column: auto; }
  .rc-invoice-meta { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .rc-invoice-bottom, .rc-invoice-footer { grid-template-columns: 1fr; }
}
@page { size: A4 portrait; margin: 12mm; }
@media print {
  body * { visibility: hidden !important; }
  #rc-paper, #rc-paper * { visibility: visible !important; }
  .rc-screen-head, .rc-actions, .rc-banner { display: none !important; }
  #rc-paper { position: absolute !important; left: 0 !important; top: 0 !important; width: 100% !important; max-width: none !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important; overflow: visible !important; }
  .rc-wrap { max-width: none !important; margin: 0 !important; }
  .rc-table-wrap { overflow: visible !important; }
  .rc-invoice-table { min-width: 0 !important; width: 100% !important; }
  .rc-invoice-table th, .rc-invoice-table td { font-size: 8px !important; padding: 5px 3px !important; }
  .rc-invoice-table thead { display: table-header-group; }
  .rc-invoice-table tr { break-inside: avoid; }
  .rc-invoice-head, .rc-invoice-meta, .rc-bill-to, .rc-invoice-bottom, .rc-invoice-footer { break-inside: avoid; }
  .rc-stamp { position: fixed !important; }
}
```

## B14. Safeguards included in A2 (no extra edit)
The complete `api/sales.py` replacement in A2 already includes these safeguards:

- Duplicate cylinder or catalogue rows in one request are rejected so stock cannot be oversold by repeating an item.
- Non-zero GST cannot be charged when the agency GSTIN is absent. A zero-rate invoice remains possible, subject to CA confirmation; without a GSTIN the printout is labelled INVOICE, not TAX INVOICE.
- Reverse-charge invoices are blocked until the correct RCM tax and payment treatment is implemented and checked by the CA. The invoice form retains the Yes/No field so the required status is visible, but selecting Yes prevents finalization.
- A paid invoice or a payout invoice cannot be cancelled because this version has no refund/credit-note/cashbook workflow. Unpaid credit invoices can be cancelled and their stock/deposit ledgers reversed. A damaged cylinder already dispatched to the supplier also prevents cancellation.
- Customer deposit events are recorded even when the configured deposit is zero, so physical cylinder returns can still be reconciled.
- Before recording a supplier-side forfeiture for a customer-damaged cylinder, the backend verifies that the selected supplier still has enough active paid-deposit cylinder quantity for that size. It refuses to over-forfeit supplier deposits.

These restrictions are intentional accounting safeguards, not unfinished error handling.

## B15. `static/js/customer_detail.js` — route customer cylinder returns through Sales
The old Customer page Return empties modal updated stock without recording the customer's refundable deposit. Route that button through the new invoice flow instead, where the operator can record a good empty return and refund its deposit (or record a damaged return and forfeiture) together.

Find this exact function:

```javascript
  function returnEmpties() {
    Cust.openReturnEmpties({ customerId: c.id, customerName: c.name, held: cyl.held, onSaved: load });
  }
```

Replace it with:

```javascript
  function returnEmpties() {
    window.location.href = "/sales?tab=new&customer=" + c.id;
  }
```

Both Return empties buttons on the customer detail page use this function. The invoice screen will open with that customer selected; use its **Good empty in** row and, where applicable, **Refund customer security deposit** option. The old `openReturnEmpties` helper can remain in `customers_common.js`; no other screen uses it after this change.

---

# C. DELETE

Delete:

`api/mock_sales.py`

The real persistent implementation is now `api/sales.py`. `api/__init__.py` no longer imports the mock.

---

# D. APPLY ORDER AND VERIFY

1. Back up `data/agni.db`.
2. Apply A1–A8.
3. Apply B1–B15 in order.
4. Delete `api/mock_sales.py` in C.
5. Start the app once. `db.init_db()` applies additive migrations automatically.
6. Open **Sales → Invoice settings** and enter the agency's actual details. Enter its GSTIN only if registered; state code is required and must match the GSTIN prefix when provided.
7. Open **Stock & Price** and set the correct HSN/SAC and GST rate for every product the agency sells. Do not copy example codes or rates without supplier/CA verification.
8. Add or edit customer GSTIN, state code and billing address where applicable.
9. Test with a temporary customer and a product before using it for a real bill.

Run checks from `agni-gas/`:

```bash
node --check static/js/stock.js
node --check static/js/sales_new.js
node --check static/js/sale_detail.js
node --check static/js/business.js
python -m py_compile db.py api/util.py api/stock.py api/customers.py api/stock_suppliers.py api/business.py api/sales.py tests/test_sales_invoice.py
python -m unittest discover -s tests
```

## Expected manual checks

- Add a cylinder with HSN and GST rate; edit both later; verify the Stock & Price card shows the muted HSN/GST label.
- Create a refill invoice. Verify the invoice snapshots HSN and splits tax into CGST/SGST for the agency's state.
- Change the product HSN/GST rate. Reopen the old invoice: its old HSN/rate/tax must remain unchanged. A new invoice must use the updated values.
- Create a new-full-cylinder invoice: gas component is taxable; refundable security deposit is shown separately and excluded from GST.
- Return a good empty cylinder and refund its customer deposit. Verify customer-deposit events record the refund and supplier deposits remain unchanged.
- Return a damaged cylinder. Verify the customer's deposit is forfeited, damaged stock increases, and the supplier's own deposit is cancelled only for the selected supplier. Then use **Send damaged back**; it must not create a supplier refund.
- Cancel a sale before a damaged cylinder is dispatched. Verify stock/customer ledger/deposit events reverse and the supplier cancelled deposit is marked reversed. A sale whose damaged cylinder has already been dispatched is intentionally not cancellable.
- Print the invoice and check A4 layout, HSN/SAC, GST breakdown, deposits, customer details and agency details.

## Notes / limits

- The new integration tests are included, but the environment used to prepare this patch did not have Flask installed, so the Flask test suite was not executed here. Python compilation and JavaScript syntax checks were run; the API integration suite still needs to be executed in the project's virtual environment.
- Product tax values are deliberately not pre-filled. A missing HSN or GST rate blocks finalizing a taxable product line, so configure them first.
- The bill total includes refundable deposits because the customer pays them, but the invoice stores taxable value, GST and refundable deposits separately for accounting/reporting.
- Paid-invoice refunds/credit notes and cash/bank reconciliation are not implemented. Paid bills are therefore blocked from cancellation so the app cannot erase a real payment without recording its refund.
- Reverse-charge invoices are blocked rather than being incorrectly treated as ordinary forward-charge invoices.
- This patch does not create a full statutory returns/reporting module, e-invoice/IRN integration, e-way bill integration, or automatic tax advice. Have the agency's CA verify product classifications, tax rates, place-of-supply, reverse-charge applicability and invoice configuration before issuing real tax invoices.
