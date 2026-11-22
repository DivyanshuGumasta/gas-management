# APPLY_THESE_EDITS13 — everything per supplier + deposit money back

Paths are relative to `agni-gas/`. Needs edits 12 already applied. Do **A (replace/paste whole files)** first, then **B (find/replace)**.
Start the app once afterwards: it adds the new columns to your existing database by itself and keeps your data.

## What changed
* **Every supplier is fully separate** for each cylinder size. Example: 4 × 5 kg from Supplier 1 and 5 × 5 kg from Supplier 2, each with its
  own *buy price*, own *security deposit*, own *full* and *empty* count, own *deposit held* and own *margin*.
* Each supplier card has **Adjust stock** (type what you really have from them), **Change price & deposit**, **Send back** and **Remove**.
* **Add supplier** now asks for that supplier's price **and** security deposit.
* **New purchase** uses the *selected supplier's* deposit (still editable on the form). A purchase also updates that supplier's empties and
  remembers which supplier every full cylinder came from. "Update purchase prices" saves the deposit on that supplier too.
* **Damaged**: choosing "Bought from" fills each size's deposit with *that supplier's* deposit (still editable). Cylinders are taken from that
  supplier's stock (full → their oldest ones first).
* **Send back = real money.** The popup asks *Money received in: Cash in hand / Bank / UPI* and shows "Money back: Rs …". The refund is saved
  with cash/bank and the Damaged box shows "received back Rs X (cash …, bank …)".
* Stock that is not tied to any supplier (your opening stock, empties customers brought back) shows as **"Not tied to a supplier: N full, N empty"**
  on the size card, so the numbers always add up to the size total.

---

# A. WHOLE FILES

