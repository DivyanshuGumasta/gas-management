# """Supplier records, supplier ledger, payments, and supplier-specific item prices.

# Supplier balance sign: positive = payable to supplier; negative = supplier advance.
# Balance = opening + active purchases - active supplier payments.
# """
# import re

# from flask import jsonify, request

# from db import get_db, next_number, transaction
# from money import format_inr, to_rupees

# from . import api_bp
# from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, phone_field, text

# SUPPLIER_SELECT = """SELECT s.*,
#     s.opening_balance_paise
#       + COALESCE((SELECT SUM(p.total_paise) FROM purchases p
#                   WHERE p.supplier_id = s.id AND p.status = 'active'), 0)
#       - COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
#                   WHERE sp.supplier_id = s.id AND sp.status = 'active'), 0) AS balance,
#     COALESCE((SELECT SUM(p.total_paise) FROM purchases p
#               WHERE p.supplier_id = s.id AND p.status = 'active'), 0) AS total_purchases_paise,
#     COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
#               WHERE sp.supplier_id = s.id AND sp.status = 'active'), 0) AS total_paid_paise,
#     (SELECT COUNT(*) FROM purchases p WHERE p.supplier_id = s.id AND p.status = 'active') AS purchase_count,
#     (SELECT MAX(p.purchase_date) FROM purchases p
#       WHERE p.supplier_id = s.id AND p.status = 'active') AS last_purchase
#     FROM suppliers s"""


# def supplier_row(sid, include_inactive=False):
#     sql = SUPPLIER_SELECT + " WHERE s.id = ?" + ("" if include_inactive else " AND s.active = 1")
#     row = get_db().execute(sql, (sid,)).fetchone()
#     if not row:
#         raise ApiError("Supplier not found.", 404)
#     return row


# def _dict(r):
#     return {
#         "id": r["id"], "name": r["name"], "gstin": r["gstin"],
#         "phone": r["phone"], "address": r["address"], "note": r["note"],
#         "opening_balance": to_rupees(r["opening_balance_paise"]),
#         "balance": to_rupees(r["balance"]),
#         "total_purchases": to_rupees(r["total_purchases_paise"]),
#         "total_paid": to_rupees(r["total_paid_paise"]),
#         "purchase_count": r["purchase_count"], "last_purchase": r["last_purchase"],
#         "type_label": "Supplier", "active": bool(r["active"]),
#         "created_at": r["created_at"],
#     }


# def _parse_supplier(data, self_id=None):
#     name = text(data, "name", "Supplier name", required=True, max_len=100)
#     gstin = (text(data, "gstin", "GST number", required=True, max_len=15) or "").upper()
#     # GSTIN structure: state code + PAN + entity number + Z + checksum character.
#     if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
#         raise ApiError("Enter a valid 15-character GSTIN.", field="gstin")
#     phone = phone_field(data)
#     opening_type = data.get("opening_type", "payable")
#     if opening_type not in ("payable", "advance"):
#         raise ApiError("Choose Payable or Advance.", field="opening_type")
#     opening_amount = money_field(data, "opening_amount", "Previous balance")
#     duplicate = get_db().execute(
#         "SELECT id FROM suppliers WHERE active = 1 AND gstin = ? AND id IS NOT ?",
#         (gstin, self_id),
#     ).fetchone()
#     if duplicate:
#         raise ApiError("A supplier with this GSTIN already exists.", 409, field="gstin")
#     return {
#         "name": name, "gstin": gstin, "phone": phone,
#         "address": text(data, "address", "Address", max_len=250),
#         "note": text(data, "note", "Note", max_len=500),
#         "opening": opening_amount if opening_type == "payable" else -opening_amount,
#     }


# @api_bp.get("/suppliers")
# def suppliers_list():
#     q = (request.args.get("q") or "").strip()
#     where, params = " WHERE s.active = 1", []
#     if q:
#         where += " AND (s.name LIKE ? OR s.gstin LIKE ? OR s.phone LIKE ? OR s.address LIKE ?)"
#         params += [f"%{q}%"] * 4
#     rows = get_db().execute(SUPPLIER_SELECT + where + " ORDER BY s.name COLLATE NOCASE", params).fetchall()
#     return jsonify([_dict(r) for r in rows])


# @api_bp.get("/suppliers/summary")
# def suppliers_summary():
#     db = get_db()
#     row = db.execute(
#         "SELECT COUNT(*) AS count, COALESCE(SUM(CASE WHEN balance > 0 THEN balance ELSE 0 END),0) AS payable, "
#         "COALESCE(SUM(CASE WHEN balance < 0 THEN -balance ELSE 0 END),0) AS advance FROM (" +
#         SUPPLIER_SELECT + " WHERE s.active = 1)"
#     ).fetchone()
#     return jsonify({"supplier_count": row["count"], "payable": to_rupees(row["payable"]),
#                     "advance": to_rupees(row["advance"])})


# @api_bp.post("/suppliers")
# def supplier_create():
#     f = _parse_supplier(body())
#     db = get_db()
#     with transaction(db):
#         sid = db.execute(
#             "INSERT INTO suppliers (name,gstin,phone,address,opening_balance_paise,note) VALUES (?,?,?,?,?,?)",
#             (f["name"], f["gstin"], f["phone"], f["address"], f["opening"], f["note"]),
#         ).lastrowid
#     return jsonify(_dict(supplier_row(sid))), 201


# @api_bp.get("/suppliers/<int:sid>")
# def supplier_get(sid):
#     return jsonify(_dict(supplier_row(sid)))


# @api_bp.put("/suppliers/<int:sid>")
# def supplier_update(sid):
#     supplier_row(sid)
#     f = _parse_supplier(body(), self_id=sid)
#     db = get_db()
#     with transaction(db):
#         db.execute(
#             "UPDATE suppliers SET name=?,gstin=?,phone=?,address=?,opening_balance_paise=?,note=? WHERE id=?",
#             (f["name"], f["gstin"], f["phone"], f["address"], f["opening"], f["note"], sid),
#         )
#     return jsonify(_dict(supplier_row(sid)))


# @api_bp.delete("/suppliers/<int:sid>")
# def supplier_delete(sid):
#     """Archive a supplier. History is retained; outstanding balances must be settled first."""
#     db = get_db()
#     with transaction(db):
#         s = supplier_row(sid)
#         if s["balance"] != 0:
#             raise ApiError(f"{s['name']} has an unsettled balance of {format_inr(s['balance'])}.", 409)
#         db.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (sid,))
#     return jsonify({"ok": True})


