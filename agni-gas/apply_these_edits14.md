# APPLY_THESE_EDITS14 — damaged-cylinder dispatch + sole-supplier defaults

Paths below are relative to `agni-gas/`. This patch is for the current repository version after `APPLY_THESE_EDITS13.md`.

This adds one small operation beside **Add damaged cylinder**: **Send damaged back**. It opens a checklist of outstanding damaged-cylinder records, lets the user tick the rows being dispatched, and records the date and optional note. It also makes the only active supplier the default for all cylinder sizes and ordinary items, including existing stock and new stock.

**The existing Add damaged cylinder workflow is intentionally unchanged.** Its one supplier dropdown stays as it is; when different suppliers are involved, the user can record separate damage batches. The new dispatch checklist has a supplier dropdown on each row, initially filled from the supplier recorded when that batch was marked damaged.

## Accounting rules (important)

- Marking a cylinder damaged already writes the `cancelled` security-deposit event. That is the permanent loss of the deposit.
- Sending that damaged cylinder back only reduces `cylinder_types.damaged_qty` and writes a stock-history movement.
- Dispatch must not insert another `cylinder_deposits` row, change the original cancellation, create a `refunded` event, or touch `purchases`, `supplier_payments`, or supplier balances.
- The editable deposit value in the dispatch checklist is saved as a **reference snapshot only**. It is not an accounting amount and must never be included in deposit totals or reports.
- The supplier selected in the dispatch checklist is the destination for the physical cylinder. Changing it must not rewrite the supplier on the original deposit-cancellation event.

The ordinary **Send back** action for good, empty cylinders remains untouched. That action still records an actual deposit refund.

---

# A. Database tables

## A1. `schema.sql`

At the very end of `schema.sql`, immediately after the existing line:

```sql
CREATE INDEX IF NOT EXISTS idx_cylinder_deposits ON cylinder_deposits(cylinder_type_id, supplier_id);
```

append:

```sql
-- Physical dispatch of cylinders that were already marked damaged.
-- This is an inventory/audit record only; it does not refund or cancel deposits.
CREATE TABLE IF NOT EXISTS damaged_cylinder_dispatches (
    id           INTEGER PRIMARY KEY,
    dispatch_date TEXT NOT NULL,
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS damaged_cylinder_dispatch_items (
    id                       INTEGER PRIMARY KEY,
    dispatch_id              INTEGER NOT NULL REFERENCES damaged_cylinder_dispatches(id),
    damage_event_id          INTEGER NOT NULL REFERENCES cylinder_deposits(id),
    cylinder_type_id         INTEGER NOT NULL REFERENCES cylinder_types(id),
    supplier_id              INTEGER REFERENCES suppliers(id),
    qty                      INTEGER NOT NULL CHECK (qty > 0),
    deposit_reference_paise  INTEGER NOT NULL DEFAULT 0,
    created_at               TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (dispatch_id, damage_event_id)
);
CREATE INDEX IF NOT EXISTS idx_damaged_dispatch_items_event
    ON damaged_cylinder_dispatch_items(damage_event_id);
CREATE INDEX IF NOT EXISTS idx_damaged_dispatch_items_dispatch
    ON damaged_cylinder_dispatch_items(dispatch_id);
```

No manual SQL migration is needed. `db.init_db()` runs `schema.sql` on startup, and these `CREATE TABLE IF NOT EXISTS` statements add the tables without deleting existing data.

---

# B. Backend

## B1. `api/stock_suppliers.py` — add imports

Find:

```python
from .util import ApiError, RECEIVED_IN, body, int_field, money_field
```

Replace with:

```python
from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, text
```

## B2. `api/stock_suppliers.py` — expose damaged batches that have not yet been dispatched

Inside `stock_extra()`, find the existing `damaged = [...]` query. It starts with:

```python
damaged = [{"cylinder_type_id": r["id"], "name": r["name"], "qty": r["damaged_qty"], "deposit_lost": to_rupees(r["lost"])} for r in db.execute(
```

Leave that query exactly as it is. Immediately **after that complete `damaged = ...` statement and before `return jsonify({`**, insert:

```python
    # Each cancelled deposit row created by damaged_add() is one damage batch.
    # A batch remains selectable until all its damaged cylinders have been dispatched.
    dispatch_options = []
    physical_remaining = {
        r["id"]: r["damaged_qty"]
        for r in db.execute("SELECT id, damaged_qty FROM cylinder_types WHERE active=1")
    }
    damage_batches = db.execute(
        "SELECT d.id AS damage_event_id, d.cylinder_type_id, c.name, "
        "d.supplier_id, s.name AS supplier_name, d.qty, d.amount_paise, d.created_at, "
        "COALESCE((SELECT SUM(di.qty) FROM damaged_cylinder_dispatch_items di "
        "          WHERE di.damage_event_id=d.id),0) AS dispatched_qty "
        "FROM cylinder_deposits d "
        "JOIN cylinder_types c ON c.id=d.cylinder_type_id "
        "LEFT JOIN suppliers s ON s.id=d.supplier_id "
        "WHERE d.kind='cancelled' AND c.active=1 "
        "ORDER BY d.created_at, d.id"
    ).fetchall()
    for r in damage_batches:
        batch_remaining = max(0, r["qty"] - r["dispatched_qty"])
        # Do not offer more cylinders than the current damaged stock count.
        available = min(batch_remaining, physical_remaining.get(r["cylinder_type_id"], 0))
        if available <= 0:
            continue
        per_cylinder = (r["amount_paise"] + (r["qty"] // 2)) // r["qty"] if r["qty"] else 0
        dispatch_options.append({
            "damage_event_id": r["damage_event_id"],
            "cylinder_type_id": r["cylinder_type_id"],
            "name": r["name"],
            "supplier_id": r["supplier_id"],
            "supplier_name": r["supplier_name"],
            "remaining_qty": available,
            "deposit_reference": to_rupees(per_cylinder),
            "damaged_at": r["created_at"],
        })
        physical_remaining[r["cylinder_type_id"]] -= available
```