## A1. `api/stock_suppliers.py` — DELETE everything in the file and paste this
```python
"""Stock & Price, part 2: suppliers on each cylinder, damaged cylinders and security deposits.

Everything is kept per supplier: the price you buy at, the security deposit, the full cylinders
(stock_lots.supplier_id), the empty cylinders (supplier_items.empty_qty) and the deposit held.
Stock that is not tied to a supplier (opening stock, empties customers brought back) is shown as "unassigned".

Security deposits are tracked in `cylinder_deposits`, one row per event, never deleted:
    paid       - a purchase of new cylinders (written by api/purchases.py)
    cancelled  - cylinders marked damaged: the deposit is lost
    refunded   - good cylinders sent back to the supplier: the deposit comes back as real money (cash or bank)
Deposit held with a supplier = paid - cancelled - refunded.
"""
from datetime import date

from flask import jsonify

import lots
from db import get_db, transaction
from money import to_rupees
from . import api_bp
from .stock import _cylinder, _movement
from .util import ApiError, RECEIVED_IN, body, int_field, money_field


def _supplier(db, sid):
    row = db.execute("SELECT id, name FROM suppliers WHERE id=? AND active=1", (sid,)).fetchone()
    if not row:
        raise ApiError("Supplier not found.", 404)
    return row


def _optional_supplier(db, data):
    raw = data.get("supplier_id")
    if raw in (None, "", "0"):
        return None
    return _supplier(db, int_field(raw, "Supplier", field="supplier_id", minimum=1))["id"]


def _link(db, tid, sid):
    row = db.execute("SELECT * FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
    if not row:
        raise ApiError("This supplier does not sell this cylinder.", 404)
    return row


def _security(link, cylinder):
    """The deposit for one cylinder from this supplier (their own, else the size's)."""
    return cylinder["security_paise"] if link is None or link["security_paise"] is None else link["security_paise"]


def _default_deposit(db, data, tid, sid, cylinder, key="deposit"):
    if data.get(key) not in (None, ""):
        return money_field(data, key, "Deposit", allow_zero=True)
    link = db.execute("SELECT * FROM supplier_items WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone() if sid else None
    return _security(link, cylinder)


def _deposit_event(db, tid, supplier_id, kind, qty, amount, note=None, received_in=None):
    db.execute("INSERT INTO cylinder_deposits (cylinder_type_id, supplier_id, kind, qty, amount_paise, note, received_in) VALUES (?,?,?,?,?,?,?)",
               (tid, supplier_id, kind, qty, amount, note, received_in))


def _held(db, tid, sid):
    """Deposit (paise) still held with one supplier for one cylinder size. Never below zero."""
    row = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'paid' THEN amount_paise ELSE -amount_paise END),0) FROM cylinder_deposits "
        "WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
    return max(0, row[0])


def _take_empty(db, tid, sid, qty):
    """The supplier's own empties go down (never below 0; the size total is changed by the caller)."""
    if sid:
        db.execute("UPDATE supplier_items SET empty_qty=MAX(0, empty_qty-?) WHERE cylinder_type_id=? AND supplier_id=?", (qty, tid, sid))


def _take_full(db, tid, sid, qty, ref_type, ref_id):
    """Take full cylinders out of one supplier's oldest lots first, then (if short) the oldest of any lot."""
    remaining = qty
    if sid:
        for lot in db.execute(
            "SELECT id, qty_left, unit_cost_paise FROM stock_lots WHERE cylinder_type_id=? AND supplier_id=? AND qty_left>0 "
            "ORDER BY " + lots._ORDER, (tid, sid)).fetchall():
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_left"])
            db.execute("UPDATE stock_lots SET qty_left=qty_left-? WHERE id=?", (take, lot["id"]))
            db.execute("INSERT INTO lot_consumptions (lot_id, cylinder_type_id, ref_type, ref_id, qty, unit_cost_paise) VALUES (?,?,?,?,?,?)",
                       (lot["id"], tid, ref_type, ref_id, take, lot["unit_cost_paise"]))
            remaining -= take
    if remaining > 0:
        lots.consume_fifo(db, tid, remaining, ref_type, ref_id)


@api_bp.get("/stock/extra")
def stock_extra():
    db = get_db()
    types = {r["id"]: r for r in db.execute("SELECT * FROM cylinder_types WHERE active=1")}
    full_from = {(r["t"], r["s"]): r["q"] for r in db.execute(
        "SELECT cylinder_type_id AS t, supplier_id AS s, SUM(qty_left) AS q FROM stock_lots WHERE supplier_id IS NOT NULL GROUP BY 1,2")}
    cylinders = {t: {"suppliers": [], "unassigned_full": r["full_qty"], "unassigned_empty": r["empty_qty"]} for t, r in types.items()}
    for r in db.execute(
        "SELECT si.*, s.name FROM supplier_items si JOIN suppliers s ON s.id=si.supplier_id "
        "WHERE s.active=1 ORDER BY s.name COLLATE NOCASE"
    ):
        c = types.get(r["cylinder_type_id"])
        if not c:
            continue
        t, full = r["cylinder_type_id"], full_from.get((r["cylinder_type_id"], r["supplier_id"]), 0)
        cylinders[t]["suppliers"].append({
            "supplier_id": r["supplier_id"], "name": r["name"], "price": to_rupees(r["purchase_price_paise"]),
            "security": to_rupees(_security(r, c)), "margin": to_rupees(c["sale_price_paise"] - r["purchase_price_paise"]),
            "full": full, "empty": r["empty_qty"], "deposit_held": to_rupees(_held(db, t, r["supplier_id"]))})
        cylinders[t]["unassigned_full"] -= full
        cylinders[t]["unassigned_empty"] -= r["empty_qty"]
    for c in cylinders.values():
        c["unassigned_full"] = max(0, c["unassigned_full"])
        c["unassigned_empty"] = max(0, c["unassigned_empty"])
    totals = {k: v for k, v in db.execute("SELECT kind, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits GROUP BY kind")}
    by_mode = {k: v for k, v in db.execute(
        "SELECT received_in, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits WHERE kind='refunded' GROUP BY 1")}
    damaged = [{"cylinder_type_id": r["id"], "name": r["name"], "qty": r["damaged_qty"], "deposit_lost": to_rupees(r["lost"])} for r in db.execute(
        "SELECT c.id, c.name, c.damaged_qty, COALESCE((SELECT SUM(amount_paise) FROM cylinder_deposits d "
        "WHERE d.cylinder_type_id=c.id AND d.kind='cancelled'),0) AS lost FROM cylinder_types c "
        "WHERE c.active=1 AND c.damaged_qty>0 ORDER BY c.sort_order, c.id")]
    return jsonify({
        "cylinders": cylinders, "damaged": damaged,
        "suppliers": [{"id": r["id"], "name": r["name"]} for r in db.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name COLLATE NOCASE")],
        "deposits": {"paid": to_rupees(totals.get("paid", 0)), "cancelled": to_rupees(totals.get("cancelled", 0)),
                     "refunded": to_rupees(totals.get("refunded", 0)),
                     "refunded_cash": to_rupees(by_mode.get("cash", 0)), "refunded_bank": to_rupees(by_mode.get("bank", 0)),
                     "held": to_rupees(max(0, totals.get("paid", 0) - totals.get("cancelled", 0) - totals.get("refunded", 0)))},
    })


# ---------- which supplier sells this cylinder (each supplier has its own price and deposit) ----------
@api_bp.post("/cylinders/<int:tid>/suppliers")
def cylinder_supplier_add(tid):
    data = body()
    sid = int_field(data.get("supplier_id"), "Supplier", field="supplier_id", minimum=1)
    price = money_field(data, "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        _supplier(db, sid)
        security = c["security_paise"] if data.get("security") in (None, "") else money_field(data, "security", "Security deposit")
        db.execute("INSERT INTO supplier_items (supplier_id, cylinder_type_id, purchase_price_paise, security_paise) VALUES (?,?,?,?) "
                   "ON CONFLICT(supplier_id, cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise, "
                   "security_paise=excluded.security_paise", (sid, tid, price, security))
    return jsonify({"ok": True}), 201


@api_bp.put("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_price(tid, sid):
    data = body()
    price = money_field(data, "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        link = _link(db, tid, sid)
        security = _security(link, c) if data.get("security") in (None, "") else money_field(data, "security", "Security deposit")
        db.execute("UPDATE supplier_items SET purchase_price_paise=?, security_paise=? WHERE supplier_id=? AND cylinder_type_id=?",
                   (price, security, sid, tid))   # cylinders already bought keep the price and deposit they were bought at
    return jsonify({"ok": True})


@api_bp.delete("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_remove(tid, sid):
    db = get_db()
    with transaction(db):   # old purchases keep their supplier; only the link is removed
        db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
    return jsonify({"ok": True})


@api_bp.post("/cylinders/<int:tid>/suppliers/<int:sid>/adjust")
def cylinder_supplier_adjust(tid, sid):
    """Type what you really have FROM THIS SUPPLIER. The size's total changes by the same difference."""
    data = body()
    full = int_field(data.get("full"), "Full cylinders", field="full", maximum=1_000_000)
    empty = int_field(data.get("empty"), "Empty cylinders", field="empty", maximum=1_000_000)
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        link = _link(db, tid, sid)
        have_full = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM stock_lots WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()[0]
        d_full, d_empty = full - have_full, empty - link["empty_qty"]
        if d_full or d_empty:
            if c["full_qty"] + d_full < 0 or c["empty_qty"] + d_empty < 0:
                raise ApiError("That is more than the stock you have in total for this size. Use Adjust stock on the size first.", 409)
            mid = _movement(db, tid, "adjustment", full=d_full, empty=d_empty, note="Adjusted from supplier card")
            db.execute("UPDATE cylinder_types SET full_qty=full_qty+?, empty_qty=empty_qty+? WHERE id=?", (d_full, d_empty, tid))
            db.execute("UPDATE supplier_items SET empty_qty=? WHERE supplier_id=? AND cylinder_type_id=?", (empty, sid, tid))
            if d_full > 0:
                lid = lots.add_lot(db, tid, d_full, link["purchase_price_paise"], date.today().isoformat(), None, "adjustment")
                db.execute("UPDATE stock_lots SET supplier_id=? WHERE id=?", (sid, lid))
            elif d_full < 0:
                _take_full(db, tid, sid, -d_full, "adjustment", mid)
    return jsonify({"ok": True})


# ---------- damaged cylinders ----------
@api_bp.post("/stock/damaged/add")
def damaged_add():
    """Mark cylinders damaged. They leave the empty (or full) stock and their security deposit is cancelled."""
    data = body()
    source = data.get("source") or "empty"
    if source not in ("empty", "full"):
        raise ApiError("Choose whether the cylinders were empty or full.", field="source")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("Select at least one cylinder.")
    db = get_db()
    with transaction(db):
        supplier_id = _optional_supplier(db, data)
        for it in items:
            tid = int_field(it.get("cylinder_type_id"), "Cylinder", minimum=1)
            c = _cylinder(db, tid)
            qty = int_field(it.get("qty"), f"{c['name']} count", field=f"q{tid}", minimum=1, maximum=1_000_000)
            have = c["empty_qty"] if source == "empty" else c["full_qty"]
            if qty > have:
                raise ApiError(f"{c['name']}: only {have} {source} cylinder(s) in stock.", 409, field=f"q{tid}")
            dep = _default_deposit(db, it, tid, supplier_id, c)
            mid = _movement(db, tid, "damaged", full=-qty if source == "full" else 0,
                            empty=-qty if source == "empty" else 0, damaged=qty, note="Marked damaged")
            db.execute(f"UPDATE cylinder_types SET {source}_qty={source}_qty-?, damaged_qty=damaged_qty+? WHERE id=?", (qty, qty, tid))
            if source == "full":
                _take_full(db, tid, supplier_id, qty, "damaged", mid)
            else:
                _take_empty(db, tid, supplier_id, qty)
            _deposit_event(db, tid, supplier_id, "cancelled", qty, qty * dep, "Cylinder damaged")
    return jsonify({"ok": True})


# ---------- empty cylinders sent back to the supplier ----------
@api_bp.post("/cylinders/<int:tid>/send-back")
def cylinder_send_back(tid):
    """Good empty cylinders go back to a supplier and the security deposit comes back as real money."""
    data = body()
    mode = data.get("received_in") or "cash"
    if mode not in RECEIVED_IN:
        raise ApiError("Choose where the money was received.", field="received_in")
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        qty = int_field(data.get("qty"), "Cylinders", field="qty", minimum=1, maximum=1_000_000)
        if qty > c["empty_qty"]:
            raise ApiError(f"Only {c['empty_qty']} empty cylinder(s) in stock.", 409, field="qty")
        supplier_id = _optional_supplier(db, data)
        dep = _default_deposit(db, data, tid, supplier_id, c)
        _movement(db, tid, "sent_back", empty=-qty, note="Sent back to supplier")
        db.execute("UPDATE cylinder_types SET empty_qty=empty_qty-? WHERE id=?", (qty, tid))
        _take_empty(db, tid, supplier_id, qty)
        _deposit_event(db, tid, supplier_id, "refunded", qty, qty * dep, "Sent back to supplier", mode)
    return jsonify({"ok": True})
```