# @api_bp.get("/suppliers/<int:sid>/ledger")
# def supplier_ledger(sid):
#     db = get_db()
#     s = supplier_row(sid, include_inactive=True)
#     opening = s["opening_balance_paise"]
#     events = []
#     for p in db.execute(
#         "SELECT id,number,purchase_date,created_at,total_paise,note,status FROM purchases "
#         "WHERE supplier_id=? ORDER BY purchase_date,created_at,id", (sid,)
#     ):
#         cylinder_summary = db.execute(
#             "SELECT GROUP_CONCAT(qty_label, ' · ') FROM ("
#             " SELECT CAST(pi.full_in_qty AS TEXT) || ' × ' || ct.name AS qty_label "
#             " FROM purchase_items pi JOIN cylinder_types ct ON ct.id=pi.cylinder_type_id "
#             " WHERE pi.purchase_id=? AND pi.full_in_qty>0 ORDER BY pi.id)", (p["id"],)
#         ).fetchone()[0]
#         other_summary = db.execute(
#             "SELECT GROUP_CONCAT(label, ' · ') FROM (SELECT printf('%g',quantity_milli/1000.0) || ' ' || "
#             "item_name AS label FROM purchase_catalog_items WHERE purchase_id=? ORDER BY id)", (p["id"],)
#         ).fetchone()[0]
#         summary = " · ".join(part for part in (cylinder_summary, other_summary) if part)
#         events.append(((p["purchase_date"], p["created_at"], 0, p["id"]), {
#             "kind": "purchase", "id": p["id"], "date": p["purchase_date"],
#             "detail": f"Purchase {p['number']}", "sub": summary or p["note"],
#             "purchase": to_rupees(p["total_paise"]), "paid": None,
#             "status": p["status"], "delta": p["total_paise"],
#         }))
#     for p in db.execute(
#         "SELECT sp.id,sp.number,sp.payment_date,sp.created_at,sp.amount_paise,sp.paid_from,sp.note,sp.status,"
#         "pu.number AS purchase_number FROM supplier_payments sp "
#         "LEFT JOIN purchases pu ON pu.id=sp.purchase_id WHERE sp.supplier_id=?", (sid,)
#     ):
#         sub = ("Cash in hand" if p["paid_from"] == "cash" else "Bank / UPI")
#         if p["purchase_number"]:
#             sub += " · " + p["purchase_number"]
#         if p["note"]:
#             sub += " · " + p["note"]
#         events.append(((p["payment_date"], p["created_at"], 1, p["id"]), {
#             "kind": "payment", "id": p["id"], "date": p["payment_date"],
#             "detail": f"Paid to supplier {p['number']}", "sub": sub,
#             "purchase": None, "paid": to_rupees(p["amount_paise"]),
#             "status": p["status"], "delta": -p["amount_paise"],
#         }))

#     rows = [{"kind": "opening", "id": None, "date": None, "detail": "Opening balance", "sub": None,
#              "purchase": to_rupees(opening) if opening > 0 else None,
#              "paid": to_rupees(-opening) if opening < 0 else None,
#              "balance": to_rupees(opening), "status": "active"}]
#     running = opening
#     for _, e in sorted(events, key=lambda item: item[0]):
#         if e["status"] == "active":
#             running += e["delta"]
#         e["balance"] = to_rupees(running)
#         del e["delta"]
#         rows.append(e)
#     return jsonify({"rows": rows, "closing_balance": to_rupees(running)})


# @api_bp.get("/suppliers/<int:sid>/items")
# def supplier_items_get(sid):
#     """Return only cylinder types currently supplied by this supplier."""
#     supplier_row(sid, include_inactive=True)
#     rows = get_db().execute(
#         "SELECT ct.id,ct.name,ct.purchase_price_paise AS default_price,ct.security_paise,"
#         "si.purchase_price_paise AS supplier_price "
#         "FROM supplier_items si JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
#         "WHERE si.supplier_id=? AND ct.active=1 ORDER BY ct.sort_order,ct.id", (sid,)
#     ).fetchall()
#     return jsonify([_supplier_cylinder_dict(row) for row in rows])


# def _supplier_cylinder_dict(row):
#     return {
#         "cylinder_type_id": row["id"],
#         "name": row["name"],
#         "purchase_price": to_rupees(row["supplier_price"]),
#         "default_purchase_price": to_rupees(row["default_price"]),
#         "security_price": to_rupees(row["security_paise"]),
#     }


# @api_bp.get("/suppliers/<int:sid>/available-cylinders")
# def supplier_available_cylinders(sid):
#     """Active cylinder types not yet linked to this supplier."""
#     supplier_row(sid)
#     rows = get_db().execute(
#         "SELECT ct.id,ct.name,ct.purchase_price_paise AS default_price,ct.security_paise "
#         "FROM cylinder_types ct LEFT JOIN supplier_items si "
#         "ON si.cylinder_type_id=ct.id AND si.supplier_id=? "
#         "WHERE ct.active=1 AND si.supplier_id IS NULL ORDER BY ct.sort_order,ct.id", (sid,)
#     ).fetchall()
#     return jsonify([{
#         "cylinder_type_id": row["id"],
#         "name": row["name"],
#         "purchase_price": to_rupees(row["default_price"]),
#         "security_price": to_rupees(row["security_paise"]),
#     } for row in rows])


# @api_bp.post("/suppliers/<int:sid>/items")
# def supplier_cylinder_link(sid):
#     """Link one existing Stock & Price cylinder type to this supplier."""
#     supplier_row(sid)
#     data = body()
#     tid = int_field(data.get("cylinder_type_id"), "Cylinder size", minimum=1)
#     db = get_db()
#     cylinder = db.execute(
#         "SELECT id,name,purchase_price_paise FROM cylinder_types WHERE id=? AND active=1", (tid,)
#     ).fetchone()
#     if not cylinder:
#         raise ApiError("Cylinder size not found in Stock & Price.", 404, field="cylinder_type_id")
#     raw_price = data.get("purchase_price")
#     price = (money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
#              if raw_price not in (None, "") else cylinder["purchase_price_paise"])
#     with transaction(db):
#         db.execute(
#             "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
#             "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
#             (sid, tid, price),
#         )
#     row = db.execute(
#         "SELECT ct.id,ct.name,ct.purchase_price_paise AS default_price,ct.security_paise,"
#         "si.purchase_price_paise AS supplier_price FROM supplier_items si "
#         "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
#         "WHERE si.supplier_id=? AND si.cylinder_type_id=?", (sid, tid)
#     ).fetchone()
#     return jsonify(_supplier_cylinder_dict(row)), 201