Then, in the existing `return jsonify({ ... })` dictionary, add this property alongside `"cylinders"` and `"damaged"`:

```python
        "damaged_dispatch_options": dispatch_options,
```

For example, the beginning of that response should now look like:

```python
    return jsonify({
        "cylinders": cylinders, "damaged": damaged,
        "damaged_dispatch_options": dispatch_options,
        "suppliers": [{"id": r["id"], "name": r["name"]} for r in db.execute(
```

Do not change the existing `deposits` calculation. It must continue to count every `cancelled` event permanently.

## B3. `api/stock_suppliers.py` — add the dispatch endpoint

Find the end of the existing `damaged_add()` function:

```python
    return jsonify({"ok": True})


# ---------- empty cylinders sent back to the supplier ----------
```

Insert the following code **between** those lines. Leave the existing good-empty-cylinder `cylinder_send_back()` route below it unchanged.

```python
@api_bp.post("/stock/damaged/send-back")
def damaged_send_back():
    """Record physical dispatch of already-damaged cylinders; no deposit money moves here."""
    data = body()
    dispatch_date = day_field(data, "date", "Dispatch date")
    note = text(data, "note", "Note", max_len=200)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("Select at least one damaged-cylinder row to send back.")

    db = get_db()
    with transaction(db):
        parsed = []
        seen_events = set()
        qty_by_type = {}

        # Validate every selected row before writing anything.
        for item in items:
            if not isinstance(item, dict):
                raise ApiError("Invalid damaged-cylinder dispatch row.")

            event_id = int_field(item.get("damage_event_id"), "Damage record", minimum=1)
            if event_id in seen_events:
                raise ApiError("A damaged-cylinder row was selected more than once.", 409)
            seen_events.add(event_id)

            event = db.execute(
                "SELECT d.id, d.cylinder_type_id, d.qty, d.amount_paise, "
                "COALESCE((SELECT SUM(di.qty) FROM damaged_cylinder_dispatch_items di "
                "          WHERE di.damage_event_id=d.id),0) AS dispatched_qty "
                "FROM cylinder_deposits d WHERE d.id=? AND d.kind='cancelled'",
                (event_id,),
            ).fetchone()
            if not event:
                raise ApiError("This damaged-cylinder record was not found.", 404)
            if event["qty"] <= 0:
                raise ApiError("This damaged-cylinder record has an invalid quantity.", 409)

            qty = int_field(item.get("qty"), "Dispatch quantity", field="qty", minimum=1, maximum=1_000_000)
            remaining = event["qty"] - event["dispatched_qty"]
            if qty > remaining:
                raise ApiError(f"Only {max(0, remaining)} cylinder(s) remain in this damaged batch.", 409)

            tid = event["cylinder_type_id"]
            _cylinder(db, tid)
            supplier_id = _optional_supplier(db, item)  # destination; does not alter the original damage event

            if item.get("deposit_reference") in (None, ""):
                deposit_reference = (event["amount_paise"] + (event["qty"] // 2)) // event["qty"]
            else:
                deposit_reference = money_field(
                    item, "deposit_reference", "Deposit reference", allow_zero=True
                )

            parsed.append({
                "event_id": event_id,
                "cylinder_type_id": tid,
                "qty": qty,
                "supplier_id": supplier_id,
                "deposit_reference_paise": deposit_reference,
            })
            qty_by_type[tid] = qty_by_type.get(tid, 0) + qty

        # Several damage batches can refer to the same cylinder size.
        # Their combined dispatch must still fit the current damaged stock.
        for tid, qty in qty_by_type.items():
            cylinder = _cylinder(db, tid)
            if qty > cylinder["damaged_qty"]:
                raise ApiError(
                    f"Only {cylinder['damaged_qty']} damaged cylinder(s) of {cylinder['name']} are currently in stock.",
                    409,
                )

        dispatch_id = db.execute(
            "INSERT INTO damaged_cylinder_dispatches(dispatch_date, note) VALUES(?,?)",
            (dispatch_date, note),
        ).lastrowid

        for item in parsed:
            tid = item["cylinder_type_id"]
            qty = item["qty"]
            sid = item["supplier_id"]
            supplier_name = _supplier(db, sid)["name"] if sid is not None else None

            db.execute(
                "INSERT INTO damaged_cylinder_dispatch_items "
                "(dispatch_id, damage_event_id, cylinder_type_id, supplier_id, qty, deposit_reference_paise) "
                "VALUES(?,?,?,?,?,?)",
                (dispatch_id, item["event_id"], tid, sid, qty, item["deposit_reference_paise"]),
            )

            changed = db.execute(
                "UPDATE cylinder_types SET damaged_qty=damaged_qty-? "
                "WHERE id=? AND damaged_qty>=?",
                (qty, tid, qty),
            ).rowcount
            if not changed:
                raise ApiError("Damaged stock changed while this dispatch was being saved. Reload and try again.", 409)

            movement_note = "Damaged cylinders sent back"
            if supplier_name:
                movement_note += f" to {supplier_name}"
            if note:
                movement_note += f" · {note}"
            _movement(
                db, tid, "damaged_send_back", ref_id=dispatch_id,
                damaged=-qty, note=movement_note,
            )

    return jsonify({"ok": True, "dispatch_id": dispatch_id, "date": dispatch_date, "items": len(parsed)})
```