## A2. `static/js/stock_extra.js` — DELETE everything in the file and paste this
```javascript
// Stock & Price, part 2: suppliers on each cylinder, the damaged-cylinders area and sending cylinders back.
// Loads after stock.js and re-draws these parts every time stock.js has drawn the page.
(function () {
  const { esc, fmt } = UI;
  const money = (v) => fmt.money(v);
  const $ = (id) => document.getElementById(id);
  let ext = { cylinders: {}, damaged: [], suppliers: [], deposits: {} };
  const supOf = (tid) => (ext.cylinders[tid] && ext.cylinders[tid].suppliers) || [];

  /* ---------- a tiny popup helper ---------- */
  function popup(title, intro, bodyHtml, submitLabel, run, success, onOpen) {
    const body = UI.openModal(title);
    body.innerHTML = '<form novalidate autocomplete="off">' + (intro ? '<p class="st-intro hint">' + esc(intro) + "</p>" : "") + bodyHtml +
      '<div class="form-error" role="alert"></div><div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-dark">' + esc(submitLabel) + "</button></div></form>";
    const form = body.querySelector("form"), err = body.querySelector(".form-error");
    if (onOpen) onOpen(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); err.textContent = "";
      const btn = form.querySelector("[type=submit]"); btn.disabled = true;
      try { await run(form); UI.closeModal(); StockUI.toast(success); StockUI.load(); }
      catch (ex) { err.textContent = ex.message || "Could not save."; btn.disabled = false; }
    });
  }
  const moneyBox = (name, label, value) => '<label class="field"><span>' + label + '</span><div class="amt"><i>Rs</i><input name="' + name +
    '" inputmode="decimal" autocomplete="off" placeholder="0" value="' + esc(value == null ? "" : value) + '"></div></label>';
  const supplierSelect = (name, label, list, blank) => '<label class="field"><span>' + label + '</span><select name="' + name + '" class="amt">' +
    (blank ? '<option value="">' + blank + "</option>" : "") + list.map((s) => '<option value="' + s.id + '">' + esc(s.name) + "</option>").join("") + "</select></label>";
  const cyl = (id) => StockUI.state.cylinders.find((c) => c.id === id);

  /* ---------- suppliers on each cylinder card (every number is that supplier's own) ---------- */
  function supplierPanel(c) {
    const list = supOf(c.id), x = ext.cylinders[c.id] || {};
    const cards = list.map((s) => {
      const neg = Number(s.margin) < 0;
      return '<div class="st-sup" data-tid="' + c.id + '" data-sid="' + s.supplier_id + '">' +
        '<div class="st-sup-top"><b>' + esc(s.name) + "</b></div>" +
        '<div class="st-sup-grid"><div><small>Buy at</small><b>' + money(s.price) + "</b></div>" +
        '<div><small>Security deposit</small><b>' + money(s.security) + "</b></div>" +
        '<div><small>Margin</small><b class="' + (neg ? "neg" : "pos") + '">' + money(s.margin) + "</b></div>" +
        "<div><small>Full</small><b>" + s.full + "</b></div><div><small>Empty</small><b>" + s.empty + "</b></div>" +
        "<div><small>Deposit held</small><b>" + money(s.deposit_held) + "</b></div></div>" +
        '<div class="st-sup-btns"><button type="button" class="link" data-xact="sup-adjust">Adjust stock</button>' +
        '<button type="button" class="link" data-xact="sup-edit">Change price &amp; deposit</button>' +
        '<button type="button" class="link" data-xact="sup-sendback">Send back</button>' +
        '<button type="button" class="link del" data-xact="sup-remove">Remove</button></div></div>';
    }).join("");
    const loose = (x.unassigned_full || x.unassigned_empty)
      ? '<p class="st-supplier">Not tied to a supplier: <b>' + (x.unassigned_full || 0) + " full, " + (x.unassigned_empty || 0) + " empty</b></p>" : "";
    return '<div class="st-sups"><div class="st-sups-head"><b>Suppliers</b>' +
      '<button type="button" class="btn btn-white" data-xact="sup-add" data-tid="' + c.id + '">＋ Add supplier</button></div>' +
      (cards || '<p class="st-supplier">No supplier sells this size yet.</p>') + loose + "</div>";
  }
  function decorateCards() {
    StockUI.state.cylinders.forEach((c) => {
      const card = $("cyl-" + c.id); if (!card) return;
      const old = card.querySelector(".st-supplier"); if (old) old.remove();
      const acts = card.querySelector(".st-actions");
      acts.insertAdjacentHTML("beforebegin", supplierPanel(c));
      acts.insertAdjacentHTML("afterbegin", '<button class="btn btn-white" data-xact="send-back" data-tid="' + c.id + '" type="button">Send back</button>');
    });
  }
  function addSupplier(tid) {
    const c = cyl(tid), linked = supOf(tid).map((s) => s.supplier_id);
    const free = ext.suppliers.filter((s) => !linked.includes(s.id));
    if (!free.length) { StockUI.toast(ext.suppliers.length ? "Every supplier already sells this size." : "Add a supplier first (Suppliers & Purchases).", true); return; }
    popup("Add supplier · " + c.name, "Each supplier has their own price and security deposit for this cylinder.",
      supplierSelect("supplier_id", "Supplier", free) +
      '<div class="two">' + moneyBox("purchase_price", "Their price (full cylinder)") + moneyBox("security", "Their security deposit", c.security) + "</div>", "Add supplier",
      (f) => Api.post("/api/cylinders/" + tid + "/suppliers", { supplier_id: f.elements.supplier_id.value,
        purchase_price: f.elements.purchase_price.value.trim(), security: f.elements.security.value.trim() }),
      "Supplier added");
  }
  function editSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid);
    popup("Change price & deposit · " + s.name, "Applies to cylinders you buy from now on. Cylinders already bought keep the price they were bought at.",
      '<div class="two">' + moneyBox("purchase_price", "Their price (full cylinder)", s.price) + moneyBox("security", "Their security deposit", s.security) + "</div>", "Save",
      (f) => Api.put("/api/cylinders/" + tid + "/suppliers/" + sid, { purchase_price: f.elements.purchase_price.value.trim(), security: f.elements.security.value.trim() }),
      "Saved");
  }
  function adjustSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid), c = cyl(tid);
    popup("Adjust stock · " + c.name + " from " + s.name, "Type what you really have from this supplier. The difference is saved in Stock history and added to the size's total.",
      '<div class="two"><label class="field"><span>Full cylinders</span><div class="amt"><input name="full" type="number" min="0" step="1" value="' + s.full + '"><i>cyl</i></div></label>' +
      '<label class="field"><span>Empty cylinders</span><div class="amt"><input name="empty" type="number" min="0" step="1" value="' + s.empty + '"><i>cyl</i></div></label></div>', "Save stock",
      (f) => Api.post("/api/cylinders/" + tid + "/suppliers/" + sid + "/adjust", { full: f.elements.full.value.trim(), empty: f.elements.empty.value.trim() }),
      "Stock updated");
  }
  function removeSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid);
    Cust.openConfirm({ title: "Remove " + s.name + "?", danger: true, confirmLabel: "Remove",
      message: s.name + " will no longer be offered for " + cyl(tid).name + " in new purchases. Past purchases stay as they are.",
      onConfirm: async () => { await Api.del("/api/cylinders/" + tid + "/suppliers/" + sid); StockUI.toast("Supplier removed"); StockUI.load(); } });
  }

  /* ---------- send back ---------- */
  function sendBack(tid, sid) {
    const c = cyl(tid), s = sid ? supOf(tid).find((x) => x.supplier_id === sid) : null;
    const opts = ext.suppliers.map((p) => '<option value="' + p.id + '"' + (p.id === sid ? " selected" : "") + ">" + esc(p.name) + "</option>").join("");
    popup("Send back · " + c.name, "Good empty cylinders going back to a supplier. The security deposit comes back to you as money.",
      '<label class="field"><span>Sent to</span><select name="supplier_id" class="amt"><option value="">Not sure / skip</option>' + opts + "</select></label>" +
      '<div class="two"><label class="field"><span>How many</span><div class="amt"><input name="qty" type="number" min="1" step="1" inputmode="numeric" value="1"><i>cyl</i></div></label>' +
      moneyBox("deposit", "Deposit per cylinder", s ? s.security : c.security) + "</div>" +
      '<label class="field"><span>Money received in</span><select name="received_in" class="amt"><option value="cash">Cash in hand</option><option value="bank">Bank / UPI</option></select></label>' +
      '<p class="hint st-refund" id="st-refund">Money back: Rs 0</p><p class="hint">You have ' + c.empty + " empty " + esc(c.name) + " cylinder(s) in total.</p>", "Send back & receive money",
      (f) => Api.post("/api/cylinders/" + tid + "/send-back", { qty: f.elements.qty.value.trim(), deposit: f.elements.deposit.value.trim(),
        supplier_id: f.elements.supplier_id.value, received_in: f.elements.received_in.value }),
      "Cylinders sent back, deposit received",
      (f) => {
        const calc = () => { f.querySelector("#st-refund").textContent = "Money back: " + money(((Number(f.elements.qty.value) || 0) * (Number(f.elements.deposit.value) || 0)).toFixed(2)); };
        f.elements.supplier_id.addEventListener("change", () => {
          const row = supOf(tid).find((x) => String(x.supplier_id) === f.elements.supplier_id.value);
          f.elements.deposit.value = row ? row.security : c.security; calc();
        });
        f.addEventListener("input", calc); calc();
      });
  }

  /* ---------- damaged cylinders ---------- */
  function renderDamagedArea() {
    const d = ext.deposits || {};
    $("st-damaged-list").innerHTML = ext.damaged.length ? ext.damaged.map((r) =>
      '<div class="st-dmg-chip"><b>' + r.qty + "</b> × " + esc(r.name) + (Number(r.deposit_lost) ? "<small>deposit lost " + money(r.deposit_lost) + "</small>" : "") + "</div>").join("")
      : '<span class="card-sub">No damaged cylinders.</span>';
    $("st-deposit-line").innerHTML = "Deposits held with suppliers <b>" + money(d.held) + "</b> · lost on damaged <b>" + money(d.cancelled) +
      "</b> · received back <b>" + money(d.refunded) + "</b>" +
      (Number(d.refunded) ? " (cash " + money(d.refunded_cash) + ", bank " + money(d.refunded_bank) + ")" : "");
  }
  function addDamaged() {
    const cyls = StockUI.state.cylinders;
    if (!cyls.length) { StockUI.toast("Add a cylinder first.", true); return; }
    const rows = cyls.map((c) => '<div class="st-dmg-row" data-id="' + c.id + '">' +
      '<label class="st-dmg-pick"><input type="checkbox" name="pick' + c.id + '"><span>' + esc(c.name) + "<small>" + c.empty + " empty · " + c.full + " full</small></span></label>" +
      '<div class="amt"><input name="q' + c.id + '" type="number" min="1" step="1" inputmode="numeric" value="1" disabled><i>cyl</i></div>' +
      '<div class="amt"><i>Rs</i><input name="d' + c.id + '" inputmode="decimal" value="' + esc(c.security) + '" disabled></div></div>').join("");
    popup("Add damaged cylinder", "Tick the cylinders that are damaged. They leave your stock and their security deposit is cancelled, because they can no longer be used.",
      '<label class="field"><span>They were</span><select name="source" class="amt"><option value="empty">Empty</option><option value="full">Full</option></select></label>' +
      supplierSelect("supplier_id", "Bought from", ext.suppliers, "Not sure / skip") +
      '<div class="st-dmg-head"><span>Cylinder</span><span>How many</span><span>Deposit each</span></div>' + rows +
      '<p class="st-dmg-total hint" id="st-dmg-total">Deposit cancelled: Rs 0</p>', "Update damaged stock",
      async (f) => {
        const items = cyls.filter((c) => f.elements["pick" + c.id].checked).map((c) => ({
          cylinder_type_id: c.id, qty: f.elements["q" + c.id].value.trim(), deposit: f.elements["d" + c.id].value.trim() }));
        if (!items.length) throw new Error("Tick at least one cylinder.");
        await Api.post("/api/stock/damaged/add", { source: f.elements.source.value, supplier_id: f.elements.supplier_id.value, items });
      }, "Damaged stock updated",
      (f) => {
        const total = () => {
          const t = cyls.reduce((a, c) => a + (f.elements["pick" + c.id].checked ? (Number(f.elements["q" + c.id].value) || 0) * (Number(f.elements["d" + c.id].value) || 0) : 0), 0);
          f.querySelector("#st-dmg-total").textContent = "Deposit cancelled: " + money(t.toFixed(2));
        };
        f.elements.supplier_id.addEventListener("change", () => {      // each supplier has its own deposit
          cyls.forEach((c) => {
            const row = supOf(c.id).find((x) => String(x.supplier_id) === f.elements.supplier_id.value);
            f.elements["d" + c.id].value = row ? row.security : c.security;
          });
          total();
        });
        f.addEventListener("change", (e) => {
          const m = /^pick(\d+)$/.exec(e.target.name || "");
          if (m) { f.elements["q" + m[1]].disabled = f.elements["d" + m[1]].disabled = !e.target.checked; }
          total();
        });
        f.addEventListener("input", total);
      });
  }

  /* ---------- wiring ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-xact]"); if (!b) return;
    const sup = b.closest(".st-sup");
    const tid = Number(b.dataset.tid || (sup && sup.dataset.tid)), sid = sup ? Number(sup.dataset.sid) : 0;
    ({ "sup-add": () => addSupplier(tid), "sup-edit": () => editSupplier(tid, sid), "sup-remove": () => removeSupplier(tid, sid),
       "sup-adjust": () => adjustSupplier(tid, sid), "sup-sendback": () => sendBack(tid, sid), "send-back": () => sendBack(tid, 0) })[b.dataset.xact]();
  });
  $("st-damaged-add").addEventListener("click", addDamaged);
  document.addEventListener("stock:rendered", async () => {
    try { ext = await Api.get("/api/stock/extra"); } catch (e) { return; }
    decorateCards();
    renderDamagedArea();
  });
})();
```