# @api_bp.put("/suppliers/<int:sid>/items/<int:tid>")
# def supplier_cylinder_price_update(sid, tid):
#     """Update only the rate this supplier charges for this cylinder type."""
#     supplier_row(sid)
#     db = get_db()
#     linked = db.execute(
#         "SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)
#     ).fetchone()
#     if not linked:
#         raise ApiError("This cylinder size is not linked to this supplier.", 404)
#     price = money_field(body(), "purchase_price", "Supplier purchase price", allow_zero=False)
#     with transaction(db):
#         db.execute(
#             "UPDATE supplier_items SET purchase_price_paise=? WHERE supplier_id=? AND cylinder_type_id=?",
#             (price, sid, tid),
#         )
#     row = db.execute(
#         "SELECT ct.id,ct.name,ct.purchase_price_paise AS default_price,ct.security_paise,"
#         "si.purchase_price_paise AS supplier_price FROM supplier_items si "
#         "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
#         "WHERE si.supplier_id=? AND si.cylinder_type_id=?", (sid, tid)
#     ).fetchone()
#     return jsonify(_supplier_cylinder_dict(row))


# @api_bp.delete("/suppliers/<int:sid>/items/<int:tid>")
# def supplier_cylinder_unlink(sid, tid):
#     """Stop offering this cylinder to the supplier without touching history or stock."""
#     supplier_row(sid)
#     db = get_db()
#     with transaction(db):
#         changed = db.execute(
#             "DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)
#         ).rowcount
#         if not changed:
#             raise ApiError("This cylinder size is not linked to this supplier.", 404)
#     return jsonify({"ok": True})


# # Backwards-compatible bulk endpoint. New UI uses the item-specific add/edit/remove routes above.
# @api_bp.put("/suppliers/<int:sid>/items")
# def supplier_items_save(sid):
#     supplier_row(sid)
#     items = body().get("items")
#     if not isinstance(items, list):
#         raise ApiError("Send the supplier's item list.")
#     db = get_db()
#     valid = {r["id"] for r in db.execute("SELECT id FROM cylinder_types WHERE active=1")}
#     parsed, seen = [], set()
#     for item in items:
#         if not isinstance(item, dict):
#             raise ApiError("Invalid item entry.")
#         tid = int_field(item.get("cylinder_type_id"), "Cylinder type", minimum=1)
#         if tid not in valid or tid in seen:
#             raise ApiError("Unknown or duplicate cylinder type.", 409)
#         seen.add(tid)
#         enabled = bool(item.get("supplied"))
#         price = money_field(item, "purchase_price", "Purchase price", allow_zero=False) if enabled else None
#         parsed.append((tid, enabled, price))
#     with transaction(db):
#         for tid, enabled, price in parsed:
#             if enabled:
#                 db.execute(
#                     "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
#                     "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
#                     (sid, tid, price),
#                 )
#             else:
#                 db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
#     return jsonify(supplier_items_get_data(db, sid))


# def supplier_items_get_data(db, sid):
#     rows = db.execute(
#         "SELECT ct.id,ct.name,ct.purchase_price_paise AS default_price,ct.security_paise,"
#         "si.purchase_price_paise AS supplier_price FROM supplier_items si "
#         "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
#         "WHERE si.supplier_id=? AND ct.active=1 ORDER BY ct.sort_order,ct.id", (sid,)
#     ).fetchall()
#     return [_supplier_cylinder_dict(row) for row in rows]


# @api_bp.post("/suppliers/<int:sid>/payments")
# def supplier_payment_create(sid):
#     data = body()
#     amount = money_field(data, "amount", "Amount", allow_zero=False)
#     day = day_field(data)
#     paid_from = data.get("paid_from", "cash")
#     if paid_from not in RECEIVED_IN:
#         raise ApiError("Choose Cash in hand or Bank / UPI.", field="paid_from")
#     note = text(data, "note", "Note", max_len=200)
#     purchase_id = data.get("purchase_id")
#     if purchase_id not in (None, ""):
#         purchase_id = int_field(purchase_id, "Purchase", minimum=1)
#     else:
#         purchase_id = None

#     db = get_db()
#     with transaction(db):
#         # Validate under the write lock so concurrent requests cannot overpay
#         # the same purchase if this API is hosted for multiple devices later.
#         supplier_row(sid)
#         if purchase_id is not None:
#             row = db.execute(
#                 "SELECT p.supplier_id,p.total_paise-COALESCE((SELECT SUM(sp.amount_paise) "
#                 "FROM supplier_payments sp WHERE sp.purchase_id=p.id AND sp.status='active'),0) AS due_paise "
#                 "FROM purchases p WHERE p.id=? AND p.status='active'", (purchase_id,)
#             ).fetchone()
#             if not row or row["supplier_id"] != sid:
#                 raise ApiError("This purchase does not belong to the selected supplier.", 409, field="purchase_id")
#             if amount > row["due_paise"]:
#                 raise ApiError("Payment cannot exceed the remaining balance of this purchase. Use a general supplier payment for an advance.", 409, field="amount")
#         number = next_number(db, "supplier_payment", "SP")
#         pid = db.execute(
#             "INSERT INTO supplier_payments(number,supplier_id,purchase_id,amount_paise,payment_date,paid_from,note) "
#             "VALUES(?,?,?,?,?,?,?)", (number,sid,purchase_id,amount,day,paid_from,note)
#         ).lastrowid
#     r = db.execute("SELECT * FROM supplier_payments WHERE id=?", (pid,)).fetchone()
#     return jsonify({"id": r["id"], "number": r["number"], "supplier_id": sid,
#                     "purchase_id": r["purchase_id"], "amount": to_rupees(r["amount_paise"]),
#                     "date": r["payment_date"], "paid_from": r["paid_from"], "note": r["note"],
#                     "balance": to_rupees(supplier_row(sid)["balance"])}), 201


# @api_bp.post("/supplier-payments/<int:pid>/cancel")
# def supplier_payment_cancel(pid):
#     db = get_db()
#     row = db.execute("SELECT id,status FROM supplier_payments WHERE id=?", (pid,)).fetchone()
#     if not row:
#         raise ApiError("Supplier payment not found.", 404)
#     if row["status"] == "cancelled":
#         raise ApiError("This payment is already cancelled.", 409)
#     with transaction(db):
#         db.execute("UPDATE supplier_payments SET status='cancelled' WHERE id=?", (pid,))
#     return jsonify({"ok": True})