This endpoint deliberately does **not** call `_deposit_event()`. It only writes the dispatch audit rows and the negative damaged-stock movement. The original `cancelled` deposit row remains untouched.

---

# C. Stock history

## C1. `api/stock.py` — label the new movement

Find `MOVEMENT_LABEL` near the top of the file and add this entry:

```python
"damaged_send_back": "Damaged cylinders sent back",
```

For example:

```python
MOVEMENT_LABEL = {
    "purchase": "Purchase", "sale": "Sale", "sale_cancel": "Sale cancelled", "adjustment": "Adjusted",
    "opening": "Opening stock", "damaged": "Damaged updated", "customer_return": "Empty returned",
    "return": "Empty returned", "damaged_send_back": "Damaged cylinders sent back",
}
```

## C2. `api/stock.py` — show the entered dispatch date in history

In `stock_history()`, find the query that starts:

```python
    for m in db.execute(
        "SELECT m.id, m.moved_at, m.ref_type, m.note, m.full_delta, m.empty_delta, m.damaged_delta, t.name, "
        "COALESCE(p.number, s.number) AS number FROM stock_movements m "
```

Replace the **whole SQL query string section** with:

```python
    for m in db.execute(
        "SELECT m.id, COALESCE(dd.dispatch_date || ' 12:00:00', m.moved_at) AS moved_at, "
        "m.ref_type, m.note, m.full_delta, m.empty_delta, m.damaged_delta, t.name, "
        "COALESCE(p.number, s.number, CASE WHEN dd.id IS NOT NULL THEN 'Dispatch #' || dd.id END) AS number "
        "FROM stock_movements m "
        "JOIN cylinder_types t ON t.id=m.cylinder_type_id "
        "LEFT JOIN purchases p ON m.ref_type='purchase' AND p.id=m.ref_id "
        "LEFT JOIN sales s ON m.ref_type IN ('sale','sale_cancel') AND s.id=m.ref_id "
        "LEFT JOIN damaged_cylinder_dispatches dd ON m.ref_type='damaged_send_back' AND dd.id=m.ref_id" + where +
        " ORDER BY COALESCE(dd.dispatch_date || ' 12:00:00', m.moved_at) DESC, m.id DESC LIMIT ?",
        params + [limit + 1]
    ):
```

Leave the rest of `stock_history()` alone. The negative `damaged_delta` is already included in its `changes` list, so the history will show the dispatched quantity as a decrease.

---

# D. Frontend

## D1. `templates/stock.html` — add the button beside Add damaged cylinder

Find this existing block inside `.st-damaged-body`:

```html
    <div class="st-dmg-list" id="st-damaged-list"></div>
    <button class="btn btn-dark" type="button" id="st-damaged-add"><i data-icon="plus"></i>Add damaged cylinder</button>
```

Replace it with:

```html
    <div class="st-dmg-list" id="st-damaged-list"></div>
    <div class="st-damaged-actions">
      <button class="btn btn-dark" type="button" id="st-damaged-add"><i data-icon="plus"></i>Add damaged cylinder</button>
      <button class="btn btn-white" type="button" id="st-damaged-sendback" disabled>Send damaged back</button>
    </div>
```

## D2. `static/css/stock.css` — style the paired buttons and checklist rows

Append this at the end of the file:

```css
/* ---- v0.4.5: dispatch damaged cylinders ---- */
.st-damaged-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.st-damaged-actions .btn:disabled { opacity: .45; cursor: not-allowed; }
.st-dmg-dispatch-head,
.st-dmg-dispatch-row {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) minmax(0, 1fr) minmax(90px, .65fr);
  gap: 8px;
  align-items: end;
  margin-bottom: 9px;
}
.st-dmg-dispatch-head { margin-top: 8px; font-size: 11px; color: var(--muted); }
.st-dmg-dispatch-row { padding: 10px; border: 1px solid #e3e2f0; border-radius: 10px; background: #fafaff; }
.st-dmg-dispatch-name { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; font-weight: 650; }
.st-dmg-dispatch-name small { display: block; margin-top: 3px; font-size: 11px; font-weight: 400; color: var(--muted); }
.st-dmg-dispatch-row .field { min-width: 0; margin: 0; }
.st-dmg-dispatch-row .field > span { font-size: 11px; }
.st-dmg-dispatch-row .amt input { width: 100%; min-width: 0; }
.st-dmg-dispatch-row input:disabled { background: #f1f1f6; color: #9a99b0; }
@media (max-width: 640px) {
  .st-dmg-dispatch-head { display: none; }
  .st-dmg-dispatch-row { grid-template-columns: 1fr 1fr; }
  .st-dmg-dispatch-name { grid-column: 1 / -1; }
}
```

