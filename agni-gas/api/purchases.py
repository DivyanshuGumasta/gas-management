"""Purchase records, purchase history, supplier bill attachments and stock updates.

This records the supplier's invoice; it deliberately does not generate a purchase bill.
"""
import json
import os
from io import BytesIO
from decimal import Decimal, InvalidOperation
from flask import jsonify, request, send_file

from db import get_db, next_number, transaction
from money import gst_paise, to_rupees
from . import api_bp
from .suppliers import supplier_row
from .util import (ApiError, RECEIVED_IN, body, day_field, int_field, money_field,
                   quantity_milli_field, quantity_from_milli, text)

ALLOWED_ATTACHMENTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _purchase_payload(row):
    return {
        "id": row["id"], "number": row["number"], "supplier_id": row["supplier_id"],
        "supplier": row["supplier_name"], "gstin": row["gstin"], "date": row["purchase_date"],
        "subtotal": to_rupees(row["subtotal_paise"]), "gst_percent": row["gst_percent"],
        "gst": to_rupees(row["gst_paise"]), "total": to_rupees(row["total_paise"]),
        "paid": to_rupees(row["paid_paise"]), "due": to_rupees(row["due_paise"]),
        "status": "paid" if row["paid_paise"] >= row["total_paise"] else ("partial" if row["paid_paise"] else "unpaid"),
        "items_summary": row["items_summary"] or "No item quantity", "note": row["note"],
        "attachment_name": row["supplier_bill_name"], "attachment_mime": row["supplier_bill_mime"],
        "has_attachment": bool(row["has_attachment"]),
    }


def _list_sql():
    return """SELECT p.id,p.number,p.supplier_id,p.purchase_date,p.created_at,
      p.subtotal_paise,p.gst_percent,p.gst_paise,p.total_paise,p.note,
      p.supplier_bill_name,p.supplier_bill_mime,
      CASE WHEN p.supplier_bill_data IS NOT NULL AND length(p.supplier_bill_data)>0 THEN 1 ELSE 0 END AS has_attachment,
      s.name AS supplier_name,s.gstin,
      COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
                WHERE sp.purchase_id=p.id AND sp.status='active'),0) AS paid_paise,
      p.total_paise-COALESCE((SELECT SUM(sp.amount_paise) FROM supplier_payments sp
                WHERE sp.purchase_id=p.id AND sp.status='active'),0) AS due_paise,
      (SELECT GROUP_CONCAT(label,' · ') FROM (
         SELECT CAST(pi.full_in_qty AS TEXT) || ' × ' || ct.name AS label
         FROM purchase_items pi JOIN cylinder_types ct ON ct.id=pi.cylinder_type_id
         WHERE pi.purchase_id=p.id AND pi.full_in_qty>0
         UNION ALL
         SELECT printf('%g', pci.quantity_milli / 1000.0) || ' ' || pci.item_name AS label
         FROM purchase_catalog_items pci WHERE pci.purchase_id=p.id
       )) AS items_summary
      FROM purchases p JOIN suppliers s ON s.id=p.supplier_id"""


def _purchase_row(pid):
    row = get_db().execute(_list_sql() + " WHERE p.id=?", (pid,)).fetchone()
    if not row:
        raise ApiError("Purchase not found.", 404)
    return row


def _date_filter(query, where, params):
    start, end = query.get("from"), query.get("to")
    parsed = {}
    for key, value, op in (("from", start, ">="), ("to", end, "<=")):
        if value:
            try:
                from datetime import date
                parsed[key] = date.fromisoformat(value)
            except (TypeError, ValueError):
                raise ApiError(f"Invalid {key} date.", field=key)
            where += f" AND p.purchase_date {op} ?"
            params.append(value)
    if parsed.get("from") and parsed.get("to") and parsed["from"] > parsed["to"]:
        raise ApiError("The start date must be on or before the end date.", field="from")
    return where, params


@api_bp.get("/purchases/options")
def purchase_options():
    """Return only active cylinder sizes linked to the selected supplier."""
    db = get_db()
    raw_sid = request.args.get("supplier_id")
    if raw_sid in (None, ""):
        return jsonify([])
    sid = int_field(raw_sid, "Supplier", minimum=1)
    supplier_row(sid)
    rows = db.execute(
        "SELECT ct.id,ct.name,ct.full_qty,ct.empty_qty,ct.purchase_price_paise,ct.security_paise,"
        "si.purchase_price_paise AS supplier_price FROM cylinder_types ct "
        "JOIN supplier_items si ON si.cylinder_type_id=ct.id AND si.supplier_id=? "
        "WHERE ct.active=1 ORDER BY ct.sort_order,ct.id", (sid,)
    ).fetchall()
    return jsonify([{
        "id": r["id"], "name": r["name"], "full_stock": r["full_qty"], "empty_stock": r["empty_qty"],
        "rate": to_rupees(r["supplier_price"]),
        "security_rate": to_rupees(r["security_paise"]),
    } for r in rows])