# # ---------------------------------------------------------------- general catalogue items (non-cylinder goods)
# def _catalog_item_dict(row, supplier_price=None):
#     stock_milli = row["stock_qty_milli"]
#     from .util import quantity_from_milli
#     price = row["purchase_price_paise"] if supplier_price is None else supplier_price
#     return {
#         "id": row["id"],
#         "item_id": row["id"],
#         "name": row["name"],
#         "unit": row["unit"],
#         "purchase_price": to_rupees(price),
#         "default_purchase_price": to_rupees(row["purchase_price_paise"]),
#         "sale_price": to_rupees(row["sale_price_paise"]),
#         "stock": quantity_from_milli(stock_milli),
#         "stock_milli": stock_milli,
#         "active": bool(row["active"]),
#     }



# @api_bp.get("/items")
# def catalog_items_list():
#     """Active general goods, optionally filtered by search text."""
#     q = (request.args.get("q") or "").strip()
#     where, params = " WHERE active=1", []
#     if q:
#         where += " AND (name LIKE ? OR unit LIKE ?)"
#         params.extend([f"%{q}%", f"%{q}%"])
#     rows = get_db().execute(
#         "SELECT * FROM catalog_items" + where + " ORDER BY name COLLATE NOCASE", params
#     ).fetchall()
#     return jsonify([_catalog_item_dict(row) for row in rows])


# @api_bp.get("/suppliers/<int:sid>/catalog-items")
# def supplier_catalog_items_get(sid):
#     supplier_row(sid, include_inactive=True)
#     rows = get_db().execute(
#         "SELECT i.*,si.purchase_price_paise AS supplier_price FROM supplier_catalog_items si "
#         "JOIN catalog_items i ON i.id=si.item_id "
#         "WHERE si.supplier_id=? AND si.active=1 AND i.active=1 ORDER BY i.name COLLATE NOCASE",
#         (sid,),
#     ).fetchall()
#     return jsonify([_catalog_item_dict(row, row["supplier_price"]) for row in rows])


# @api_bp.post("/suppliers/<int:sid>/catalog-items")
# def supplier_catalog_item_add(sid):
#     """Link an existing Stock & Price catalogue item to this supplier."""
#     data = body()
#     db = get_db()
#     supplier_row(sid)
#     existing_id = data.get("item_id")
#     if existing_id in (None, ""):
#         raise ApiError(
#             "Choose an item from Stock & Price. New items are created there.",
#             400, field="item_id",
#         )
#     item_id = int_field(existing_id, "Item", minimum=1)
#     item = db.execute("SELECT * FROM catalog_items WHERE id=? AND active=1", (item_id,)).fetchone()
#     if not item:
#         raise ApiError("Catalogue item not found.", 404)
#     price_raw = data.get("purchase_price")
#     supplier_price = (money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
#                       if price_raw not in (None, "") else item["purchase_price_paise"])
#     with transaction(db):
#         db.execute(
#             "INSERT INTO supplier_catalog_items(supplier_id,item_id,purchase_price_paise,active) "
#             "VALUES(?,?,?,1) ON CONFLICT(supplier_id,item_id) DO UPDATE SET "
#             "purchase_price_paise=excluded.purchase_price_paise,active=1",
#             (sid, item_id, supplier_price),
#         )
#     row = db.execute(
#         "SELECT i.*,si.purchase_price_paise AS supplier_price FROM catalog_items i "
#         "JOIN supplier_catalog_items si ON si.item_id=i.id "
#         "WHERE i.id=? AND si.supplier_id=? AND si.active=1",
#         (item_id, sid),
#     ).fetchone()
#     return jsonify(_catalog_item_dict(row, row["supplier_price"])), 201


# @api_bp.put("/suppliers/<int:sid>/catalog-items/<int:item_id>")
# def supplier_catalog_item_update(sid, item_id):
#     """Edit only this supplier's rate; item name/unit/sale price belong to Stock & Price."""
#     data = body()
#     db = get_db()
#     supplier_row(sid)
#     association = db.execute(
#         "SELECT active FROM supplier_catalog_items WHERE supplier_id=? AND item_id=?", (sid, item_id)
#     ).fetchone()
#     item = db.execute("SELECT id FROM catalog_items WHERE id=? AND active=1", (item_id,)).fetchone()
#     if not association or not association["active"] or not item:
#         raise ApiError("This item is not currently linked to the supplier.", 404)
#     purchase_price = money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
#     with transaction(db):
#         db.execute(
#             "UPDATE supplier_catalog_items SET purchase_price_paise=? WHERE supplier_id=? AND item_id=?",
#             (purchase_price, sid, item_id),
#         )
#     row = db.execute(
#         "SELECT i.*,si.purchase_price_paise AS supplier_price FROM catalog_items i "
#         "JOIN supplier_catalog_items si ON si.item_id=i.id "
#         "WHERE i.id=? AND si.supplier_id=? AND si.active=1",
#         (item_id, sid),
#     ).fetchone()
#     return jsonify(_catalog_item_dict(row, row["supplier_price"]))


# @api_bp.delete("/suppliers/<int:sid>/catalog-items/<int:item_id>")
# def supplier_catalog_item_remove(sid, item_id):
#     supplier_row(sid)
#     db = get_db()
#     with transaction(db):
#         changed = db.execute(
#             "UPDATE supplier_catalog_items SET active=0 WHERE supplier_id=? AND item_id=? AND active=1",
#             (sid, item_id),
#         ).rowcount
#         if not changed:
#             raise ApiError("This item is not linked to the supplier.", 404)
#     return jsonify({"ok": True})
"""Supplier records, supplier ledger, payments, and supplier-specific item prices.

Supplier balance sign: positive = payable to supplier; negative = supplier advance.
Balance = opening + active purchases - active supplier payments.
"""
import re

from flask import jsonify, request

from db import (get_db, next_number, transaction, sole_active_supplier_id,
                link_all_stock_to_supplier)
from money import format_inr, to_rupees

from . import api_bp
from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, phone_field, text

SUPPLIER_SELECT = """SELECT s.*,
    s.opening_balance_paise
      + COALESCE((SELECT SUM(p.total_paise) FROM purchases p
                  WHERE p.supplier_id = s.id AND p.status = 'active'), 0)
      - COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
                  WHERE sp.supplier_id = s.id AND sp.status = 'active'), 0) AS balance,
    COALESCE((SELECT SUM(p.total_paise) FROM purchases p
              WHERE p.supplier_id = s.id AND p.status = 'active'), 0) AS total_purchases_paise,
    COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
              WHERE sp.supplier_id = s.id AND sp.status = 'active'), 0) AS total_paid_paise,
    (SELECT COUNT(*) FROM purchases p WHERE p.supplier_id = s.id AND p.status = 'active') AS purchase_count,
    (SELECT MAX(p.purchase_date) FROM purchases p
      WHERE p.supplier_id = s.id AND p.status = 'active') AS last_purchase
    FROM suppliers s"""


