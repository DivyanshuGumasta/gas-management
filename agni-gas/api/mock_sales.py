# """TEMPORARY fake Sales API so the Sales screens can be reviewed before the real backend exists.

# Keeps sales in memory only (gone when the app closes) and NEVER changes stock or customer balances.
# It reads the real customers and cylinder sizes. Delete this file (and `mock_sales` in api/__init__.py)
# when the real Sales backend is added. Same URLs and JSON as SALES_API_CONTRACT.md.
# """
# from datetime import date, datetime, timedelta
# from decimal import Decimal, ROUND_HALF_UP

# from flask import jsonify, request

# from db import get_db
# from money import to_paise, to_rupees
# from . import api_bp
# from .util import ApiError, body

# _SALES = []
# _NEXT = [1]


# def _p(v):
#     return to_paise(v) if v not in (None, "") else 0


# def _label(lines):
#     parts = []
#     for ln in lines:
#         n = ln["qty"]
#         if ln["kind"] in ("refill", "new_full"):
#             parts.append(f"{n} x {ln['name']}")
#         elif ln["kind"] == "item":
#             parts.append(f"{n} {ln['name']}")
#     if not parts:
#         return "Empty returned, deposit given back" if any(ln["kind"] == "deposit_back" for ln in lines) else "Empty cylinders only"
#     return " · ".join(parts)


# def _add(customer, lines, day, hhmm, discount, gst_pct, status_pay, paid, received_in, note):
#     back = sum(-ln["amount_paise"] for ln in lines if ln["kind"] == "deposit_back")      # deposit handed back (stored negative)
#     subtotal = sum(ln["amount_paise"] for ln in lines if ln["kind"] != "deposit_back")
#     discount = min(discount, subtotal)
#     gst = int((Decimal(subtotal - discount) * Decimal(str(gst_pct)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
#     total = subtotal - discount + gst - back
#     paid = total if (status_pay == "paid" or total <= 0) else (0 if status_pay == "credit" else paid)
#     sid = _NEXT[0]
#     _NEXT[0] += 1
#     sale = {"id": sid, "number": f"S-{sid:05d}", "date": day, "time": hhmm, "customer": customer, "lines": lines,
#             "subtotal": subtotal, "deposit_back": back, "discount": discount, "gst_percent": gst_pct, "gst": gst, "total": total, "paid": paid,
#             "received_in": received_in, "note": note, "cancelled": False}
#     _SALES.append(sale)
#     return sale


# def _status(s):
#     if s["cancelled"]:
#         return "cancelled"
#     if s["paid"] >= s["total"]:
#         return "paid"
#     return "udhaar" if s["paid"] == 0 else "partial"


# def _row(s):
#     cyl = sum(ln["qty"] for ln in s["lines"] if ln["kind"] in ("refill", "new_full"))
#     return {"id": s["id"], "number": s["number"], "date": s["date"], "time": s["time"],
#             "customer": s["customer"]["name"] if s["customer"] else "Walk-in customer",
#             "customer_id": s["customer"]["id"] if s["customer"] else None,
#             "label": _label(s["lines"]), "cylinders": cyl, "total": to_rupees(s["total"]),
#             "due": to_rupees(max(0, s["total"] - s["paid"])), "status": _status(s)}


# def _seed():
#     if _SALES:
#         return
#     db = get_db()
#     ct = db.execute("SELECT id, name, sale_price_paise FROM cylinder_types WHERE active=1 ORDER BY sort_order LIMIT 3").fetchall()
#     cust = db.execute("SELECT id, name, phone FROM customers WHERE active=1 ORDER BY id LIMIT 2").fetchall()
#     today, y = date.today().isoformat(), (date.today() - timedelta(days=2)).isoformat()
#     if ct:
#         c = ct[-1]
#         _add(None, [{"kind": "refill", "name": c["name"], "qty": 1, "rate_paise": c["sale_price_paise"], "amount_paise": c["sale_price_paise"]}],
#              today, "10:23 AM", 0, 0, "paid", 0, "cash", None)
#     if ct and cust:
#         c = ct[0]
#         amt = 2 * c["sale_price_paise"]
#         _add({"id": cust[0]["id"], "name": cust[0]["name"], "phone": cust[0]["phone"]},
#              [{"kind": "refill", "name": c["name"], "qty": 2, "rate_paise": c["sale_price_paise"], "amount_paise": amt}],
#              y, "04:05 PM", 0, 0, "credit", 0, "cash", "Will pay on Friday")


# @api_bp.get("/sales")
# def sales_list():
#     _seed()
#     f, t = request.args.get("from"), request.args.get("to")
#     q = (request.args.get("q") or "").strip().lower()
#     out = [s for s in _SALES if (not f or s["date"] >= f) and (not t or s["date"] <= t)]
#     if q:
#         out = [s for s in out if q in s["number"].lower() or q in (s["customer"]["name"].lower() if s["customer"] else "walk-in customer")]
#     out.sort(key=lambda s: (s["date"], s["id"]), reverse=True)
#     live = [s for s in out if not s["cancelled"]]
#     return jsonify({
#         "summary": {"total": to_rupees(sum(s["total"] for s in live)), "bills": len(live),
#                     "cylinders": sum(sum(ln["qty"] for ln in s["lines"] if ln["kind"] in ("refill", "new_full")) for s in live),
#                     "udhaar": to_rupees(sum(max(0, s["total"] - s["paid"]) for s in live))},
#         "sales": [_row(s) for s in out]})


# def _find(sid):
#     _seed()
#     for s in _SALES:
#         if s["id"] == sid:
#             return s
#     raise ApiError("Sale not found.", 404)