## A3. `tests/test_stock_suppliers.py` — DELETE everything in the file and paste this (optional but recommended)
```python
"""v0.4.4: suppliers per cylinder, damaged cylinders, security deposits - everything per supplier."""
import importlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class StockSupplierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.tmp.name
        os.environ["AGNI_DB"] = os.path.join(self.tmp.name, "ss.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        db.init_db()
        self.conn = db.connect()
        self.conn.execute("INSERT INTO suppliers (name, gstin) VALUES ('Alpha', '22AAAAA0000A1Z5'), ('Beta', '22BBBBB0000B1Z5')")
        self.tid = self.conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]
        self.conn.execute("UPDATE cylinder_types SET full_qty=0, empty_qty=3, security_paise=250000, sale_price_paise=150000 WHERE id=?", (self.tid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def row(self):
        return self.conn.execute("SELECT * FROM cylinder_types WHERE id=?", (self.tid,)).fetchone()

    def sups(self):
        return {s["name"]: s for s in self.api("get", "/api/stock/extra")[1]["cylinders"][str(self.tid)]["suppliers"]}

    def two_suppliers(self):
        """4 x 5 kg from Alpha (1300, deposit 2500) and 5 x 5 kg from Beta (1350, deposit 3000)."""
        for sid, price, dep, qty in ((1, "1300", "2500", 4), (2, "1350", "3000", 5)):
            self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers",
                                      {"supplier_id": sid, "purchase_price": price, "security": dep})[0], 201)
            code, p = self.api("post", "/api/purchases", {"supplier_id": sid, "items": [
                {"cylinder_type_id": self.tid, "full_in": qty, "new_full": qty, "rate": price, "deposit": dep}]})
            self.assertEqual(code, 201, p)

    def test_each_supplier_has_own_price_deposit_and_stock(self):
        self.two_suppliers()
        s = self.sups()
        self.assertEqual((s["Alpha"]["price"], s["Alpha"]["security"], s["Alpha"]["full"], s["Alpha"]["margin"]),
                         ("1300.00", "2500.00", 4, "200.00"))
        self.assertEqual((s["Beta"]["price"], s["Beta"]["security"], s["Beta"]["full"], s["Beta"]["margin"]),
                         ("1350.00", "3000.00", 5, "150.00"))
        self.assertEqual((s["Alpha"]["deposit_held"], s["Beta"]["deposit_held"]), ("10000.00", "15000.00"))
        self.assertEqual(self.row()["full_qty"], 9)
        # the purchase form asks for each supplier's own deposit
        self.assertEqual(self.api("get", "/api/purchases/options?supplier_id=2")[1][0]["security_rate"], "3000.00")
        self.assertEqual(self.api("get", "/api/purchases/options?supplier_id=1")[1][0]["security_rate"], "2500.00")

    def test_change_price_and_deposit_for_one_supplier_only(self):
        self.two_suppliers()
        self.assertEqual(self.api("put", f"/api/cylinders/{self.tid}/suppliers/2", {"purchase_price": "1400", "security": "3200"})[0], 200)
        s = self.sups()
        self.assertEqual((s["Beta"]["price"], s["Beta"]["security"]), ("1400.00", "3200.00"))
        self.assertEqual((s["Alpha"]["price"], s["Alpha"]["security"]), ("1300.00", "2500.00"))
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers", {"supplier_id": 1})[0], 400)
        self.api("delete", f"/api/cylinders/{self.tid}/suppliers/1")
        self.assertEqual(list(self.sups()), ["Beta"])

    def test_purchase_tracks_supplier_empties(self):
        self.two_suppliers()
        self.api("post", "/api/purchases", {"supplier_id": 1, "items": [{"cylinder_type_id": self.tid, "full_in": 0, "new_empty": 2, "rate": "0", "deposit": "2500"}]})
        self.assertEqual(self.sups()["Alpha"]["empty"], 2)

    def test_adjust_one_supplier(self):
        self.two_suppliers()
        code, _ = self.api("post", f"/api/cylinders/{self.tid}/suppliers/1/adjust", {"full": "6", "empty": "1"})
        self.assertEqual(code, 200)
        s = self.sups()
        self.assertEqual((s["Alpha"]["full"], s["Alpha"]["empty"], s["Beta"]["full"]), (6, 1, 5))
        r = self.row()
        self.assertEqual((r["full_qty"], r["empty_qty"]), (11, 4))
        self.api("post", f"/api/cylinders/{self.tid}/suppliers/1/adjust", {"full": "1", "empty": "1"})
        self.assertEqual(self.sups()["Alpha"]["full"], 1)
        self.assertEqual(self.row()["full_qty"], 6)

    def test_damaged_empty_cancels_that_suppliers_deposit(self):
        self.two_suppliers()
        self.api("post", f"/api/cylinders/{self.tid}/suppliers/2/adjust", {"full": "5", "empty": "2"})
        code, _ = self.api("post", "/api/stock/damaged/add", {"source": "empty", "supplier_id": "2", "items": [{"cylinder_type_id": self.tid, "qty": "2"}]})
        self.assertEqual(code, 200)
        r = self.row()
        self.assertEqual((r["empty_qty"], r["damaged_qty"]), (3, 2))
        d = self.api("get", "/api/stock/extra")[1]
        self.assertEqual(d["deposits"]["cancelled"], "6000.00")        # Beta's own deposit (3000 x 2), not the size's
        self.assertEqual(self.sups()["Beta"]["empty"], 0)
        self.assertEqual(self.sups()["Beta"]["deposit_held"], "9000.00")
        self.assertEqual(self.api("post", "/api/stock/damaged/add", {"source": "empty", "items": [{"cylinder_type_id": self.tid, "qty": "9"}]})[0], 409)

    def test_damaged_full_takes_from_that_suppliers_lots(self):
        self.two_suppliers()
        self.api("post", "/api/stock/damaged/add", {"source": "full", "supplier_id": "2", "items": [{"cylinder_type_id": self.tid, "qty": "2", "deposit": "100"}]})
        s = self.sups()
        self.assertEqual((s["Alpha"]["full"], s["Beta"]["full"]), (4, 3))
        self.assertEqual(self.api("get", "/api/stock/extra")[1]["deposits"]["cancelled"], "200.00")

    def test_send_back_refunds_real_money_to_cash_or_bank(self):
        self.two_suppliers()
        code, _ = self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "2", "supplier_id": "2", "received_in": "bank"})
        self.assertEqual(code, 200)
        self.assertEqual(self.row()["empty_qty"], 1)
        dep = self.api("get", "/api/stock/extra")[1]["deposits"]
        self.assertEqual((dep["refunded"], dep["refunded_bank"], dep["refunded_cash"]), ("6000.00", "6000.00", "0.00"))
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "1", "received_in": "x"})[0], 400)
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "5"})[0], 409)

    def test_lots_remember_supplier(self):
        self.two_suppliers()
        rows = self.conn.execute("SELECT supplier_id, qty_left FROM stock_lots ORDER BY supplier_id").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [(1, 4), (2, 5)])


if __name__ == "__main__":
    unittest.main()
```

