# """GET /api/suppliers (Select supplier modal; the full Supplier screen comes with
# the Purchase + Supplier merge). Balance: + = we owe them (To pay), - = advance."""
# from flask import jsonify, request

# from db import get_db
# from money import to_rupees

# from . import api_bp

# @api_bp.get("/suppliers")
# def suppliers():
#     q = (request.args.get("q") or "").strip()
#     where, params = "", []
#     if q:
#         where = " AND (name LIKE ? OR phone LIKE ? OR address LIKE ?)"
#         params = [f"%{q}%"] * 3
#     # TODO(purchases): balance = opening + purchases - payments to supplier.
#     rows = get_db().execute(
#         "SELECT id, name, gstin, phone, address, opening_balance_paise AS balance "
#         "FROM suppliers WHERE active = 1" + where + " ORDER BY name COLLATE NOCASE",
#         params,
#     ).fetchall()
#     return jsonify(
#         [
#             {
#                 "id": r["id"],
#                 "name": r["name"],
#                 "gstin": r["gstin"],
#                 "phone": r["phone"],
#                 "address": r["address"],
#                 "type_label": "Supplier",
#                 "balance": to_rupees(r["balance"]),
#             }
#             for r in rows
#         ]
#     )
