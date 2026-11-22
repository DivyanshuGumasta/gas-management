# APPLY_THESE_EDITS12 — suppliers on cylinders, damaged cylinders, security deposits

Paths are relative to `agni-gas/`. Do **A (new files)** first, then **B (edits)** in order. Then start the app once
(it creates the new table by itself). Needs v0.4.2 (Stock & Price backend) already in your folder.

## What you get
* **Each cylinder card now has a "Suppliers" section.** `＋ Add supplier` links a supplier and their price. Every supplier gets
  its own small card: *Buy at*, *Margin* (your sale price minus their price), *Full from them* (how many full cylinders still on
  the shelf came from them) and *Deposit held*. `Change price` / `Remove` on each.
* **Damaged cylinders area**: tap **Add damaged cylinder**, tick the sizes, type how many, confirm. They leave your stock and
  their security deposit is **cancelled**. The box shows what is damaged and the deposit totals.
* **Send back** button on each cylinder card: good empty cylinders going back to a supplier; the deposit is **refunded**.
* **Deposit history** (`cylinder_deposits`): every deposit paid (each purchase of new cylinders), cancelled, or refunded is kept
  forever. Deposits on purchases you made before this update are filled in automatically.

---

# A. NEW FILES / NEW BLOCKS

## A1. New file `api/stock_suppliers.py`
Create this file with exactly this content:

```python
"""Stock & Price, part 2: which supplier sells a cylinder, damaged cylinders and security deposits.

Security deposits are tracked in `cylinder_deposits`, one row per event, never deleted:
    paid       - a purchase of new cylinders (written by api/purchases.py)
    cancelled  - cylinders marked damaged: the deposit is lost
    refunded   - good cylinders sent back to the supplier: the deposit comes back
Deposit held with a supplier = paid - cancelled - refunded.
"""
from flask import jsonify

import lots
from db import get_db, transaction
from money import to_rupees
from . import api_bp
from .stock import _cylinder, _movement
from .util import ApiError, body, int_field, money_field


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


def _deposit_event(db, tid, supplier_id, kind, qty, amount, note=None):
    db.execute("INSERT INTO cylinder_deposits (cylinder_type_id, supplier_id, kind, qty, amount_paise, note) VALUES (?,?,?,?,?,?)",
               (tid, supplier_id, kind, qty, amount, note))


def _held(db, tid, sid):
    """Deposit (paise) still held with one supplier for one cylinder size. Never below zero."""
    row = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'paid' THEN amount_paise ELSE -amount_paise END),0) FROM cylinder_deposits "
        "WHERE cylinder_type_id=? AND supplier_id=?", (tid, sid)).fetchone()
    return max(0, row[0])


@api_bp.get("/stock/extra")
def stock_extra():
    db = get_db()
    sale = {r["id"]: r["sale_price_paise"] for r in db.execute("SELECT id, sale_price_paise FROM cylinder_types WHERE active=1")}
    full_from = {(r["t"], r["s"]): r["q"] for r in db.execute(
        "SELECT l.cylinder_type_id AS t, p.supplier_id AS s, SUM(l.qty_left) AS q FROM stock_lots l "
        "JOIN purchases p ON p.id=l.purchase_id GROUP BY 1,2")}
    cylinders = {}
    for r in db.execute(
        "SELECT si.cylinder_type_id AS t, s.id AS sid, s.name, si.purchase_price_paise AS price FROM supplier_items si "
        "JOIN suppliers s ON s.id=si.supplier_id JOIN cylinder_types c ON c.id=si.cylinder_type_id "
        "WHERE s.active=1 AND c.active=1 ORDER BY s.name COLLATE NOCASE"
    ):
        cylinders.setdefault(r["t"], []).append({
            "supplier_id": r["sid"], "name": r["name"], "price": to_rupees(r["price"]),
            "margin": to_rupees(sale.get(r["t"], 0) - r["price"]),
            "full": full_from.get((r["t"], r["sid"]), 0), "deposit_held": to_rupees(_held(db, r["t"], r["sid"]))})
    totals = {k: v for k, v in db.execute("SELECT kind, COALESCE(SUM(amount_paise),0) FROM cylinder_deposits GROUP BY kind")}
    damaged = [{"cylinder_type_id": r["id"], "name": r["name"], "qty": r["damaged_qty"],
                "deposit_lost": to_rupees(r["lost"])} for r in db.execute(
        "SELECT c.id, c.name, c.damaged_qty, COALESCE((SELECT SUM(amount_paise) FROM cylinder_deposits d "
        "WHERE d.cylinder_type_id=c.id AND d.kind='cancelled'),0) AS lost FROM cylinder_types c "
        "WHERE c.active=1 AND c.damaged_qty>0 ORDER BY c.sort_order, c.id")]
    return jsonify({
        "cylinders": cylinders, "damaged": damaged,
        "suppliers": [{"id": r["id"], "name": r["name"]} for r in db.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name COLLATE NOCASE")],
        "deposits": {"paid": to_rupees(totals.get("paid", 0)), "cancelled": to_rupees(totals.get("cancelled", 0)),
                     "refunded": to_rupees(totals.get("refunded", 0)),
                     "held": to_rupees(max(0, totals.get("paid", 0) - totals.get("cancelled", 0) - totals.get("refunded", 0)))},
    })


# ---------- which supplier sells this cylinder ----------
@api_bp.post("/cylinders/<int:tid>/suppliers")
def cylinder_supplier_add(tid):
    data = body()
    sid = int_field(data.get("supplier_id"), "Supplier", field="supplier_id", minimum=1)
    price = money_field(data, "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        _cylinder(db, tid)
        _supplier(db, sid)
        db.execute("INSERT INTO supplier_items (supplier_id, cylinder_type_id, purchase_price_paise) VALUES (?,?,?) "
                   "ON CONFLICT(supplier_id, cylinder_type_id) DO UPDATE SET purchase_price_paise=excluded.purchase_price_paise",
                   (sid, tid, price))
    return jsonify({"ok": True}), 201


@api_bp.put("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_price(tid, sid):
    price = money_field(body(), "purchase_price", "Purchase price", allow_zero=False)
    db = get_db()
    with transaction(db):
        cur = db.execute("UPDATE supplier_items SET purchase_price_paise=? WHERE supplier_id=? AND cylinder_type_id=?", (price, sid, tid))
        if not cur.rowcount:
            raise ApiError("This supplier does not sell this cylinder.", 404)
    return jsonify({"ok": True})


@api_bp.delete("/cylinders/<int:tid>/suppliers/<int:sid>")
def cylinder_supplier_remove(tid, sid):
    db = get_db()
    with transaction(db):   # old purchases keep their supplier; only the link is removed
        db.execute("DELETE FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (sid, tid))
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
            dep = c["security_paise"] if it.get("deposit") in (None, "") else money_field(it, "deposit", "Deposit", allow_zero=True)
            mid = _movement(db, tid, "damaged", full=-qty if source == "full" else 0,
                            empty=-qty if source == "empty" else 0, damaged=qty, note="Marked damaged")
            db.execute(f"UPDATE cylinder_types SET {source}_qty={source}_qty-?, damaged_qty=damaged_qty+? WHERE id=?", (qty, qty, tid))
            if source == "full":
                lots.consume_fifo(db, tid, qty, "damaged", mid)
            _deposit_event(db, tid, supplier_id, "cancelled", qty, qty * dep, "Cylinder damaged")
    return jsonify({"ok": True})


# ---------- empty cylinders sent back to the supplier ----------
@api_bp.post("/cylinders/<int:tid>/send-back")
def cylinder_send_back(tid):
    """Good empty cylinders go back to a supplier and the security deposit comes back."""
    data = body()
    db = get_db()
    with transaction(db):
        c = _cylinder(db, tid)
        qty = int_field(data.get("qty"), "Cylinders", field="qty", minimum=1, maximum=1_000_000)
        if qty > c["empty_qty"]:
            raise ApiError(f"Only {c['empty_qty']} empty cylinder(s) in stock.", 409, field="qty")
        supplier_id = _optional_supplier(db, data)
        dep = c["security_paise"] if data.get("deposit") in (None, "") else money_field(data, "deposit", "Deposit", allow_zero=True)
        _movement(db, tid, "sent_back", empty=-qty, note="Sent back to supplier")
        db.execute("UPDATE cylinder_types SET empty_qty=empty_qty-? WHERE id=?", (qty, tid))
        _deposit_event(db, tid, supplier_id, "refunded", qty, qty * dep, "Sent back to supplier")
    return jsonify({"ok": True})
```