## A4. `static/css/stock.css` — paste at the very END of the file
```css

/* ---- v0.4.4: per-supplier cards ---- */
.st-sup-top { margin-bottom: 8px; }
.st-sup-grid { grid-template-columns: repeat(3, 1fr); row-gap: 8px; }
.st-sup-btns { margin-top: 10px; padding-top: 8px; border-top: 1px solid #e3e2f0; flex-wrap: wrap; }
.st-refund { font-weight: 700; color: var(--green); }
```

---

# B. FIND / REPLACE EDITS

## B1. `db.py` — New columns: each supplier's own deposit + empty count, and which supplier each full-cylinder lot came from
**Find:**
```
        # v0.4.3: deposits already paid on earlier purchases go into the deposit history (only when it is empty).
```
**Replace with:**
```
        # v0.4.4: everything per supplier. Own deposit and empty count on the supplier link, supplier on each lot,
        # and where a refunded deposit was received (cash / bank).
        if "security_paise" not in [r[1] for r in conn.execute("PRAGMA table_info(supplier_items)")]:
            conn.execute("ALTER TABLE supplier_items ADD COLUMN security_paise INTEGER")
            conn.execute("UPDATE supplier_items SET security_paise=(SELECT security_paise FROM cylinder_types WHERE id=supplier_items.cylinder_type_id)")
        if "empty_qty" not in [r[1] for r in conn.execute("PRAGMA table_info(supplier_items)")]:
            conn.execute("ALTER TABLE supplier_items ADD COLUMN empty_qty INTEGER NOT NULL DEFAULT 0")
        if "supplier_id" not in [r[1] for r in conn.execute("PRAGMA table_info(stock_lots)")]:
            conn.execute("ALTER TABLE stock_lots ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)")
        conn.execute("UPDATE stock_lots SET supplier_id=(SELECT supplier_id FROM purchases WHERE id=stock_lots.purchase_id) "
                     "WHERE supplier_id IS NULL AND purchase_id IS NOT NULL")
        if "received_in" not in [r[1] for r in conn.execute("PRAGMA table_info(cylinder_deposits)")]:
            conn.execute("ALTER TABLE cylinder_deposits ADD COLUMN received_in TEXT")
        # v0.4.3: deposits already paid on earlier purchases go into the deposit history (only when it is empty).
```