## D3. `static/js/stock_extra.js` — include the dispatch options in state

Find:

```javascript
  let ext = { cylinders: {}, damaged: [], suppliers: [], deposits: {} };
```

Replace with:

```javascript
  let ext = { cylinders: {}, damaged: [], damaged_dispatch_options: [], suppliers: [], deposits: {} };
```

## D4. `static/js/stock_extra.js` — disable the button when there is nothing to dispatch

At the end of `renderDamagedArea()`, after the existing assignment to `st-deposit-line`, add:

```javascript
    const sendButton = $("st-damaged-sendback");
    sendButton.disabled = !ext.damaged_dispatch_options.length;
```

Do not change the existing damaged-count or deposit-summary display.

## D5. `static/js/stock_extra.js` — add the checklist popup

Insert this entire function immediately **after** the existing `addDamaged()` function and before the `/* ---------- wiring ---------- */` comment:

```javascript
  function sendDamagedBack() {
    const rows = ext.damaged_dispatch_options || [];
    if (!rows.length) {
      StockUI.toast("There are no damaged cylinders awaiting dispatch.", true);
      return;
    }

    const supplierOptions = (selected) =>
      '<option value="">Not sure / unassigned</option>' + ext.suppliers.map((s) =>
        '<option value="' + s.id + '"' + (Number(selected) === Number(s.id) ? " selected" : "") + '>' + esc(s.name) + '</option>'
      ).join("");

    const rowHtml = rows.map((r) => {
      const id = r.damage_event_id;
      const markedDate = String(r.damaged_at || "").split(" ")[0];
      return '<div class="st-dmg-dispatch-row" data-event="' + id + '">' +
        '<label class="st-dmg-dispatch-name"><input type="checkbox" name="pick' + id + '"><span>' +
          esc(r.name) + '<small>' + r.remaining_qty + ' awaiting dispatch' + (markedDate ? ' · marked ' + esc(markedDate) : '') + '</small></span></label>' +
        '<label class="field"><span>Supplier</span><select name="s' + id + '" class="amt">' + supplierOptions(r.supplier_id) + '</select></label>' +
        '<label class="field"><span>Deposit / cylinder</span><div class="amt"><i>Rs</i><input name="d' + id + '" inputmode="decimal" value="' + esc(r.deposit_reference) + '"></div></label>' +
        '<label class="field"><span>Sending</span><div class="amt"><input name="q' + id + '" type="number" min="1" max="' + r.remaining_qty + '" step="1" inputmode="numeric" value="1" disabled><i>cyl</i></div></label>' +
      '</div>';
    }).join("");

    popup(
      "Send damaged cylinders back",
      "Tick the damaged-cylinder batches being sent to the supplier. This records the physical dispatch only; their security deposits were already cancelled when they were marked damaged.",
      '<label class="field"><span>Dispatch date</span><input type="date" name="date"></label>' +
      '<label class="field"><span>Note (optional)</span><input name="note" maxlength="200" autocomplete="off" placeholder="Dispatch reference or note"></label>' +
      '<div class="st-dmg-dispatch-head"><span>Cylinder</span><span>Supplier</span><span>Deposit / cylinder</span><span>Quantity</span></div>' +
      rowHtml +
      '<p class="hint">The deposit value is editable for reference only. It will not change the cancelled deposit or any financial report.</p>',
      "Record dispatch",
      async (f) => {
        const items = rows.filter((r) => f.elements["pick" + r.damage_event_id].checked).map((r) => ({
          damage_event_id: r.damage_event_id,
          qty: f.elements["q" + r.damage_event_id].value.trim(),
          supplier_id: f.elements["s" + r.damage_event_id].value,
          deposit_reference: f.elements["d" + r.damage_event_id].value.trim(),
        }));
        if (!items.length) throw new Error("Tick at least one damaged-cylinder row.");
        await Api.post("/api/stock/damaged/send-back", {
          date: f.elements.date.value,
          note: f.elements.note.value.trim(),
          items,
        });
      },
      "Damaged cylinders sent back",
      (f) => {
        f.addEventListener("change", (e) => {
          const match = /^pick(\d+)$/.exec(e.target.name || "");
          if (match) f.elements["q" + match[1]].disabled = !e.target.checked;
        });
      }
    );
  }
```

The checklist is one row per original damage batch. If the same size was marked damaged more than once, its batches remain separately traceable, including their original deposit reference.

## D6. `static/js/stock_extra.js` — wire the button

Near the bottom, find:

```javascript
  $("st-damaged-add").addEventListener("click", addDamaged);
```

Immediately after it, add:

```javascript
  $("st-damaged-sendback").addEventListener("click", sendDamagedBack);
```

Leave the existing `stock:rendered` listener and all ordinary/empty-cylinder Send back handlers unchanged.

---

# E. Regression test

Add this method inside the existing `ApiTests` class in `tests/test_api.py`, immediately before `def test_suppliers(self):` (or anywhere else inside the class):