## A2. New file `static/js/stock_extra.js`
```javascript
// Stock & Price, part 2: suppliers on each cylinder, the damaged-cylinders area and sending cylinders back.
// Loads after stock.js and re-draws these parts every time stock.js has drawn the page.
(function () {
  const { esc, fmt } = UI;
  const money = (v) => fmt.money(v);
  const $ = (id) => document.getElementById(id);
  let ext = { cylinders: {}, damaged: [], suppliers: [], deposits: {} };

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

  /* ---------- suppliers on each cylinder card ---------- */
  function supplierPanel(c) {
    const list = ext.cylinders[c.id] || [];
    const cards = list.map((s) => {
      const neg = Number(s.margin) < 0;
      return '<div class="st-sup" data-tid="' + c.id + '" data-sid="' + s.supplier_id + '">' +
        '<div class="st-sup-top"><b>' + esc(s.name) + '</b><span class="st-sup-btns">' +
        '<button type="button" class="link" data-xact="sup-edit">Change price</button>' +
        '<button type="button" class="link del" data-xact="sup-remove">Remove</button></span></div>' +
        '<div class="st-sup-grid"><div><small>Buy at</small><b>' + money(s.price) + "</b></div>" +
        '<div><small>Margin</small><b class="' + (neg ? "neg" : "pos") + '">' + money(s.margin) + "</b></div>" +
        "<div><small>Full from them</small><b>" + s.full + "</b></div>" +
        "<div><small>Deposit held</small><b>" + money(s.deposit_held) + "</b></div></div></div>";
    }).join("");
    return '<div class="st-sups"><div class="st-sups-head"><b>Suppliers</b>' +
      '<button type="button" class="btn btn-white" data-xact="sup-add" data-tid="' + c.id + '">＋ Add supplier</button></div>' +
      (cards || '<p class="st-supplier">No supplier sells this size yet.</p>') + "</div>";
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
    const c = cyl(tid), linked = (ext.cylinders[tid] || []).map((s) => s.supplier_id);
    const free = ext.suppliers.filter((s) => !linked.includes(s.id));
    if (!free.length) { StockUI.toast(ext.suppliers.length ? "Every supplier already sells this size." : "Add a supplier first (Suppliers & Purchases).", true); return; }
    popup("Add supplier · " + c.name, "Pick who sells this cylinder and what they charge you. Each supplier keeps their own price.",
      supplierSelect("supplier_id", "Supplier", free) + moneyBox("purchase_price", "Their price for one full cylinder"), "Add supplier",
      (f) => Api.post("/api/cylinders/" + tid + "/suppliers", { supplier_id: f.elements.supplier_id.value, purchase_price: f.elements.purchase_price.value.trim() }),
      "Supplier added");
  }
  function editSupplier(tid, sid) {
    const s = ext.cylinders[tid].find((x) => x.supplier_id === sid);
    popup("Change price · " + s.name, "Applies to cylinders you buy from now on. Cylinders already bought keep the price they were bought at.",
      moneyBox("purchase_price", "Their price for one full cylinder", s.price), "Save price",
      (f) => Api.put("/api/cylinders/" + tid + "/suppliers/" + sid, { purchase_price: f.elements.purchase_price.value.trim() }), "Price updated");
  }
  function removeSupplier(tid, sid) {
    const s = ext.cylinders[tid].find((x) => x.supplier_id === sid);
    Cust.openConfirm({ title: "Remove " + s.name + "?", danger: true, confirmLabel: "Remove",
      message: s.name + " will no longer be offered for " + cyl(tid).name + " in new purchases. Past purchases stay as they are.",
      onConfirm: async () => { await Api.del("/api/cylinders/" + tid + "/suppliers/" + sid); StockUI.toast("Supplier removed"); StockUI.load(); } });
  }

  /* ---------- send back ---------- */
  function sendBack(tid) {
    const c = cyl(tid);
    popup("Send back · " + c.name, "Good empty cylinders going back to a supplier. You get the security deposit back.",
      '<div class="two"><label class="field"><span>How many</span><div class="amt"><input name="qty" type="number" min="1" step="1" inputmode="numeric" value="1"><i>cyl</i></div></label>' +
      moneyBox("deposit", "Deposit per cylinder", c.security) + "</div>" +
      supplierSelect("supplier_id", "Sent to", ext.suppliers, "Not sure / skip") +
      '<p class="hint">You have ' + c.empty + " empty " + esc(c.name) + " cylinder(s).</p>", "Send back",
      (f) => Api.post("/api/cylinders/" + tid + "/send-back", { qty: f.elements.qty.value.trim(), deposit: f.elements.deposit.value.trim(), supplier_id: f.elements.supplier_id.value }),
      "Cylinders sent back");
  }

  /* ---------- damaged cylinders ---------- */
  function renderDamagedArea() {
    const d = ext.deposits || {};
    $("st-damaged-list").innerHTML = ext.damaged.length ? ext.damaged.map((r) =>
      '<div class="st-dmg-chip"><b>' + r.qty + "</b> × " + esc(r.name) + (Number(r.deposit_lost) ? "<small>deposit lost " + money(r.deposit_lost) + "</small>" : "") + "</div>").join("")
      : '<span class="card-sub">No damaged cylinders.</span>';
    $("st-deposit-line").innerHTML = "Deposits held with suppliers <b>" + money(d.held) + "</b> · lost on damaged <b>" + money(d.cancelled) +
      "</b> · refunded <b>" + money(d.refunded) + "</b>";
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
       "send-back": () => sendBack(tid) })[b.dataset.xact]();
  });
  $("st-damaged-add").addEventListener("click", addDamaged);
  document.addEventListener("stock:rendered", async () => {
    try { ext = await Api.get("/api/stock/extra"); } catch (e) { return; }
    decorateCards();
    renderDamagedArea();
  });
})();
```

