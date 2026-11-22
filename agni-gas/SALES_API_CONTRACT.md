# Sales API contract (v0.5 frontend)

The screens already call these URLs. `api/mock_sales.py` is a temporary in-memory copy; the real backend replaces it
with the same JSON. Money is a string `"1450.50"` in rupees. Dates are `YYYY-MM-DD`.

## GET /api/sales?from=&to=&q=
`from`/`to` optional (the page sends them for Today / Last 7 days / This month / Custom; none for All). `q` matches bill number or customer name.
```json
{ "summary": { "total": "7000.00", "bills": 2, "cylinders": 3, "udhaar": "2900.00" },
  "sales": [ { "id": 5, "number": "S-00005", "date": "2026-11-23", "time": "10:23 AM", "customer": "tiku",
               "customer_id": 4, "label": "1 x 15 kg", "cylinders": 1, "total": "4100.00", "due": "0.00",
               "status": "paid" } ] }
```
`status`: `paid` | `partial` | `udhaar` | `cancelled`. Newest first. `summary` ignores cancelled bills. `cylinders` = full cylinders sold (refill + new full).
`customer` is `"Walk-in customer"` and `customer_id` null for walk-ins.

## GET /api/sales/<id>
```json
{ "id": 5, "number": "S-00005", "date": "2026-11-23", "time": "10:23 AM", "status": "paid",
  "customer": { "id": 4, "name": "tiku", "phone": "98765 43210" },     // null for walk-in
  "note": null,
  "lines": [ { "kind": "refill", "name": "15 kg", "qty": 1, "rate": "4100.00", "amount": "4100.00", "detail": "Refill" } ],
  "subtotal": "4100.00", "discount": "0.00", "gst_percent": 0, "gst": "0.00", "total": "4100.00",
  "paid": "4100.00", "due": "0.00", "received_in": "cash" }
```
Line `kind`: `refill` (rate = price) · `new_full` (rate = price + security) · `new_empty` (rate = security) · `empty_in` (free, amount 0) · `item` (other items; `detail` = unit).

## POST /api/sales  → 201 `{ "id": 5, "number": "S-00005" }`
```json
{ "customer_id": 4,                      // null = walk-in (cash only)
  "date": "2026-11-23",
  "lines": [ { "cylinder_type_id": 3, "refill": 1, "new_full": 0, "new_empty": 0, "empty_in": 1,
               "rate": "4100.00", "security": "6000.00" } ],   // only sizes that have a quantity; rate is editable per sale
  "items": [ { "item_id": 2, "qty": "2", "rate": "350.00" } ],
  "discount": "50", "gst_percent": "5",
  "payment": "paid",                      // paid | partial | credit (udhaar). partial/credit need a customer
  "received_in": "cash",                  // cash | bank
  "paid": "1000",                         // only used for partial; paid = total, credit = 0
  "note": "" }
```
Errors: `{ "error": "...", "field": "..." }` (400/404/409) e.g. not enough full cylinders, walk-in with udhaar.

## POST /api/sales/<id>/cancel  → `{ "ok": true }`
Marks the bill cancelled; stock goes back (to the same lots), udhaar removed, the record is kept. 409 if already cancelled.

## Real backend must also (not in the mock)
Take full cylinders out of the oldest lots and store the cost; empties-in/refills change empty stock; customer cylinders held;
udhaar into the customer ledger; payment into cash/bank; items stock down; numbers `S-00001…` from `next_number`.