## B2. `api/purchases.py` — Purchase form: the deposit comes from the selected supplier (part 1 of 2: ask for it)
**Find:**
```
"si.purchase_price_paise AS supplier_price FROM cylinder_types ct "
```
**Replace with:**
```
"si.purchase_price_paise AS supplier_price, COALESCE(si.security_paise,ct.security_paise) AS supplier_security FROM cylinder_types ct "
```

## B3. `api/purchases.py` — Purchase form: the deposit comes from the selected supplier (part 2 of 2: send it)
**Find:**
```
"security_rate": to_rupees(r["security_paise"]),
```
**Replace with:**
```
"security_rate": to_rupees(r["supplier_security"]),
```

## B4. `api/purchases.py` — Saving a purchase: if no deposit was typed, use this supplier's deposit
**Find:**
```
            security_rate = ct["security_paise"]
```
**Replace with:**
```
            own = db.execute("SELECT security_paise FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid)).fetchone()
            security_rate = ct["security_paise"] if own is None or own[0] is None else own[0]
```

## B5. `api/purchases.py` — Each supplier's own empty cylinders go up/down with a purchase (add these lines right AFTER the `UPDATE cylinder_types SET full_qty=...` statement, before the `INSERT INTO stock_movements` one)
**Find:**
```
                (item["full_in"],item["empty_out"],item["new_empty"],item["id"]),
            )
```
**Replace with:**
```
                (item["full_in"],item["empty_out"],item["new_empty"],item["id"]),
            )
            db.execute(   # this supplier's own empties (never below 0)
                "UPDATE supplier_items SET empty_qty=MAX(0, empty_qty-?+?) WHERE supplier_id=? AND cylinder_type_id=?",
                (item["empty_out"], item["new_empty"], sid, item["id"]),
            )
```