## A3. New file `tests/test_stock_suppliers.py`  (optional but recommended)
```python
"""v0.4.3: suppliers per cylinder, damaged cylinders, security deposits."""
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
        self.conn.commit()
        self.tid = self.conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]
        self.conn.execute("UPDATE cylinder_types SET full_qty=4, empty_qty=3, security_paise=250000, sale_price_paise=150000 WHERE id=?", (self.tid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def row(self):
        return self.conn.execute("SELECT * FROM cylinder_types WHERE id=?", (self.tid,)).fetchone()

    def test_each_supplier_has_own_price_and_margin(self):
        for sid, price in ((1, "1300"), (2, "1350")):
            self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers", {"supplier_id": sid, "purchase_price": price})[0], 201)
        sups = self.api("get", "/api/stock/extra")[1]["cylinders"][str(self.tid)]
        self.assertEqual([(s["name"], s["price"], s["margin"]) for s in sups],
                         [("Alpha", "1300.00", "200.00"), ("Beta", "1350.00", "150.00")])
        self.api("put", f"/api/cylinders/{self.tid}/suppliers/2", {"purchase_price": "1400"})
        self.assertEqual(self.api("get", "/api/stock/extra")[1]["cylinders"][str(self.tid)][1]["margin"], "100.00")
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers", {"supplier_id": 1})[0], 400)
        self.api("delete", f"/api/cylinders/{self.tid}/suppliers/1")
        self.assertEqual(len(self.api("get", "/api/stock/extra")[1]["cylinders"][str(self.tid)]), 1)

    def test_damaged_cancels_deposit_and_moves_stock(self):
        code, _ = self.api("post", "/api/stock/damaged/add", {
            "source": "empty", "supplier_id": "1", "items": [{"cylinder_type_id": self.tid, "qty": "2", "deposit": "2500"}]})
        self.assertEqual(code, 200)
        r = self.row()
        self.assertEqual((r["empty_qty"], r["damaged_qty"]), (1, 2))
        d = self.api("get", "/api/stock/extra")[1]
        self.assertEqual(d["deposits"]["cancelled"], "5000.00")
        self.assertEqual(d["damaged"][0]["qty"], 2)
        self.assertEqual(self.api("post", "/api/stock/damaged/add", {"source": "empty", "items": [{"cylinder_type_id": self.tid, "qty": "9"}]})[0], 409)

    def test_damaged_full_uses_oldest_lot(self):
        self.conn.execute("INSERT INTO stock_lots (cylinder_type_id, source, lot_date, qty_in, qty_left, unit_cost_paise) VALUES (?, 'opening', '2026-01-01', 4, 4, 130000)", (self.tid,))
        self.conn.commit()
        self.api("post", "/api/stock/damaged/add", {"source": "full", "items": [{"cylinder_type_id": self.tid, "qty": "1"}]})
        self.assertEqual(self.conn.execute("SELECT qty_left FROM stock_lots WHERE cylinder_type_id=?", (self.tid,)).fetchone()[0], 3)
        self.assertEqual(self.row()["full_qty"], 3)

    def test_send_back_refunds_deposit(self):
        code, _ = self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "2", "supplier_id": "2"})
        self.assertEqual(code, 200)
        self.assertEqual(self.row()["empty_qty"], 1)
        self.assertEqual(self.api("get", "/api/stock/extra")[1]["deposits"]["refunded"], "5000.00")
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "5"})[0], 409)

    def test_purchase_of_new_cylinders_records_deposit_paid(self):
        self.api("post", f"/api/cylinders/{self.tid}/suppliers", {"supplier_id": 1, "purchase_price": "1300"})
        code, p = self.api("post", "/api/purchases", {"supplier_id": 1, "items": [
            {"cylinder_type_id": self.tid, "full_in": 2, "new_full": 2, "rate": "1300", "deposit": "2500"}]})
        self.assertEqual(code, 201, p)
        d = self.api("get", "/api/stock/extra")[1]
        self.assertEqual(d["deposits"]["paid"], "5000.00")
        self.assertEqual(d["cylinders"][str(self.tid)][0]["deposit_held"], "5000.00")


if __name__ == "__main__":
    unittest.main()
```