```python
    def test_damaged_cylinder_dispatch_does_not_refund_or_change_supplier_account(self):
        supplier_response = self.client.post("/api/suppliers", json={
            "name": "Damaged Dispatch Test Supplier",
            "gstin": "27ZZZZZ1234A1Z5",
            "opening_type": "payable",
            "opening_amount": "0",
        })
        self.assertEqual(supplier_response.status_code, 201, supplier_response.get_json())
        sid = supplier_response.get_json()["id"]

        cylinder_response = self.client.post("/api/cylinders", json={
            "weight_kg": "88.8",
            "purchase_price": "1000",
            "security": "125",
            "full": "0",
            "empty": "2",
        })
        self.assertEqual(cylinder_response.status_code, 201, cylinder_response.get_json())
        tid = cylinder_response.get_json()["id"]

        linked = self.client.post(f"/api/cylinders/{tid}/suppliers", json={
            "supplier_id": sid,
            "purchase_price": "1000",
            "security": "125",
        })
        self.assertEqual(linked.status_code, 201, linked.get_json())

        damaged = self.client.post("/api/stock/damaged/add", json={
            "source": "empty",
            "supplier_id": sid,
            "items": [{"cylinder_type_id": tid, "qty": "2", "deposit": "125"}],
        })
        self.assertEqual(damaged.status_code, 200, damaged.get_json())

        before_extra = self.client.get("/api/stock/extra").get_json()
        before_deposits = dict(before_extra["deposits"])
        before_supplier_balance = self.client.get(f"/api/suppliers/{sid}").get_json()["balance"]
        option = next(x for x in before_extra["damaged_dispatch_options"] if x["cylinder_type_id"] == tid)
        self.assertEqual(option["remaining_qty"], 2)
        self.assertEqual(option["supplier_id"], sid)
        self.assertEqual(option["deposit_reference"], "125.00")

        first_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "note": "First partial dispatch",
            "items": [{
                "damage_event_id": option["damage_event_id"],
                "qty": "1",
                "supplier_id": str(sid),
                "deposit_reference": "150",
            }],
        })
        self.assertEqual(first_dispatch.status_code, 200, first_dispatch.get_json())

        after_extra = self.client.get("/api/stock/extra").get_json()
        remaining = next(x for x in after_extra["damaged_dispatch_options"] if x["damage_event_id"] == option["damage_event_id"])
        self.assertEqual(remaining["remaining_qty"], 1)
        self.assertEqual(next(x for x in after_extra["damaged"] if x["cylinder_type_id"] == tid)["qty"], 1)
        self.assertEqual(after_extra["deposits"], before_deposits)
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], before_supplier_balance)

        import db
        conn = db.connect()
        cancelled = conn.execute(
            "SELECT COUNT(*), SUM(amount_paise) FROM cylinder_deposits "
            "WHERE cylinder_type_id=? AND kind='cancelled'", (tid,)
        ).fetchone()
        dispatch_reference = conn.execute(
            "SELECT deposit_reference_paise FROM damaged_cylinder_dispatch_items WHERE dispatch_id=?",
            (first_dispatch.get_json()["dispatch_id"],),
        ).fetchone()[0]
        damaged_qty = conn.execute("SELECT damaged_qty FROM cylinder_types WHERE id=?", (tid,)).fetchone()[0]
        conn.close()
        self.assertEqual((cancelled[0], cancelled[1]), (1, 25000))
        self.assertEqual(dispatch_reference, 15000)  # reference snapshot only
        self.assertEqual(damaged_qty, 1)

        second_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "items": [{
                "damage_event_id": option["damage_event_id"],
                "qty": "1",
                "supplier_id": str(sid),
                "deposit_reference": "125",
            }],
        })
        self.assertEqual(second_dispatch.status_code, 200, second_dispatch.get_json())
        self.assertFalse(any(x["cylinder_type_id"] == tid for x in self.client.get("/api/stock/extra").get_json()["damaged_dispatch_options"]))
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], before_supplier_balance)

        over_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "items": [{"damage_event_id": option["damage_event_id"], "qty": "1", "supplier_id": str(sid)}],
        })
        self.assertEqual(over_dispatch.status_code, 409)

        history = self.client.get(f"/api/stock/history?cylinder_type_id={tid}").get_json()
        self.assertTrue(any("Damaged cylinders sent back" in row["title"] for row in history))
        self.assertEqual(self.client.get("/api/stock/extra").get_json()["deposits"], before_deposits)
```

This test checks the key accounting invariant: dispatching damaged cylinders decreases damaged physical stock but leaves the cancelled deposit totals and supplier balance unchanged. It also checks partial dispatch, remaining quantity, duplicate/over-dispatch prevention, and stock history.

---

# F. Test locally

From the `agni-gas/` directory:

```bash
node --check static/js/stock_extra.js
python -m py_compile api/stock.py api/stock_suppliers.py tests/test_api.py
python -m unittest discover tests
```

Then run the desktop app, mark a test cylinder damaged, and test a partial dispatch followed by the remaining dispatch.

# G. Automatically use the only active supplier

This extends the damaged-cylinder patch with one small convenience: while the agency has exactly **one active supplier**, that supplier is the default supplier for all cylinder sizes and ordinary catalogue items.

Behaviour:
- When the first supplier is created, link that supplier to every existing active cylinder size and every existing active catalogue item.
- If an existing database already has exactly one active supplier when this patch is first launched, do the same one-time backfill.
- When an additional supplier is archived and exactly one active supplier remains, link the remaining supplier to all active cylinder sizes and catalogue items that are not already linked.
- New cylinder sizes and new ordinary items created in Stock & Price are automatically linked to the sole active supplier.
- Supplier selectors preselect that supplier in the damaged-cylinder form, both cylinder send-back forms, damaged-dispatch checklist and new-purchase page.
- When there are zero or multiple active suppliers, do not make an automatic selection or create automatic links. Existing supplier links are retained.