@api_bp.get("/purchases/catalog-options")
def purchase_catalog_options():
    sid = int_field(request.args.get("supplier_id"), "Supplier", minimum=1)
    supplier_row(sid)
    rows = get_db().execute(
        "SELECT i.id,i.name,i.unit,i.stock_qty_milli,si.purchase_price_paise "
        "FROM supplier_catalog_items si JOIN catalog_items i ON i.id=si.item_id "
        "WHERE si.supplier_id=? AND si.active=1 AND i.active=1 ORDER BY i.name COLLATE NOCASE", (sid,)
    ).fetchall()
    return jsonify([{
        "id": r["id"], "name": r["name"], "unit": r["unit"],
        "stock": quantity_from_milli(r["stock_qty_milli"]),
        "stock_milli": r["stock_qty_milli"],
        "rate": to_rupees(r["purchase_price_paise"]),
    } for r in rows])


@api_bp.get("/purchases")
def purchases_list():
    where, params = " WHERE p.status='active'", []
    where, params = _date_filter(request.args, where, params)
    sid = request.args.get("supplier_id")
    if sid:
        where += " AND p.supplier_id=?"
        params.append(int_field(sid, "Supplier", minimum=1))
    q = (request.args.get("q") or "").strip()
    if q:
        where += " AND (p.number LIKE ? OR s.name LIKE ? OR s.gstin LIKE ?)"
        params += [f"%{q}%"] * 3
    rows = get_db().execute(_list_sql() + where + " ORDER BY p.purchase_date DESC,p.id DESC LIMIT 5000", params).fetchall()
    return jsonify([_purchase_payload(r) for r in rows])


@api_bp.get("/purchases/summary")
def purchases_summary():
    db = get_db()
    where, params = " WHERE p.status='active'", []
    where, params = _date_filter(request.args, where, params)
    r = db.execute("SELECT COUNT(*) AS count,COALESCE(SUM(p.total_paise),0) AS total FROM purchases p" + where, params).fetchone()
    payable = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN balance>0 THEN balance ELSE 0 END),0) FROM ("
        "SELECT s.opening_balance_paise + COALESCE((SELECT SUM(p.total_paise) FROM purchases p "
        "WHERE p.supplier_id=s.id AND p.status='active'),0) - COALESCE((SELECT SUM(sp.amount_paise) "
        "FROM supplier_payments sp WHERE sp.supplier_id=s.id AND sp.status='active'),0) AS balance "
        "FROM suppliers s WHERE s.active=1)"
    ).fetchone()[0]
    return jsonify({"purchase_count": r["count"], "total": to_rupees(r["total"]), "payable": to_rupees(payable)})


def _read_payload():
    if request.is_json:
        return body()
    raw = request.form.get("payload")
    if not raw:
        raise ApiError("Purchase details are missing.")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ApiError("Purchase details are invalid.")
    if not isinstance(data, dict):
        raise ApiError("Purchase details are invalid.")
    return data


def _attachment():
    f = request.files.get("supplier_bill")
    if not f or not f.filename:
        return None, None, None
    from werkzeug.utils import secure_filename
    filename = secure_filename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_ATTACHMENTS:
        raise ApiError("Attach a PDF or image (PDF, PNG, JPG or WEBP).", field="supplier_bill")
    data = f.read(MAX_ATTACHMENT_BYTES + 1)
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ApiError("Supplier bill attachment must be 5 MB or smaller.", field="supplier_bill")
    if not data:
        raise ApiError("The selected attachment is empty.", field="supplier_bill")
    mime = {".pdf":"application/pdf", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".webp":"image/webp"}[ext]
    return filename, mime, data