## A4. `static/css/stock.css` — paste at the very END of the file
```css

/* ---- v0.4.3: suppliers on cylinder cards, damaged area ---- */
.st-sups { margin: 12px 0; padding-top: 12px; border-top: 1px dashed #c9c8dc; }
.st-sups-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; }
.st-sups-head .btn { height: 28px; padding: 0 10px; font-size: 12px; }
.st-sup { background: #f8f8fd; border: 1px solid #dcdbec; border-radius: 12px; padding: 10px 12px; margin-bottom: 8px; }
.st-sup-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 14px; }
.st-sup-btns { display: flex; gap: 12px; }
.st-sup .link { background: none; border: 0; padding: 0; font-size: 12px; font-weight: 600; color: var(--navy); cursor: pointer; }
.st-sup .link.del { color: var(--red); }
.st-sup-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.st-sup-grid small { display: block; font-size: 11px; color: var(--muted); }
.st-sup-grid b { font-size: 13px; white-space: nowrap; }
.st-sup-grid b.pos { color: var(--green); }
.st-sup-grid b.neg { color: var(--red); }
@media (max-width: 640px) { .st-sup-grid { grid-template-columns: 1fr 1fr; } }

.st-damaged-body { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.st-dmg-list { display: flex; gap: 8px; flex-wrap: wrap; flex: 1; min-width: 200px; }
.st-dmg-chip { background: var(--red-soft); color: var(--red); border-radius: 10px; padding: 7px 12px; font-size: 13px; }
.st-dmg-chip small { display: block; font-size: 11px; opacity: .85; }
.st-deposit-line { margin: 12px 0 0; font-size: 12px; color: var(--muted); }
.st-deposit-line b { color: var(--text); }
.st-dmg-head, .st-dmg-row { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 1fr); gap: 8px; align-items: center; margin-bottom: 8px; }
.st-dmg-head { font-size: 11px; color: var(--muted); margin-top: 6px; }
.st-dmg-pick { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; }
.st-dmg-pick small { display: block; font-weight: 400; font-size: 11px; color: var(--muted); }
.st-dmg-row .amt input:disabled { background: #f1f1f6; color: #9a99b0; }
.st-dmg-total { margin-top: 10px; font-weight: 600; }
.modal .st-dmg-row .amt input { width: 100%; }
```