These are **supplier-product links only**. Do not assign opening-stock quantities or old stock lots to the supplier, and do not create or alter any security-deposit events. Physical stock ownership/source remains as recorded today.

## G1. `db.py` — add the reusable supplier-default helpers

Append these functions at the end of `db.py`, after the existing `transaction()` function:

```python
def sole_active_supplier_id(conn):
    """Return the only active supplier id, or None when there are zero or multiple."""
    rows = conn.execute(
        "SELECT id FROM suppliers WHERE active=1 ORDER BY id LIMIT 2"
    ).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def link_all_stock_to_supplier(conn, supplier_id):
    """Link every active cylinder size and ordinary item to this supplier without overwriting existing rates."""
    conn.execute(
        "INSERT OR IGNORE INTO supplier_items "
        "(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
        "SELECT ?,id,purchase_price_paise,security_paise,0 FROM cylinder_types WHERE active=1",
        (supplier_id,),
    )

    # An existing inactive catalogue association is reactivated, but its saved supplier rate is preserved.
    items = conn.execute(
        "SELECT id,purchase_price_paise FROM catalog_items WHERE active=1"
    ).fetchall()
    for item in items:
        conn.execute(
            "INSERT INTO supplier_catalog_items "
            "(supplier_id,item_id,purchase_price_paise,active) VALUES(?,?,?,1) "
            "ON CONFLICT(supplier_id,item_id) DO UPDATE SET active=1",
            (supplier_id, item["id"], item["purchase_price_paise"]),
        )

    # One-time marker prevents a manually removed link being recreated on every app launch.
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('sole_supplier_auto_link_v1',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(supplier_id),),
    )


def link_new_cylinder_to_sole_supplier(conn, cylinder_type_id):
    """Link a newly created/reactivated cylinder size only when there is exactly one active supplier."""
    supplier_id = sole_active_supplier_id(conn)
    if supplier_id is None:
        return
    cylinder = conn.execute(
        "SELECT purchase_price_paise,security_paise FROM cylinder_types WHERE id=? AND active=1",
        (cylinder_type_id,),
    ).fetchone()
    if not cylinder:
        return
    conn.execute(
        "INSERT INTO supplier_items "
        "(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) VALUES(?,?,?,?,0) "
        "ON CONFLICT(supplier_id,cylinder_type_id) DO UPDATE SET "
        "purchase_price_paise=excluded.purchase_price_paise,security_paise=excluded.security_paise",
        (supplier_id, cylinder_type_id, cylinder["purchase_price_paise"], cylinder["security_paise"]),
    )


def link_new_item_to_sole_supplier(conn, item_id):
    """Link a newly created/reactivated ordinary item only when there is exactly one active supplier."""
    supplier_id = sole_active_supplier_id(conn)
    if supplier_id is None:
        return
    item = conn.execute(
        "SELECT purchase_price_paise FROM catalog_items WHERE id=? AND active=1",
        (item_id,),
    ).fetchone()
    if not item:
        return
    conn.execute(
        "INSERT INTO supplier_catalog_items "
        "(supplier_id,item_id,purchase_price_paise,active) VALUES(?,?,?,1) "
        "ON CONFLICT(supplier_id,item_id) DO UPDATE SET "
        "purchase_price_paise=excluded.purchase_price_paise,active=1",
        (supplier_id, item_id, item["purchase_price_paise"]),
    )
```

## G2. `db.py` — backfill an existing database once

Inside `init_db()`, find the final existing migration block for v0.4.3. Immediately **before** its final `conn.commit()` line, insert:

```python
        # v0.4.5: if this existing database has exactly one active supplier, make it
        # the default supplier for every active cylinder size and catalogue item once.
        if not conn.execute(
            "SELECT 1 FROM settings WHERE key='sole_supplier_auto_link_v1'"
        ).fetchone():
            sole_supplier_id = sole_active_supplier_id(conn)
            if sole_supplier_id is not None:
                link_all_stock_to_supplier(conn, sole_supplier_id)
```

The helper functions in G1 can be defined below `init_db()` in the same file; Python resolves them when `init_db()` is called after the module has loaded.

## G3. `api/suppliers.py` — import the helpers

Find:

```python
from db import get_db, next_number, transaction
```

Replace with:

```python
from db import (get_db, next_number, transaction, sole_active_supplier_id,
                link_all_stock_to_supplier)
```

## G4. `api/suppliers.py` — when the first supplier is created, link all existing stock

In `supplier_create()`, find the `sid = db.execute(...).lastrowid` insert inside `with transaction(db):`.

Immediately after that insert, still inside the transaction, add:

```python
        if sole_active_supplier_id(db) == sid:
            link_all_stock_to_supplier(db, sid)
```

Do not link all stock when a second or later active supplier is created.

## G5. `api/suppliers.py` — when archiving a supplier leaves one, make the remaining supplier the default

In `supplier_delete()`, find:

```python
        db.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (sid,))
```

Immediately after it, still inside the transaction, add:

```python
        remaining_supplier_id = sole_active_supplier_id(db)
        if remaining_supplier_id is not None:
            link_all_stock_to_supplier(db, remaining_supplier_id)
```