def supplier_row(sid, include_inactive=False):
    sql = SUPPLIER_SELECT + " WHERE s.id = ?" + ("" if include_inactive else " AND s.active = 1")
    row = get_db().execute(sql, (sid,)).fetchone()
    if not row:
        raise ApiError("Supplier not found.", 404)
    return row


def _dict(r):
    return {
        "id": r["id"], "name": r["name"], "gstin": r["gstin"],
        "phone": r["phone"], "address": r["address"], "note": r["note"],
        "opening_balance": to_rupees(r["opening_balance_paise"]),
        "balance": to_rupees(r["balance"]),
        "total_purchases": to_rupees(r["total_purchases_paise"]),
        "total_paid": to_rupees(r["total_paid_paise"]),
        "purchase_count": r["purchase_count"], "last_purchase": r["last_purchase"],
        "type_label": "Supplier", "active": bool(r["active"]),
        "created_at": r["created_at"],
    }


def _parse_supplier(data, self_id=None):
    name = text(data, "name", "Supplier name", required=True, max_len=100)
    gstin = (text(data, "gstin", "GST number", required=True, max_len=15) or "").upper()
    # GSTIN structure: state code + PAN + entity number + Z + checksum character.
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
        raise ApiError("Enter a valid 15-character GSTIN.", field="gstin")
    phone = phone_field(data)
    opening_type = data.get("opening_type", "payable")
    if opening_type not in ("payable", "advance"):
        raise ApiError("Choose Payable or Advance.", field="opening_type")
    opening_amount = money_field(data, "opening_amount", "Previous balance")
    duplicate = get_db().execute(
        "SELECT id FROM suppliers WHERE active = 1 AND gstin = ? AND id IS NOT ?",
        (gstin, self_id),
    ).fetchone()
    if duplicate:
        raise ApiError("A supplier with this GSTIN already exists.", 409, field="gstin")
    return {
        "name": name, "gstin": gstin, "phone": phone,
        "address": text(data, "address", "Address", max_len=250),
        "note": text(data, "note", "Note", max_len=500),
        "opening": opening_amount if opening_type == "payable" else -opening_amount,
    }


@api_bp.get("/suppliers")
def suppliers_list():
    q = (request.args.get("q") or "").strip()
    where, params = " WHERE s.active = 1", []
    if q:
        where += " AND (s.name LIKE ? OR s.gstin LIKE ? OR s.phone LIKE ? OR s.address LIKE ?)"
        params += [f"%{q}%"] * 4
    rows = get_db().execute(SUPPLIER_SELECT + where + " ORDER BY s.name COLLATE NOCASE", params).fetchall()
    return jsonify([_dict(r) for r in rows])


@api_bp.get("/suppliers/summary")
def suppliers_summary():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(CASE WHEN balance > 0 THEN balance ELSE 0 END),0) AS payable, "
        "COALESCE(SUM(CASE WHEN balance < 0 THEN -balance ELSE 0 END),0) AS advance FROM (" +
        SUPPLIER_SELECT + " WHERE s.active = 1)"
    ).fetchone()
    return jsonify({"supplier_count": row["count"], "payable": to_rupees(row["payable"]),
                    "advance": to_rupees(row["advance"])})


@api_bp.post("/suppliers")
def supplier_create():
    f = _parse_supplier(body())
    db = get_db()
    with transaction(db):
        sid = db.execute(
            "INSERT INTO suppliers (name,gstin,phone,address,opening_balance_paise,note) VALUES (?,?,?,?,?,?)",
            (f["name"], f["gstin"], f["phone"], f["address"], f["opening"], f["note"]),
        ).lastrowid
        if sole_active_supplier_id(db) == sid:
            link_all_stock_to_supplier(db, sid)
    return jsonify(_dict(supplier_row(sid))), 201


@api_bp.get("/suppliers/<int:sid>")
def supplier_get(sid):
    return jsonify(_dict(supplier_row(sid)))


@api_bp.put("/suppliers/<int:sid>")
def supplier_update(sid):
    supplier_row(sid)
    f = _parse_supplier(body(), self_id=sid)
    db = get_db()
    with transaction(db):
        db.execute(
            "UPDATE suppliers SET name=?,gstin=?,phone=?,address=?,opening_balance_paise=?,note=? WHERE id=?",
            (f["name"], f["gstin"], f["phone"], f["address"], f["opening"], f["note"], sid),
        )
    return jsonify(_dict(supplier_row(sid)))


@api_bp.delete("/suppliers/<int:sid>")
def supplier_delete(sid):
    """Archive a supplier. History is retained; outstanding balances must be settled first."""
    db = get_db()
    with transaction(db):
        s = supplier_row(sid)
        if s["balance"] != 0:
            raise ApiError(f"{s['name']} has an unsettled balance of {format_inr(s['balance'])}.", 409)
        db.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (sid,))
        remaining_supplier_id = sole_active_supplier_id(db)
        if remaining_supplier_id is not None:
            link_all_stock_to_supplier(db, remaining_supplier_id)
    return jsonify({"ok": True})