## A5. `schema.sql` — paste at the very END of the file
```sql
-- Security deposits on cylinders, one row per event, never deleted.
--   paid = new cylinders bought (written by a purchase)   cancelled = cylinder damaged, deposit lost
--   refunded = good cylinders sent back to the supplier, deposit received
CREATE TABLE IF NOT EXISTS cylinder_deposits (
    id               INTEGER PRIMARY KEY,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    supplier_id      INTEGER REFERENCES suppliers(id),
    kind             TEXT NOT NULL CHECK (kind IN ('paid', 'cancelled', 'refunded')),
    qty              INTEGER NOT NULL,
    amount_paise     INTEGER NOT NULL,
    purchase_id      INTEGER REFERENCES purchases(id),
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_cylinder_deposits ON cylinder_deposits(cylinder_type_id, supplier_id);
```

---

# B. EDITS TO EXISTING FILES  (find the text, replace it)

## B1. `api/__init__.py` — Register the new API file
**Find:**
```
suppliers, purchases, stock  #
```
**Replace with:**
```
suppliers, purchases, stock, stock_suppliers  #
```

## B2. `db.py` — Fill in the deposit history for purchases you already made (runs once)
**Find:**
```
            lots.create_opening_lots(conn)
        conn.commit()
```
**Replace with:**
```
            lots.create_opening_lots(conn)
        # v0.4.3: deposits already paid on earlier purchases go into the deposit history (only when it is empty).
        if conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO cylinder_deposits (cylinder_type_id, supplier_id, kind, qty, amount_paise, purchase_id, note) "
                "SELECT i.cylinder_type_id, p.supplier_id, 'paid', i.new_full_qty + i.new_empty_qty, "
                "(i.new_full_qty + i.new_empty_qty) * i.security_rate_paise, p.id, 'Purchase ' || p.number "
                "FROM purchase_items i JOIN purchases p ON p.id = i.purchase_id WHERE i.new_full_qty + i.new_empty_qty > 0")
        conn.commit()
```

## B3. `api/purchases.py` — A purchase of new cylinders records the deposit paid
**Find:**
```
            lots.add_lot(db, item["id"], item["full_in"], item["rate"], day, pid)
```
**Replace with:**
```
            lots.add_lot(db, item["id"], item["full_in"], item["rate"], day, pid)
            if item["new_full"] or item["new_empty"]:      # deposit paid on brand-new cylinders
                new_total = item["new_full"] + item["new_empty"]
                db.execute(
                    "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,purchase_id,note) VALUES(?,?,?,?,?,?,?)",
                    (item["id"], sid, "paid", new_total, new_total * item["security_rate"], pid, f"Purchase {number}"))
```