# @api_bp.get("/sales/<int:sid>")
# def sale_get(sid):
#     s = _find(sid)
#     return jsonify({
#         "id": s["id"], "number": s["number"], "date": s["date"], "time": s["time"], "status": _status(s),
#         "customer": s["customer"], "note": s["note"],
#         "lines": [{"kind": ln["kind"], "name": ln["name"], "qty": ln["qty"], "rate": to_rupees(ln["rate_paise"]),
#                    "amount": to_rupees(ln["amount_paise"]), "detail": ln.get("detail")} for ln in s["lines"]],
#         "subtotal": to_rupees(s["subtotal"]), "deposit_back": to_rupees(s["deposit_back"]), "discount": to_rupees(s["discount"]), "gst_percent": s["gst_percent"],
#         "gst": to_rupees(s["gst"]), "total": to_rupees(s["total"]), "paid": to_rupees(s["paid"]),
#         "due": to_rupees(max(0, s["total"] - s["paid"])), "received_in": s["received_in"]})


# @api_bp.post("/sales/<int:sid>/cancel")
# def sale_cancel(sid):
#     s = _find(sid)
#     if s["cancelled"]:
#         raise ApiError("This bill is already cancelled.", 409)
#     s["cancelled"] = True
#     return jsonify({"ok": True})


# @api_bp.post("/sales")
# def sale_create():
#     _seed()
#     data = body()
#     db = get_db()
#     customer = None
#     if data.get("customer_id") not in (None, ""):
#         c = db.execute("SELECT id, name, phone FROM customers WHERE id=? AND active=1", (data["customer_id"],)).fetchone()
#         if not c:
#             raise ApiError("Customer not found.", 404)
#         customer = {"id": c["id"], "name": c["name"], "phone": c["phone"]}
#     lines = []
#     for ln in data.get("lines") or []:
#         c = db.execute("SELECT * FROM cylinder_types WHERE id=? AND active=1", (ln.get("cylinder_type_id"),)).fetchone()
#         if not c:
#             raise ApiError("Unknown cylinder size.", 404)
#         n = {k: int(ln.get(k) or 0) for k in ("refill", "new_full", "new_empty", "empty_in")}
#         rate, dep = _p(ln.get("rate")), _p(ln.get("security"))
#         if n["refill"] + n["new_full"] > c["full_qty"]:
#             raise ApiError(f"{c['name']}: only {c['full_qty']} full cylinder(s) in stock.", 409)
#         if n["refill"]:
#             lines.append({"kind": "refill", "name": c["name"], "qty": n["refill"], "rate_paise": rate, "amount_paise": n["refill"] * rate, "detail": "Refill"})
#         if n["new_full"]:
#             lines.append({"kind": "new_full", "name": c["name"], "qty": n["new_full"], "rate_paise": rate + dep,
#                           "amount_paise": n["new_full"] * (rate + dep), "detail": "New full cylinder (gas + deposit)"})
#         if n["new_empty"]:
#             lines.append({"kind": "new_empty", "name": c["name"], "qty": n["new_empty"], "rate_paise": dep,
#                           "amount_paise": n["new_empty"] * dep, "detail": "Empty cylinder (deposit only)"})
#         if n["empty_in"]:
#             lines.append({"kind": "empty_in", "name": c["name"], "qty": n["empty_in"], "rate_paise": 0, "amount_paise": 0, "detail": "Empty received"})
#             if ln.get("deposit_back"):
#                 if not customer:
#                     raise ApiError("Select a customer to give the deposit back.", field="deposit_back")
#                 each = _p(ln.get("deposit_each"))
#                 lines.append({"kind": "deposit_back", "name": c["name"], "qty": n["empty_in"], "rate_paise": each,
#                               "amount_paise": -n["empty_in"] * each, "detail": "Deposit given back"})
#     for it in data.get("items") or []:
#         row = db.execute("SELECT * FROM catalog_items WHERE id=? AND active=1", (it.get("item_id"),)).fetchone()
#         if not row:
#             raise ApiError("Unknown item.", 404)
#         qty = Decimal(str(it.get("qty") or 0))
#         rate = _p(it.get("rate"))
#         if qty * 1000 > row["stock_qty_milli"]:
#             raise ApiError(f"{row['name']}: not enough in stock.", 409)
#         lines.append({"kind": "item", "name": row["name"], "qty": float(qty) if qty % 1 else int(qty), "rate_paise": rate,
#                       "amount_paise": int((qty * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), "detail": row["unit"]})
#     if not any(ln["amount_paise"] or ln["kind"] == "empty_in" for ln in lines):
#         raise ApiError("Add at least one cylinder or item.")
#     mode = data.get("payment") or "paid"
#     if mode not in ("paid", "partial", "credit"):
#         raise ApiError("Choose how it was paid.", field="payment")
#     if mode != "paid" and not customer:
#         raise ApiError("Walk-in sales are cash only. Select a customer to give udhaar.", field="payment")
#     received = data.get("received_in") or "cash"
#     if received not in ("cash", "bank"):
#         raise ApiError("Choose where the money was received.", field="received_in")
#     discount = _p(data.get("discount"))
#     gst_pct = float(data.get("gst_percent") or 0)
#     if not 0 <= gst_pct <= 100:
#         raise ApiError("GST must be between 0 and 100.", field="gst_percent")
#     now = datetime.now()
#     s = _add(customer, lines, data.get("date") or date.today().isoformat(), now.strftime("%I:%M %p"), discount, gst_pct,
#              mode, _p(data.get("paid")), received, (data.get("note") or "").strip() or None)
#     if mode == "partial" and not 0 < s["paid"] < s["total"]:
#         _SALES.remove(s)
#         raise ApiError("Amount paid now must be more than 0 and less than the total.", field="paid")
#     return jsonify({"id": s["id"], "number": s["number"]}), 201