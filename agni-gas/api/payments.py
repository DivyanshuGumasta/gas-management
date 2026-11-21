"""Payments received from customers (udhaar recovery / advance)."""
from flask import jsonify, request

from db import get_db, next_number, transaction
from money import to_rupees

from . import api_bp
from .customers import customer_row
from .util import RECEIVED_IN, ApiError, body, day_field, int_field, money_field, text


def _dict(r):
    return {
        "id": r["id"], "number": r["number"], "customer_id": r["customer_id"],
        "customer": r["customer_name"], "amount": to_rupees(r["amount_paise"]),
        "date": r["payment_date"], "received_in": r["received_in"],
        "received_in_label": RECEIVED_IN.get(r["received_in"], r["received_in"]),
        "note": r["note"], "status": r["status"],
    }


PAY_SELECT = ("SELECT p.*, c.name AS customer_name FROM payments p "
              "JOIN customers c ON c.id = p.customer_id")


@api_bp.get("/payments")
def payments_list():
    where, params = " WHERE 1=1", []
    q = (request.args.get("q") or "").strip()
    if q:
        where += " AND (c.name LIKE ? OR p.number LIKE ? OR p.note LIKE ?)"
        params += [f"%{q}%"] * 3
    if request.args.get("customer_id"):
        where += " AND p.customer_id = ?"
        params.append(int_field(request.args["customer_id"], "Customer", minimum=1))
    if request.args.get("from"):
        where += " AND p.payment_date >= ?"
        params.append(request.args["from"])
    if request.args.get("to"):
        where += " AND p.payment_date <= ?"
        params.append(request.args["to"])
    rows = get_db().execute(
        PAY_SELECT + where + " ORDER BY p.payment_date DESC, p.id DESC LIMIT 500", params).fetchall()
    return jsonify([_dict(r) for r in rows])


@api_bp.post("/payments")
def payment_create():
    db = get_db()
    data = body()
    cid = int_field(data.get("customer_id"), "Customer", field="customer_id", minimum=1)
    customer_row(cid)
    amount = money_field(data, "amount", "Amount", allow_zero=False)
    day = day_field(data)
    mode = data.get("received_in", "cash")
    if mode not in RECEIVED_IN:
        raise ApiError("Choose where the money was received.", field="received_in")
    note = text(data, "note", "Note", max_len=200)

    with transaction(db):
        number = next_number(db, "payment", "R")
        pid = db.execute(
            "INSERT INTO payments (number, customer_id, amount_paise, payment_date, received_in, note)"
            " VALUES (?,?,?,?,?,?)", (number, cid, amount, day, mode, note)).lastrowid
    payment = _dict(db.execute(PAY_SELECT + " WHERE p.id = ?", (pid,)).fetchone())
    payment["balance"] = to_rupees(customer_row(cid)["balance"])
    return jsonify(payment), 201


@api_bp.post("/payments/<int:pid>/cancel")
def payment_cancel(pid):
    db = get_db()
    row = db.execute("SELECT id, status FROM payments WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise ApiError("Payment not found.", 404)
    if row["status"] == "cancelled":
        raise ApiError("This payment is already cancelled.", 409)
    with transaction(db):
        db.execute("UPDATE payments SET status = 'cancelled' WHERE id = ?", (pid,))
    return jsonify(_dict(db.execute(PAY_SELECT + " WHERE p.id = ?", (pid,)).fetchone()))