@api_bp.get("/suppliers/<int:sid>/ledger")
def supplier_ledger(sid):
    db = get_db()
    s = supplier_row(sid, include_inactive=True)
    opening = s["opening_balance_paise"]
    events = []
    for p in db.execute(
        "SELECT id,number,purchase_date,created_at,total_paise,note,status FROM purchases "
        "WHERE supplier_id=? ORDER BY purchase_date,created_at,id", (sid,)
    ):
        cylinder_summary = db.execute(
            "SELECT GROUP_CONCAT(qty_label, ' · ') FROM ("
            " SELECT CAST(pi.full_in_qty AS TEXT) || ' × ' || ct.name AS qty_label "
            " FROM purchase_items pi JOIN cylinder_types ct ON ct.id=pi.cylinder_type_id "
            " WHERE pi.purchase_id=? AND pi.full_in_qty>0 ORDER BY pi.id)", (p["id"],)
        ).fetchone()[0]
        other_summary = db.execute(
            "SELECT GROUP_CONCAT(label, ' · ') FROM (SELECT printf('%g',quantity_milli/1000.0) || ' ' || "
            "item_name AS label FROM purchase_catalog_items WHERE purchase_id=? ORDER BY id)", (p["id"],)
        ).fetchone()[0]
        summary = " · ".join(part for part in (cylinder_summary, other_summary) if part)
        events.append(((p["purchase_date"], p["created_at"], 0, p["id"]), {
            "kind": "purchase", "id": p["id"], "date": p["purchase_date"],
            "detail": f"Purchase {p['number']}", "sub": summary or p["note"],
            "purchase": to_rupees(p["total_paise"]), "paid": None,
            "status": p["status"], "delta": p["total_paise"],
        }))
    for p in db.execute(
        "SELECT sp.id,sp.number,sp.payment_date,sp.created_at,sp.amount_paise,sp.paid_from,sp.note,sp.status,"
        "pu.number AS purchase_number FROM supplier_payments sp "
        "LEFT JOIN purchases pu ON pu.id=sp.purchase_id WHERE sp.supplier_id=?", (sid,)
    ):
        sub = ("Cash in hand" if p["paid_from"] == "cash" else "Bank / UPI")
        if p["purchase_number"]:
            sub += " · " + p["purchase_number"]
        if p["note"]:
            sub += " · " + p["note"]
        events.append(((p["payment_date"], p["created_at"], 1, p["id"]), {
            "kind": "payment", "id": p["id"], "date": p["payment_date"],
            "detail": f"Paid to supplier {p['number']}", "sub": sub,
            "purchase": None, "paid": to_rupees(p["amount_paise"]),
            "status": p["status"], "delta": -p["amount_paise"],
        }))

    rows = [{"kind": "opening", "id": None, "date": None, "detail": "Opening balance", "sub": None,
             "purchase": to_rupees(opening) if opening > 0 else None,
             "paid": to_rupees(-opening) if opening < 0 else None,
             "balance": to_rupees(opening), "status": "active"}]
    running = opening
    for _, e in sorted(events, key=lambda item: item[0]):
        if e["status"] == "active":
            running += e["delta"]
        e["balance"] = to_rupees(running)
        del e["delta"]
        rows.append(e)
    return jsonify({"rows": rows, "closing_balance": to_rupees(running)})


@api_bp.get("/suppliers/<int:sid>/items")
def supplier_items_get(sid):
    """Return only cylinder types currently supplied by this supplier."""
    supplier_row(sid, include_inactive=True)
    rows = get_db().execute(
        "SELECT ct.id,ct.name,ct.kg,ct.purchase_price_paise AS default_price,ct.security_paise,ct.sale_price_paise,"
        "si.purchase_price_paise AS supplier_price "
        "FROM supplier_items si JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
        "WHERE si.supplier_id=? AND ct.active=1 ORDER BY ct.sort_order,ct.id", (sid,)
    ).fetchall()
    return jsonify([_supplier_cylinder_dict(row) for row in rows])


def _supplier_cylinder_dict(row):
    return {
        "cylinder_type_id": row["id"],
        "name": row["name"],
        "purchase_price": to_rupees(row["supplier_price"]),
        "default_purchase_price": to_rupees(row["default_price"]),
        "security_price": to_rupees(row["security_paise"]),
        "sale_price": to_rupees(row["sale_price_paise"]),
        "weight_kg": row["kg"],
    }


@api_bp.get("/suppliers/<int:sid>/available-cylinders")
def supplier_available_cylinders(sid):
    """Active cylinder types not yet linked to this supplier."""
    supplier_row(sid)
    rows = get_db().execute(
        "SELECT ct.id,ct.name,ct.kg,ct.purchase_price_paise AS default_price,ct.security_paise,ct.sale_price_paise "
        "FROM cylinder_types ct LEFT JOIN supplier_items si "
        "ON si.cylinder_type_id=ct.id AND si.supplier_id=? "
        "WHERE ct.active=1 AND si.supplier_id IS NULL ORDER BY ct.sort_order,ct.id", (sid,)
    ).fetchall()
    return jsonify([{
        "cylinder_type_id": row["id"],
        "name": row["name"],
        "purchase_price": to_rupees(row["default_price"]),
        "security_price": to_rupees(row["security_paise"]),
        "sale_price": to_rupees(row["sale_price_paise"]),
    } for row in rows])


def _optional_money(data, key, label):
    """Paise, or None when the field was left blank (meaning: keep the saved value)."""
    if data.get(key) in (None, ""):
        return None
    return money_field(data, key, label, allow_zero=True)


def _apply_cylinder_prices(db, tid, deposit, sale_price):
    if deposit is not None:
        db.execute("UPDATE cylinder_types SET security_paise=? WHERE id=?", (deposit, tid))
    if sale_price is not None:
        db.execute("UPDATE cylinder_types SET sale_price_paise=? WHERE id=?", (sale_price, tid))


@api_bp.post("/suppliers/<int:sid>/items")
def supplier_cylinder_link(sid):
    """Create/reuse a cylinder weight and make it available from this supplier."""
    supplier_row(sid)
    data = body()
    raw_weight = data.get("weight_kg")
    try:
        weight = float(raw_weight)
    except (TypeError, ValueError):
        raise ApiError("Enter the cylinder weight in kg.", 400, field="weight_kg")
    if not (0.1 <= weight <= 1000):
        raise ApiError("Cylinder weight must be between 0.1 and 1000 kg.", 400, field="weight_kg")
    weight = round(weight, 3)
    label = f"{weight:g} kg"
    price = money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
    deposit = _optional_money(data, "deposit", "Deposit")
    sale_price = _optional_money(data, "sale_price", "Selling price")
    db = get_db()
    with transaction(db):
        cylinder = db.execute(
            "SELECT id FROM cylinder_types WHERE ABS(COALESCE(kg,0)-?) < 0.0005", (weight,)
        ).fetchone()
        if cylinder:
            tid = cylinder["id"]
            db.execute("UPDATE cylinder_types SET active=1 WHERE id=?", (tid,))
        else:
            sort_order = db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM cylinder_types").fetchone()[0]
            tid = db.execute(
                "INSERT INTO cylinder_types(name,kg,sort_order) VALUES(?,?,?)", (label, weight, sort_order)
            ).lastrowid
        _apply_cylinder_prices(db, tid, deposit, sale_price)
        db.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
            "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
            (sid, tid, price),
        )
    row = db.execute(
        "SELECT ct.id,ct.name,ct.kg,ct.purchase_price_paise AS default_price,ct.security_paise,ct.sale_price_paise,"
        "si.purchase_price_paise AS supplier_price FROM supplier_items si "
        "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
        "WHERE si.supplier_id=? AND si.cylinder_type_id=?", (sid, tid)
    ).fetchone()
    return jsonify(_supplier_cylinder_dict(row)), 201


