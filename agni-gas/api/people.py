"""GET /api/customers and /api/suppliers (used by the Select modals, and later
by the Customers / Suppliers screens).

Balance sign: for customers  + = they owe us (To receive),  - = paid extra.
              for suppliers  + = we owe them (To pay),      - = advance.
"""
from flask import jsonify, request

from db import get_db
from money import to_rupees

from . import api_bp

CUSTOMER_SQL = """
SELECT c.id, c.name, c.phone, c.address, c.type,
       c.opening_balance_paise
         + COALESCE((SELECT SUM(s.total_paise - s.paid_paise) FROM sales s
                     WHERE s.customer_id = c.id AND s.status = 'active'), 0)
         - COALESCE((SELECT SUM(p.amount_paise) FROM payments p
                     WHERE p.customer_id = c.id AND p.status = 'active'), 0) AS balance
FROM customers c
WHERE c.active = 1 {where}
ORDER BY c.name COLLATE NOCASE
"""


@api_bp.get("/customers")
def customers():
    q = (request.args.get("q") or "").strip()
    ctype = request.args.get("type")
    where, params = "", []
    if q:
        where += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.address LIKE ?)"
        params += [f"%{q}%"] * 3
    if ctype in ("retail", "wholesale"):
        where += " AND c.type = ?"
        params.append(ctype)

    rows = get_db().execute(CUSTOMER_SQL.format(where=where), params).fetchall()
    if request.args.get("owing") == "1":
        rows = [r for r in rows if r["balance"] > 0]

    return jsonify(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "phone": r["phone"],
                "address": r["address"],
                "type": r["type"],
                "type_label": r["type"].capitalize(),
                "balance": to_rupees(r["balance"]),
            }
            for r in rows
        ]
    )


@api_bp.get("/suppliers")
def suppliers():
    q = (request.args.get("q") or "").strip()
    where, params = "", []
    if q:
        where = " AND (name LIKE ? OR phone LIKE ? OR address LIKE ?)"
        params = [f"%{q}%"] * 3
    # TODO(purchases): balance = opening + purchases - payments to supplier.
    rows = get_db().execute(
        "SELECT id, name, gstin, phone, address, opening_balance_paise AS balance "
        "FROM suppliers WHERE active = 1" + where + " ORDER BY name COLLATE NOCASE",
        params,
    ).fetchall()
    return jsonify(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "gstin": r["gstin"],
                "phone": r["phone"],
                "address": r["address"],
                "type_label": "Supplier",
                "balance": to_rupees(r["balance"]),
            }
            for r in rows
        ]
    )