## B6. `api/purchases.py` — The full cylinders of a purchase remember which supplier they came from (insert BEFORE the `if item["new_full"] or item["new_empty"]:` line you added last time)
**Find:**
```
            if item["new_full"] or item["new_empty"]:      # deposit paid on brand-new cylinders
```
**Replace with:**
```
            db.execute("UPDATE stock_lots SET supplier_id=? WHERE purchase_id=? AND cylinder_type_id=?", (sid, pid, item["id"]))
            if item["new_full"] or item["new_empty"]:      # deposit paid on brand-new cylinders
```

## B7. `api/purchases.py` — "Update purchase prices" also saves the deposit on this supplier
**Find:**
```
                db.execute("UPDATE cylinder_types SET security_paise=? WHERE id=?", (item["security_rate"],item["id"]))
```
**Replace with:**
```
                db.execute("UPDATE cylinder_types SET security_paise=? WHERE id=?", (item["security_rate"],item["id"]))
                db.execute("UPDATE supplier_items SET security_paise=? WHERE supplier_id=? AND cylinder_type_id=?",
                           (item["security_rate"], sid, item["id"]))
```

---
## Things I decided (tell me to change any)
* **Refunded deposit is not added to the supplier's balance.** You paid the deposit as part of that purchase, so when it comes back as cash
  your balance with the supplier is already correct. It is only recorded as money received (cash or bank). When Reports/cash book is built, it
  will read these records (`cylinder_deposits`, kind `refunded`).
* **Adjust stock on a supplier card** changes the size's total by the same difference (like Adjust stock on the size) and writes a history line.
  Extra full cylinders get that supplier's current price as their cost.
* **Existing data**: each supplier link gets the size's current deposit as its starting deposit; old lots are matched to their purchase's supplier.
  Empties per supplier start at 0 (nobody recorded them), so they show under "Not tied to a supplier" until you use Adjust stock or buy/return.
* **Customer-returned empties** can't be tied to a supplier yet. When the Sales screen is built I will attach them to the supplier of the lot the
  cylinder was sold from.
* Suite is now 38 tests, all passing; I also ran it in a browser against a database made by the previous version.