This only adds missing links and reactivates inactive ordinary-item links. It preserves existing supplier-specific rates and never changes purchases or stock quantities.

## G6. `api/stock.py` — import the new-product link helpers

Find:

```python
from db import get_db, transaction
```

Replace with:

```python
from db import (get_db, transaction, link_new_cylinder_to_sole_supplier,
                link_new_item_to_sole_supplier)
```

In `cylinder_create()`, find the existing `UPDATE cylinder_types SET sale_price_paise=...` statement. Immediately after that update, add:

```python
        link_new_cylinder_to_sole_supplier(db, tid)
```

In `item_create()`, find the existing `UPDATE catalog_items SET sale_price_paise=...` statement. Immediately after that update, add:

```python
        link_new_item_to_sole_supplier(db, iid)
```

Both calls must remain inside their existing `with transaction(db):` blocks so the product and its supplier link are created atomically.

## G7. `api/stock_suppliers.py` — default omitted supplier IDs on the backend

Find:

```python
from db import get_db, transaction
```

Replace with:

```python
from db import get_db, transaction, sole_active_supplier_id
```

Replace the whole `_optional_supplier()` helper with:

```python
def _optional_supplier(db, data):
    # Omitted means use the only active supplier, if there is exactly one.
    # An explicitly blank value means the user chose Not sure / unassigned.
    if "supplier_id" not in data:
        return sole_active_supplier_id(db)
    raw = data.get("supplier_id")
    if raw in (None, "", "0"):
        return None
    return _supplier(db, int_field(raw, "Supplier", field="supplier_id", minimum=1))["id"]
```

This preserves the user's ability to explicitly choose **Not sure / skip** in a form. Calls which omit `supplier_id` use the sole supplier automatically.

## G8. `static/js/stock_extra.js` — allow the shared supplier select helper to preselect one supplier

Find the existing `supplierSelect` helper:

```javascript
  const supplierSelect = (name, label, list, blank) => '<label class="field"><span>' + label + '</span><select name="' + name + '" class="amt">' +
    (blank ? '<option value="">' + blank + "</option>" : "") + list.map((s) => '<option value="' + s.id + '">' + esc(s.name) + "</option>").join("") + "</select></label>";
```

Replace it with:

```javascript
  const supplierSelect = (name, label, list, blank, selectedId = null) => '<label class="field"><span>' + label + '</span><select name="' + name + '" class="amt">' +
    (blank ? '<option value="">' + blank + "</option>" : "") + list.map((s) =>
      '<option value="' + s.id + '"' + (String(selectedId) === String(s.id) ? ' selected' : '') + '>' + esc(s.name) + "</option>"
    ).join("") + "</select></label>";
```

## G9. `static/js/stock_extra.js` — preselect the sole supplier in the supplier and damaged-cylinder forms

In `addSupplier(tid)`, find:

```javascript
      supplierSelect("supplier_id", "Supplier", free) +
```

Replace with:

```javascript
      supplierSelect("supplier_id", "Supplier", free, null,
        ext.suppliers.length === 1 ? ext.suppliers[0].id : null) +
```

In `addDamaged()`, find:

```javascript
      supplierSelect("supplier_id", "Bought from", ext.suppliers, "Not sure / skip") +
```

Replace with:

```javascript
      supplierSelect("supplier_id", "Bought from", ext.suppliers, "Not sure / skip",
        ext.suppliers.length === 1 ? ext.suppliers[0].id : null) +
```

Keep the existing single supplier dropdown for the entire Add damaged cylinder form. This change only preselects it when there is exactly one active supplier.

## G10. `static/js/stock_extra.js` — preselect the sole supplier in the good-empty-cylinder Send back form

At the start of `sendBack(tid, sid)`, find:

```javascript
    const c = cyl(tid), s = sid ? supOf(tid).find((x) => x.supplier_id === sid) : null;
    const opts = ext.suppliers.map((p) => '<option value="' + p.id + '"' + (p.id === sid ? " selected" : "") + ">" + esc(p.name) + "</option>").join("");
```

Replace with:

```javascript
    const selectedSid = sid || (ext.suppliers.length === 1 ? ext.suppliers[0].id : 0);
    const c = cyl(tid), s = selectedSid ? supOf(tid).find((x) => x.supplier_id === selectedSid) : null;
    const opts = ext.suppliers.map((p) => '<option value="' + p.id + '"' + (p.id === selectedSid ? " selected" : "") + ">" + esc(p.name) + "</option>").join("");
```

When the action was opened from a supplier card, its supplier remains selected. When opened from the cylinder card and there is exactly one active supplier, that supplier is selected. The user can still choose the blank option.

## G11. `static/js/stock_extra.js` — default the damaged-dispatch checklist destination

In the new `sendDamagedBack()` function added in section D5, find:

```javascript
    const supplierOptions = (selected) =>
```

Immediately before it, add:

```javascript
    const soleSupplierId = ext.suppliers.length === 1 ? ext.suppliers[0].id : null;
```

Then find this line in the row template:

```javascript
        '<label class="field"><span>Supplier</span><select name="s' + id + '" class="amt">' + supplierOptions(r.supplier_id) + '</select></label>' +
```

Replace it with:

```javascript
        '<label class="field"><span>Supplier</span><select name="s' + id + '" class="amt">' + supplierOptions(r.supplier_id || soleSupplierId) + '</select></label>' +
```