@api_bp.post("/purchases")
def purchase_create():
    data = _read_payload()
    db = get_db()
    sid = int_field(data.get("supplier_id"), "Supplier", field="supplier_id", minimum=1)
    supplier_row(sid)
    day = day_field(data)
    note = text(data, "note", "Note", max_len=500)
    try:
        gst_percent = Decimal(str(data.get("gst_percent", "0") or "0"))
    except InvalidOperation:
        raise ApiError("GST rate must be a valid number.", field="gst_percent")
    if not gst_percent.is_finite() or gst_percent < 0 or gst_percent > 100:
        raise ApiError("GST rate must be a number between 0 and 100.", field="gst_percent")
    items = data.get("items", [])
    catalog_items = data.get("catalog_items", [])
    if not isinstance(items, list) or not isinstance(catalog_items, list):
        raise ApiError("Purchase items must be sent as lists.", field="items")

    wanted, wanted_catalog, subtotal = [], [], 0
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("Invalid purchase item.")
        tid = int_field(item.get("cylinder_type_id"), "Cylinder type", minimum=1)
        if tid in seen:
            raise ApiError("A cylinder size can only appear once in a purchase.")
        seen.add(tid)
        full_in = int_field(item.get("full_in", 0), "Full cylinders received", field=f"full_{tid}")
        empty_out = int_field(item.get("empty_out", 0), "Empty cylinders returned", field=f"empty_{tid}")
        new_empty = int_field(item.get("new_empty", 0), "New empty cylinders", field=f"new_empty_{tid}")
        if full_in + empty_out + new_empty == 0:
            continue
        linked = db.execute(
            "SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)
        ).fetchone()
        if not linked:
            raise ApiError("This cylinder is not supplied by the selected supplier.", 409, field=f"cylinder_{tid}")
        ct = db.execute("SELECT id,name,empty_qty,purchase_price_paise,security_paise FROM cylinder_types WHERE id=? AND active=1", (tid,)).fetchone()
        if not ct:
            raise ApiError("Cylinder type not found.", 404)
        if empty_out > ct["empty_qty"]:
            raise ApiError(f"{ct['name']}: only {ct['empty_qty']} empty cylinders are in stock to return.", 409, field=f"empty_{tid}")
        rate = money_field(item, "rate", "Purchase rate", allow_zero=(full_in == 0))
        if full_in and rate <= 0:
            raise ApiError(f"Enter a purchase rate for {ct['name']}.", field=f"rate_{tid}")
        security_rate = ct["security_paise"]
        amount = full_in * rate + new_empty * security_rate
        subtotal += amount
        wanted.append({"id":tid,"name":ct["name"],"full_in":full_in,"empty_out":empty_out,
                       "new_empty":new_empty,"rate":rate,"security_rate":security_rate,"amount":amount})
    seen_catalog = set()
    for item in catalog_items:
        if not isinstance(item, dict):
            raise ApiError("Invalid general catalogue item.")
        item_id = int_field(item.get("item_id"), "Item", minimum=1)
        if item_id in seen_catalog:
            raise ApiError("An item can only appear once in a purchase.")
        seen_catalog.add(item_id)
        quantity_milli = quantity_milli_field(item.get("quantity"), "Item quantity", field=f"quantity_{item_id}")
        rate = money_field(item, "rate", "Item rate", allow_zero=False)
        row = db.execute(
            "SELECT i.id,i.name,i.unit,i.stock_qty_milli FROM catalog_items i "
            "JOIN supplier_catalog_items si ON si.item_id=i.id "
            "WHERE i.id=? AND i.active=1 AND si.supplier_id=? AND si.active=1",
            (item_id, sid),
        ).fetchone()
        if not row:
            raise ApiError("This item is not currently supplied by the selected supplier.", 409, field=f"item_{item_id}")
        if row["unit"] in {"pcs", "packet", "box", "set", "pair"} and quantity_milli % 1000:
            raise ApiError(f"{row['name']} is counted in whole {row['unit']}; enter a whole quantity.", field=f"quantity_{item_id}")
        # Each amount is rounded to the nearest paisa using Decimal arithmetic.
        from decimal import ROUND_HALF_UP
        line_amount = int((Decimal(quantity_milli) * Decimal(rate) / Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        subtotal += line_amount
        wanted_catalog.append({
            "id": item_id, "name": row["name"], "unit": row["unit"],
            "quantity_milli": quantity_milli, "rate": rate, "amount": line_amount,
        })

    if not wanted and not wanted_catalog:
        raise ApiError("Enter a quantity for at least one item.", field="items")

    gst = gst_paise(subtotal, gst_percent)
    total = subtotal + gst
    paid = money_field(data, "paid_amount", "Paid to supplier")
    if paid > total:
        raise ApiError("Amount paid cannot exceed this purchase total. Record an extra amount as a supplier advance.", field="paid_amount")
    paid_from = data.get("paid_from", "cash")
    if paid_from not in RECEIVED_IN:
        raise ApiError("Choose Cash in hand or Bank / UPI.", field="paid_from")
    raw_update_prices = data.get("update_prices", True)
    if not isinstance(raw_update_prices, bool):
        raise ApiError("Update purchase prices must be true or false.", field="update_prices")
    update_prices = raw_update_prices
    attachment_name, attachment_mime, attachment_data = _attachment()

    with transaction(db):
        # Recheck the supplier after taking the write lock. This avoids creating
        # purchases against a supplier archived while the form was open.
        active_supplier = db.execute("SELECT id FROM suppliers WHERE id=? AND active=1", (sid,)).fetchone()
        if not active_supplier:
            raise ApiError("Supplier not found or no longer active.", 404, field="supplier_id")
        # Recheck supplier links and empty-cylinder stock after taking the write lock.
        # This prevents a purchase being saved after a supplier-item link is removed
        # while the form is open, and avoids concurrent returns of the same empties.
        for item in wanted:
            linked = db.execute(
                "SELECT 1 FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?",
                (sid, item["id"]),
            ).fetchone()
            if not linked:
                raise ApiError("This cylinder is no longer supplied by the selected supplier.", 409,
                               field=f"cylinder_{item['id']}")
            current_stock = db.execute(
                "SELECT empty_qty,name FROM cylinder_types WHERE id=? AND active=1", (item["id"],)
            ).fetchone()
            if not current_stock or item["empty_out"] > current_stock["empty_qty"]:
                available = current_stock["empty_qty"] if current_stock else 0
                raise ApiError(f"{item['name']}: only {available} empty cylinders are in stock to return.",
                               409, field=f"empty_{item['id']}")
        number = next_number(db, "purchase", "P")
        pid = db.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_percent,gst_paise,total_paise,note,"
            "supplier_bill_name,supplier_bill_mime,supplier_bill_data) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (number,sid,day,subtotal,str(gst_percent),gst,total,note,attachment_name,attachment_mime,attachment_data)
        ).lastrowid
        for item in wanted:
            db.execute(
                "INSERT INTO purchase_items(purchase_id,cylinder_type_id,full_in_qty,empty_out_qty,new_empty_qty,rate_paise,security_rate_paise,amount_paise) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (pid,item["id"],item["full_in"],item["empty_out"],item["new_empty"],item["rate"],item["security_rate"],item["amount"]),
            )
            db.execute(
                "UPDATE cylinder_types SET full_qty=full_qty+?, empty_qty=empty_qty-?+? WHERE id=?",
                (item["full_in"],item["empty_out"],item["new_empty"],item["id"]),
            )
            db.execute(
                "INSERT INTO stock_movements(cylinder_type_id,ref_type,ref_id,full_delta,empty_delta,note) VALUES(?,?,?,?,?,?)",
                (item["id"],"purchase",pid,item["full_in"],item["new_empty"]-item["empty_out"],f"Purchase {number}"),
            )
            if update_prices and item["full_in"]:
                db.execute(
                    "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise) VALUES(?,?,?) "
                    "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
                    (sid,item["id"],item["rate"]),
                )
                db.execute("UPDATE cylinder_types SET purchase_price_paise=? WHERE id=?", (item["rate"],item["id"]))
        for item in wanted_catalog:
            # Verify the supplier-item link still exists while holding the write lock.
            link = db.execute(
                "SELECT 1 FROM supplier_catalog_items WHERE supplier_id=? AND item_id=? AND active=1",
                (sid, item["id"]),
            ).fetchone()
            if not link:
                raise ApiError(f"{item['name']} is no longer supplied by this supplier.", 409)
            db.execute(
                "INSERT INTO purchase_catalog_items(purchase_id,item_id,item_name,unit,quantity_milli,rate_paise,amount_paise) "
                "VALUES(?,?,?,?,?,?,?)",
                (pid,item["id"],item["name"],item["unit"],item["quantity_milli"],item["rate"],item["amount"]),
            )
            db.execute(
                "UPDATE catalog_items SET stock_qty_milli=stock_qty_milli+? WHERE id=?",
                (item["quantity_milli"],item["id"]),
            )
            db.execute(
                "INSERT INTO catalog_stock_movements(item_id,purchase_id,quantity_delta_milli,note) VALUES(?,?,?,?)",
                (item["id"],pid,item["quantity_milli"],f"Purchase {number}"),
            )
            if update_prices:
                db.execute(
                    "UPDATE supplier_catalog_items SET purchase_price_paise=? WHERE supplier_id=? AND item_id=?",
                    (item["rate"],sid,item["id"]),
                )
                db.execute("UPDATE catalog_items SET purchase_price_paise=? WHERE id=?", (item["rate"],item["id"]))

        if paid:
            payment_number = next_number(db, "supplier_payment", "SP")
            db.execute(
                "INSERT INTO supplier_payments(number,supplier_id,purchase_id,amount_paise,payment_date,paid_from,note) "
                "VALUES(?,?,?,?,?,?,?)", (payment_number,sid,pid,paid,day,paid_from,f"Initial payment for {number}"),
            )
    return jsonify(_purchase_payload(_purchase_row(pid))), 201


@api_bp.get("/purchases/<int:pid>")
def purchase_get(pid):
    row = _purchase_row(pid)
    db = get_db()
    items = db.execute(
        "SELECT pi.*,ct.name FROM purchase_items pi JOIN cylinder_types ct ON ct.id=pi.cylinder_type_id "
        "WHERE pi.purchase_id=? ORDER BY pi.id", (pid,)
    ).fetchall()
    catalog_rows = db.execute(
        "SELECT item_id,item_name,unit,quantity_milli,rate_paise,amount_paise "
        "FROM purchase_catalog_items WHERE purchase_id=? ORDER BY id", (pid,)
    ).fetchall()
    payments = db.execute(
        "SELECT id,number,amount_paise,payment_date,paid_from,note,status FROM supplier_payments "
        "WHERE purchase_id=? ORDER BY payment_date,id", (pid,)
    ).fetchall()
    result = _purchase_payload(row)
    result.update({
        "items": [{"cylinder_type_id":i["cylinder_type_id"],"name":i["name"],"full_in":i["full_in_qty"],
                   "empty_out":i["empty_out_qty"],"new_empty":i["new_empty_qty"],
                   "rate":to_rupees(i["rate_paise"]),"security_rate":to_rupees(i["security_rate_paise"]),
                   "amount":to_rupees(i["amount_paise"])} for i in items],
        "catalog_items": [{"item_id":i["item_id"],"name":i["item_name"],"unit":i["unit"],
                           "quantity":quantity_from_milli(i["quantity_milli"]),
                           "rate":to_rupees(i["rate_paise"]),"amount":to_rupees(i["amount_paise"])}
                          for i in catalog_rows],
        "payments": [{"id":p["id"],"number":p["number"],"amount":to_rupees(p["amount_paise"]),
                      "date":p["payment_date"],"paid_from":p["paid_from"],"note":p["note"],"status":p["status"]} for p in payments],
        "attachment_url": f"/api/purchases/{pid}/attachment" if row["has_attachment"] else None,
        "attachment_name": row["supplier_bill_name"],
        "attachment_mime": row["supplier_bill_mime"],
    })
    return jsonify(result)


@api_bp.post("/purchases/<int:pid>/attachment")
def purchase_attachment_upload(pid):
    """Attach or replace the supplier's original invoice after the purchase is recorded."""
    filename, mime, data = _attachment()
    if not data:
        raise ApiError("Choose a supplier invoice file first.", field="supplier_bill")
    db = get_db()
    with transaction(db):
        exists = db.execute("SELECT id FROM purchases WHERE id=?", (pid,)).fetchone()
        if not exists:
            raise ApiError("Purchase not found.", 404)
        db.execute(
            "UPDATE purchases SET supplier_bill_name=?,supplier_bill_mime=?,supplier_bill_data=? WHERE id=?",
            (filename, mime, data, pid),
        )
    return jsonify({
        "ok": True,
        "attachment_name": filename,
        "attachment_mime": mime,
        "attachment_url": f"/api/purchases/{pid}/attachment",
    })


@api_bp.delete("/purchases/<int:pid>/attachment")
def purchase_attachment_delete(pid):
    """Remove an incorrect attachment while retaining the purchase ledger entry."""
    db = get_db()
    with transaction(db):
        exists = db.execute("SELECT id FROM purchases WHERE id=?", (pid,)).fetchone()
        if not exists:
            raise ApiError("Purchase not found.", 404)
        db.execute(
            "UPDATE purchases SET supplier_bill_name=NULL,supplier_bill_mime=NULL,supplier_bill_data=NULL WHERE id=?",
            (pid,),
        )
    return jsonify({"ok": True})


@api_bp.get("/purchases/<int:pid>/attachment")
def purchase_attachment(pid):
    row = get_db().execute(
        "SELECT supplier_bill_name,supplier_bill_mime,supplier_bill_data FROM purchases WHERE id=?", (pid,)
    ).fetchone()
    if not row:
        raise ApiError("Purchase not found.", 404)
    if not row["supplier_bill_data"]:
        raise ApiError("No supplier bill is attached to this purchase.", 404)
    response = send_file(BytesIO(row["supplier_bill_data"]), mimetype=row["supplier_bill_mime"],
                         download_name=row["supplier_bill_name"], as_attachment=False, max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