@api_bp.put("/suppliers/<int:sid>/items/<int:tid>")
def supplier_cylinder_price_update(sid, tid):
    """Update supplier rate and, if needed, move this supplier to another weight variant."""
    supplier_row(sid)
    data = body()
    db = get_db()
    linked = db.execute(
        "SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)
    ).fetchone()
    if not linked:
        raise ApiError("This cylinder size is not linked to this supplier.", 404)
    price = money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
    raw_weight = data.get("weight_kg")
    try:
        weight = round(float(raw_weight), 3)
    except (TypeError, ValueError):
        raise ApiError("Enter the cylinder weight in kg.", 400, field="weight_kg")
    if not (0.1 <= weight <= 1000):
        raise ApiError("Cylinder weight must be between 0.1 and 1000 kg.", 400, field="weight_kg")
    label = f"{weight:g} kg"
    deposit = _optional_money(data, "deposit", "Deposit")
    sale_price = _optional_money(data, "sale_price", "Selling price")
    with transaction(db):
        current = db.execute("SELECT kg FROM cylinder_types WHERE id=?", (tid,)).fetchone()
        if not current:
            raise ApiError("Cylinder type not found.", 404)
        if current["kg"] is not None and abs(float(current["kg"]) - weight) < 0.0005:
            target_id = tid
        else:
            target = db.execute(
                "SELECT id FROM cylinder_types WHERE ABS(COALESCE(kg,0)-?) < 0.0005", (weight,)
            ).fetchone()
            if target:
                target_id = target["id"]
                db.execute("UPDATE cylinder_types SET active=1 WHERE id=?", (target_id,))
            else:
                sort_order = db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM cylinder_types").fetchone()[0]
                target_id = db.execute(
                    "INSERT INTO cylinder_types(name,kg,sort_order) VALUES(?,?,?)", (label, weight, sort_order)
                ).lastrowid
            already = db.execute(
                "SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, target_id)
            ).fetchone()
            if already:
                raise ApiError("This supplier already has that cylinder weight. Edit its existing entry instead.", 409)
            db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
        _apply_cylinder_prices(db, target_id, deposit, sale_price)
        db.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
            "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
            (sid, target_id, price),
        )
    row = db.execute(
        "SELECT ct.id,ct.name,ct.kg,ct.purchase_price_paise AS default_price,ct.security_paise,ct.sale_price_paise,"
        "si.purchase_price_paise AS supplier_price FROM supplier_items si "
        "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
        "WHERE si.supplier_id=? AND si.cylinder_type_id=?", (sid, target_id)
    ).fetchone()
    return jsonify(_supplier_cylinder_dict(row))

@api_bp.delete("/suppliers/<int:sid>/items/<int:tid>")
def supplier_cylinder_unlink(sid, tid):
    """Stop offering this cylinder to the supplier without touching history or stock."""
    supplier_row(sid)
    db = get_db()

    with transaction(db):
        changed = db.execute(
            "DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?",
            (sid, tid)
        ).rowcount

        if not changed:
            raise ApiError(
                "This cylinder size is not linked to this supplier.", 404
            )

    return jsonify({"ok": True})

# Backwards-compatible bulk endpoint. New UI uses the item-specific add/edit/remove routes above.
@api_bp.put("/suppliers/<int:sid>/items")
def supplier_items_save(sid):
    supplier_row(sid)
    items = body().get("items")
    if not isinstance(items, list):
        raise ApiError("Send the supplier's item list.")
    db = get_db()
    valid = {r["id"] for r in db.execute("SELECT id FROM cylinder_types WHERE active=1")}
    parsed, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("Invalid item entry.")
        tid = int_field(item.get("cylinder_type_id"), "Cylinder type", minimum=1)
        if tid not in valid or tid in seen:
            raise ApiError("Unknown or duplicate cylinder type.", 409)
        seen.add(tid)
        enabled = bool(item.get("supplied"))
        price = money_field(item, "purchase_price", "Purchase price", allow_zero=False) if enabled else None
        parsed.append((tid, enabled, price))
    with transaction(db):
        for tid, enabled, price in parsed:
            if enabled:
                db.execute(
                    "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
                    "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
                    (sid, tid, price),
                )
            else:
                db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
    return jsonify(supplier_items_get_data(db, sid))


def supplier_items_get_data(db, sid):
    rows = db.execute(
        "SELECT ct.id,ct.name,ct.kg,ct.purchase_price_paise AS default_price,ct.security_paise,ct.sale_price_paise,"
        "si.purchase_price_paise AS supplier_price FROM supplier_items si "
        "JOIN cylinder_types ct ON ct.id=si.cylinder_type_id "
        "WHERE si.supplier_id=? AND ct.active=1 ORDER BY ct.sort_order,ct.id", (sid,)
    ).fetchall()
    return [_supplier_cylinder_dict(row) for row in rows]


@api_bp.post("/suppliers/<int:sid>/payments")
def supplier_payment_create(sid):
    data = body()
    amount = money_field(data, "amount", "Amount", allow_zero=False)
    day = day_field(data)
    paid_from = data.get("paid_from", "cash")
    if paid_from not in RECEIVED_IN:
        raise ApiError("Choose Cash in hand or Bank / UPI.", field="paid_from")
    note = text(data, "note", "Note", max_len=200)
    purchase_id = data.get("purchase_id")
    if purchase_id not in (None, ""):
        purchase_id = int_field(purchase_id, "Purchase", minimum=1)
    else:
        purchase_id = None

    db = get_db()
    with transaction(db):
        # Validate under the write lock so concurrent requests cannot overpay
        # the same purchase if this API is hosted for multiple devices later.
        supplier_row(sid)
        if purchase_id is not None:
            row = db.execute(
                "SELECT p.supplier_id,p.total_paise-COALESCE((SELECT SUM(sp.amount_paise) "
                "FROM supplier_payments sp WHERE sp.purchase_id=p.id AND sp.status='active'),0) AS due_paise "
                "FROM purchases p WHERE p.id=? AND p.status='active'", (purchase_id,)
            ).fetchone()
            if not row or row["supplier_id"] != sid:
                raise ApiError("This purchase does not belong to the selected supplier.", 409, field="purchase_id")
            if amount > row["due_paise"]:
                raise ApiError("Payment cannot exceed the remaining balance of this purchase. Use a general supplier payment for an advance.", 409, field="amount")
        number = next_number(db, "supplier_payment", "SP")
        pid = db.execute(
            "INSERT INTO supplier_payments(number,supplier_id,purchase_id,amount_paise,payment_date,paid_from,note) "
            "VALUES(?,?,?,?,?,?,?)", (number,sid,purchase_id,amount,day,paid_from,note)
        ).lastrowid
    r = db.execute("SELECT * FROM supplier_payments WHERE id=?", (pid,)).fetchone()
    return jsonify({"id": r["id"], "number": r["number"], "supplier_id": sid,
                    "purchase_id": r["purchase_id"], "amount": to_rupees(r["amount_paise"]),
                    "date": r["payment_date"], "paid_from": r["paid_from"], "note": r["note"],
                    "balance": to_rupees(supplier_row(sid)["balance"])}), 201