The supplier attached to the damage batch remains the initial choice. If no supplier was recorded and exactly one active supplier exists, use that supplier as the default destination.

## G12. `static/js/purchase_new.js` — select the only supplier automatically on New purchase

At the bottom of the file, find the existing block:

```javascript
  const preferred = new URLSearchParams(location.search).get("supplier");
  if (preferred) {
    Api.get("/api/suppliers/" + encodeURIComponent(preferred))
      .then(async (supplier) => { setSupplier(supplier); await loadOptions(); })
      .catch((err) => showError("Could not load the selected supplier. " + err.message));
  }
  calculate();
```

Replace it with:

```javascript
  const preferred = new URLSearchParams(location.search).get("supplier");
  if (preferred) {
    Api.get("/api/suppliers/" + encodeURIComponent(preferred))
      .then(async (supplier) => { setSupplier(supplier); await loadOptions(); })
      .catch((err) => showError("Could not load the selected supplier. " + err.message));
  } else {
    Api.get("/api/suppliers").then(async (suppliers) => {
      if (suppliers.length !== 1) return;
      setSupplier(suppliers[0]);
      await loadOptions();
    }).catch(() => {});
  }
  calculate();
```

An explicit `?supplier=...` link still takes priority. With no preferred supplier, auto-select only when the API returns exactly one active supplier.

## G13. Regression test — verify one-supplier linking and multiple-supplier behaviour

Add this method inside `ApiTests` in `tests/test_api.py`:

```python
    def test_sole_supplier_auto_link_helpers(self):
        import sqlite3
        from db import (sole_active_supplier_id, link_all_stock_to_supplier,
                        link_new_cylinder_to_sole_supplier, link_new_item_to_sole_supplier)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE suppliers(id INTEGER PRIMARY KEY, active INTEGER NOT NULL);
            CREATE TABLE cylinder_types(
                id INTEGER PRIMARY KEY, active INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, security_paise INTEGER NOT NULL
            );
            CREATE TABLE supplier_items(
                supplier_id INTEGER NOT NULL, cylinder_type_id INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, security_paise INTEGER,
                empty_qty INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(supplier_id,cylinder_type_id)
            );
            CREATE TABLE catalog_items(
                id INTEGER PRIMARY KEY, active INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL
            );
            CREATE TABLE supplier_catalog_items(
                supplier_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(supplier_id,item_id)
            );
            INSERT INTO suppliers(id,active) VALUES(1,1);
            INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise)
                VALUES(10,1,130000,250000),(11,1,295000,500000);
            INSERT INTO catalog_items(id,active,purchase_price_paise)
                VALUES(20,1,25000),(21,1,40000);
        """)
        self.assertEqual(sole_active_supplier_id(conn), 1)
        link_all_stock_to_supplier(conn, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_items WHERE supplier_id=1").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_catalog_items WHERE supplier_id=1 AND active=1").fetchone()[0], 2)

        conn.execute("INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise) VALUES(12,1,50000,100000)")
        conn.execute("INSERT INTO catalog_items(id,active,purchase_price_paise) VALUES(22,1,7000)")
        link_new_cylinder_to_sole_supplier(conn, 12)
        link_new_item_to_sole_supplier(conn, 22)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM supplier_items WHERE supplier_id=1 AND cylinder_type_id=12").fetchone())
        self.assertIsNotNone(conn.execute("SELECT 1 FROM supplier_catalog_items WHERE supplier_id=1 AND item_id=22 AND active=1").fetchone())

        conn.execute("INSERT INTO suppliers(id,active) VALUES(2,1)")
        self.assertIsNone(sole_active_supplier_id(conn))
        conn.execute("INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise) VALUES(13,1,60000,120000)")
        conn.execute("INSERT INTO catalog_items(id,active,purchase_price_paise) VALUES(23,1,9000)")
        link_new_cylinder_to_sole_supplier(conn, 13)
        link_new_item_to_sole_supplier(conn, 23)
        self.assertIsNone(conn.execute("SELECT 1 FROM supplier_items WHERE cylinder_type_id=13").fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM supplier_catalog_items WHERE item_id=23").fetchone())
        conn.close()
```

This tests the database-linking helpers independently of the seeded demo suppliers in the API test database. It checks both existing stock backfill and newly-created stock, and confirms that a second active supplier disables automatic linking.

## G14. Local checks

Run these after applying sections A–G:

```bash
node --check static/js/stock_extra.js
node --check static/js/purchase_new.js
python -m py_compile db.py api/suppliers.py api/stock.py api/stock_suppliers.py tests/test_api.py
python -m unittest discover tests
```


## Files changed

- `schema.sql`
- `api/stock_suppliers.py`
- `api/stock.py`
- `api/suppliers.py`
- `db.py`
- `templates/stock.html`
- `static/css/stock.css`
- `static/js/stock_extra.js`
- `static/js/purchase_new.js`
- `tests/test_api.py`

## Deliberately not changed

- The current **Add damaged cylinder** form and its single supplier dropdown.
- The existing good-empty-cylinder **Send back** flow and its cash/bank refund recording.
- `cylinder_deposits` cancellation rows and calculations.
- Supplier purchase balances, purchase totals, GST, or payment records.
- Any GitHub files. Apply and test this locally, then push it yourself when satisfied.