## B4. `templates/stock.html` — Replace the Damaged cylinders box
**Find:**
```
  <form id="st-damaged-form" class="st-damaged-form" autocomplete="off">
    <div class="st-damaged-fields" id="st-damaged-fields"></div>
    <button class="btn btn-dark" type="submit" id="st-damaged-save">Update damaged stock</button>
  </form>
  <div class="form-error" id="st-damaged-error" role="alert"></div>
```
**Replace with:**
```
  <div class="st-damaged-body">
    <div class="st-dmg-list" id="st-damaged-list"></div>
    <button class="btn btn-dark" type="button" id="st-damaged-add"><i data-icon="plus"></i>Add damaged cylinder</button>
  </div>
  <p class="st-deposit-line" id="st-deposit-line"></p>
```

## B5. `templates/stock.html` — Load the new script (add the second line after the first)
**Find:**
```
<script src="{{ url_for('static', filename='js/stock.js') }}"></script>
```
**Replace with:**
```
<script src="{{ url_for('static', filename='js/stock.js') }}"></script>
<script src="{{ url_for('static', filename='js/stock_extra.js') }}"></script>
```

## B6. `templates/stock.html` — Subtitle of the Damaged box
**Find:**
```
Track and update damaged quantities by cylinder size.
```
**Replace with:**
```
Cylinders that can no longer be used. Their security deposit is cancelled.
```

## B7. `static/js/stock.js` — renderDamaged is now drawn by stock_extra.js: make it empty
**Find:**
```
  function renderDamaged(cyls) {
    $("st-damaged-fields").innerHTML = cyls.map((c) =>
      '<label><span>' + esc(c.name) + '</span><div class="amt"><input name="d' + c.id + '" type="number" min="0" step="1" inputmode="numeric" value="' +
      c.damaged + '"><i>cyl</i></div></label>').join("") || '<span class="card-sub">Add a cylinder to track damaged stock.</span>';
    $("st-damaged-save").disabled = !cyls.length;
  }
```
**Replace with:**
```
  function renderDamaged() {}   // the damaged area is drawn by stock_extra.js
```

## B8. `static/js/stock.js` — Tell stock_extra.js the page was drawn
**Find:**
```
    if (window.Icons && Icons.render) Icons.render(document);
  }

  /* ---------- history ---------- */
```
**Replace with:**
```
    if (window.Icons && Icons.render) Icons.render(document);
    document.dispatchEvent(new CustomEvent("stock:rendered"));
  }

  /* ---------- history ---------- */
```

## B9. `static/js/stock.js` — Remove the old damaged-form handler (delete this whole block)
**Find:**
```
  $("st-damaged-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const counts = {};
    state.cylinders.forEach((c) => { counts[c.id] = Math.max(0, Math.floor(num(e.target.elements["d" + c.id].value))); });
    const err = $("st-damaged-error"); err.textContent = "";
    $("st-damaged-save").disabled = true;
    try { await Api.put("/api/stock/damaged", { counts }); toast("Damaged stock updated"); await load(); }
    catch (ex) { err.textContent = ex.message || "Could not save."; }
    $("st-damaged-save").disabled = false;
  });

  load();
})();
```
**Replace with:**
```
  window.StockUI = { load, toast, state };   // used by stock_extra.js
  load();
})();
```

---
## Things I decided (change any of them by telling me)
* **Damaged**: cylinders can be damaged from *empty* or *full* stock (you pick). A full one also leaves the oldest-first cost lot.
  The deposit per cylinder is pre-filled from the size's security price and you can type a different one.
* **Deposit refunded / cancelled does not touch the supplier's balance yet.** It is only recorded and shown in the box
  and the history. Tell me if the refund should reduce what you owe that supplier, and I will connect it.
* **"Deposit held"** per supplier is *paid − cancelled − refunded*, never below 0. Deposits for cylinders you owned before
  this app are unknown, so a size can show Rs 0 held even though you did pay.
* **Cards per supplier** live inside each cylinder's card (so stock counts stay per size). *Full from them* only counts cylinders
  bought through a purchase, not your opening stock.
* Cylinders only for now. Linking suppliers to **other items** from Stock & Price is not done (still on the supplier page).
* The old `PUT /api/stock/damaged` endpoint in `api/stock.py` is no longer used by the screen. You can leave it or delete it.
* Tests: after this the suite has 35 tests.