@api_bp.post("/supplier-payments/<int:pid>/cancel")
def supplier_payment_cancel(pid):
    db = get_db()
    row = db.execute("SELECT id,status FROM supplier_payments WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ApiError("Supplier payment not found.", 404)
    if row["status"] == "cancelled":
        raise ApiError("This payment is already cancelled.", 409)
    with transaction(db):
        db.execute("UPDATE supplier_payments SET status='cancelled' WHERE id=?", (pid,))
    return jsonify({"ok": True})

# ---------------------------------------------------------------- general catalogue items (non-cylinder goods)
def _catalog_item_dict(row, supplier_price=None):
    stock_milli = row["stock_qty_milli"]
    from .util import quantity_from_milli
    price = row["purchase_price_paise"] if supplier_price is None else supplier_price
    return {
        "id": row["id"],
        "item_id": row["id"],
        "name": row["name"],
        "unit": row["unit"],
        "purchase_price": to_rupees(price),
        "default_purchase_price": to_rupees(row["purchase_price_paise"]),
        "sale_price": to_rupees(row["sale_price_paise"]),
        "stock": quantity_from_milli(stock_milli),
        "stock_milli": stock_milli,
        "active": bool(row["active"]),
    }



@api_bp.get("/items")
def catalog_items_list():
    """Active general goods, optionally filtered by search text."""
    q = (request.args.get("q") or "").strip()
    where, params = " WHERE active=1", []
    if q:
        where += " AND (name LIKE ? OR unit LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    rows = get_db().execute(
        "SELECT * FROM catalog_items" + where + " ORDER BY name COLLATE NOCASE", params
    ).fetchall()
    return jsonify([_catalog_item_dict(row) for row in rows])


@api_bp.get("/suppliers/<int:sid>/catalog-items")
def supplier_catalog_items_get(sid):
    supplier_row(sid, include_inactive=True)
    rows = get_db().execute(
        "SELECT i.*,si.purchase_price_paise AS supplier_price FROM supplier_catalog_items si "
        "JOIN catalog_items i ON i.id=si.item_id "
        "WHERE si.supplier_id=? AND si.active=1 AND i.active=1 ORDER BY i.name COLLATE NOCASE",
        (sid,),
    ).fetchall()
    return jsonify([_catalog_item_dict(row, row["supplier_price"]) for row in rows])


@api_bp.post("/suppliers/<int:sid>/catalog-items")
def supplier_catalog_item_add(sid):
    """Create a supplier-specific general item with its purchase and resale prices."""
    data = body()
    db = get_db()
    supplier_row(sid)
    name = text(data, "name", "Item name", required=True, max_len=100)
    unit = text(data, "unit", "Unit", required=False, max_len=20) or "pcs"
    purchase_price = money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
    sale_price = money_field(data, "sale_price", "Sale price", allow_zero=False)
    with transaction(db):
        existing = db.execute("SELECT id FROM catalog_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if existing:
            item_id = existing["id"]
            db.execute("UPDATE catalog_items SET unit=?,sale_price_paise=?,active=1 WHERE id=?", (unit, sale_price, item_id))
        else:
            item_id = db.execute(
                "INSERT INTO catalog_items(name,unit,purchase_price_paise,sale_price_paise) VALUES(?,?,?,?)",
                (name, unit, purchase_price, sale_price),
            ).lastrowid
        db.execute(
            "INSERT INTO supplier_catalog_items(supplier_id,item_id,purchase_price_paise,active) "
            "VALUES(?,?,?,1) ON CONFLICT(supplier_id,item_id) DO UPDATE SET "
            "purchase_price_paise=excluded.purchase_price_paise,active=1",
            (sid, item_id, purchase_price),
        )
    row = db.execute(
        "SELECT i.*,si.purchase_price_paise AS supplier_price FROM catalog_items i "
        "JOIN supplier_catalog_items si ON si.item_id=i.id "
        "WHERE i.id=? AND si.supplier_id=? AND si.active=1", (item_id, sid)
    ).fetchone()
    return jsonify(_catalog_item_dict(row, row["supplier_price"])), 201


@api_bp.put("/suppliers/<int:sid>/catalog-items/<int:item_id>")
def supplier_catalog_item_update(sid, item_id):
    """Edit the item description/resale price and this supplier's purchase price."""
    data = body()
    db = get_db()
    supplier_row(sid)
    association = db.execute(
        "SELECT active FROM supplier_catalog_items WHERE supplier_id=? AND item_id=?", (sid, item_id)
    ).fetchone()
    if not association or not association["active"]:
        raise ApiError("This item is not currently supplied by this supplier.", 404)
    name = text(data, "name", "Item name", required=True, max_len=100)
    unit = text(data, "unit", "Unit", required=False, max_len=20) or "pcs"
    purchase_price = money_field(data, "purchase_price", "Supplier purchase price", allow_zero=False)
    sale_price = money_field(data, "sale_price", "Sale price", allow_zero=False)
    with transaction(db):
        duplicate = db.execute("SELECT id FROM catalog_items WHERE name=? COLLATE NOCASE AND id<>?", (name, item_id)).fetchone()
        if duplicate:
            raise ApiError("Another catalogue item already uses this name.", 409, field="name")
        db.execute("UPDATE catalog_items SET name=?,unit=?,sale_price_paise=? WHERE id=?", (name, unit, sale_price, item_id))
        db.execute(
            "UPDATE supplier_catalog_items SET purchase_price_paise=? WHERE supplier_id=? AND item_id=?",
            (purchase_price, sid, item_id),
        )
    row = db.execute(
        "SELECT i.*,si.purchase_price_paise AS supplier_price FROM catalog_items i "
        "JOIN supplier_catalog_items si ON si.item_id=i.id "
        "WHERE i.id=? AND si.supplier_id=? AND si.active=1", (item_id, sid)
    ).fetchone()
    return jsonify(_catalog_item_dict(row, row["supplier_price"]))

@api_bp.delete("/suppliers/<int:sid>/catalog-items/<int:item_id>")
def supplier_catalog_item_remove(sid, item_id):
    supplier_row(sid)
    db = get_db()
    with transaction(db):
        changed = db.execute(
            "UPDATE supplier_catalog_items SET active=0 WHERE supplier_id=? AND item_id=? AND active=1",
            (sid, item_id),
        ).rowcount
        if not changed:
            raise ApiError("This item is not linked to the supplier.", 404)
    return jsonify({"ok": True})
