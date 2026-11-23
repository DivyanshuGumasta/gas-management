# Sales API contract (v0.6.2)

All endpoints are under `/api`. Money values are strings in rupees with two decimals. Database money is stored as integer paise. Sales are persistent SQLite records; the old in-memory mock is retired.

## GET /sales

Optional query parameters: `from`, `to`, `q`.

Returns:

- `summary.total`: taxable value + GST across all matching active bills; excludes refundable deposits.
- `summary.bills`: matching active bill count.
- `summary.cylinders`: full cylinders sold (refill + new full).
- `summary.deposits_held_change`: deposits received minus deposits refunded on matching active bills.
- `summary.udhaar`: outstanding amount on matching active bills.
- `sales`: newest 500 matching bills. Each row includes `id`, `number`, `date`, 12-hour `time`, `customer`, `customer_id`, `label`, `cylinders`, `total` (actual invoice total including deposits), `sales_value` (taxable + GST), `due`, and `status`.
- `truncated`: true when more than 500 rows match. The summary is still calculated over all matching bills.

## GET /sales/<id>

Returns the saved invoice snapshot: `id`, `number`, `date`, 12-hour `time`, `status`, `customer`, `business`, `legacy`, `place_state_code`, `reverse_charge` (always false), `note`, `lines`, `subtotal`, `discount`, `taxable`, `cgst`, `sgst`, `igst`, `gst`, `gst_percent`, `deposit_received`, `deposit_refunded`, `total`, `paid`, `due`, `received_in`, `cancel_reason`, and `cancelled_at`.

Each line includes `kind`, `action`, `name`, `hsn`, `qty`, `unit`, `rate`, `amount`, `taxable`, `gst_rate` (string or null), `cgst`, `sgst`, `igst`, `detail`, and `supplier_id`.

Legacy bills without `sale_lines` are returned with `legacy: true`, a live customer name/phone fallback, `business: {}`, and their original `sale_items` represented as product lines.

## POST /sales

Creates an invoice and applies stock, customer cylinder-ledger, customer-deposit, supplier-empty, supplier-deposit and catalogue-stock movements in one transaction.

Body fields: `customer_id`, `date`, `place_state_code`, `lines`, `items`, `discount`, `payment` (`paid`, `partial`, `credit`), `received_in` (`cash`, `bank`), `paid`, and `note`.

Each cylinder `lines[]` row contains `cylinder_type_id`, `refill`, `new_full`, `new_empty`, `empty_in`, `damaged_in`, `rate`, `security`, optional `supplier_id` (stock source), optional `return_supplier_id` (good/damaged return owner), `deposit_back`, and optional `deposit_each`.

The old bill-level `damaged_supplier_id` is accepted as a fallback for `return_supplier_id` on damaged-return rows. Browser-sent `gst_rate`, `hsn`, and `reverse_charge` values are ignored. HSN and GST rate come from Stock & Price. Reverse charge is always false.

If exactly one active supplier exists it is selected automatically. With multiple active suppliers, stock movements require an explicit supplier. A return can infer its supplier when the customer's holdings for that size identify exactly one supplier; otherwise the API returns 422 asking for `return_supplier_id`. A selected supplier must be linked to the cylinder size in Stock & Price.

A refill by itself does not require or reduce customer-held cylinders. `empty_in` and `damaged_in` must not exceed the customer's held count. When a single cylinder row combines a refill with a separate return action, the combined counts cannot reuse the same tracked cylinder. Customer deposits are separate from supplier deposits.

Returns `201` with `{ "id": 12, "number": "S-00012" }`.

## POST /sales/<id>/cancel

Body: `{ "reason": "optional reason up to 200 characters" }`.

Cancels paid and unpaid invoices when stock safety allows. A bill with damaged cylinders already dispatched to a supplier cannot be cancelled. A reversal that would make stock or customer-held cylinders negative is rejected. The invoice remains in history with the same number and status `cancelled`; `paid_paise` is preserved.

Returns `{ "ok": true, "refund": "1450.00" }`. The refund is the positive amount previously received, and it must be handed back using the original `received_in` method. A payout invoice whose `paid` value is negative returns `0.00`.

## GET /sales/<id>/pdf

Returns a downloadable `application/pdf` generated from the saved invoice snapshot. Legacy bills are supported.

## Customer cylinder endpoints

- `GET /customers/<id>/held-cylinders`: existing simple `{ "<cylinder_type_id>": qty }` response; retained for compatibility.
- `GET /customers/<id>/holdings`: list of supplier-specific holdings, each with `cylinder_type_id`, `name`, `supplier_id`, `supplier_name`, `qty`, `deposit_each`, and `deposit_total`. Legacy ledger-only cylinders appear as an unassigned zero-deposit entry.
- `POST /customers` may include `held: [{"cylinder_type_id":1,"qty":2,"supplier_id":3,"deposit_each":"2500.00"}]`. Omitting `supplier_id` uses the sole active supplier when exactly one exists; explicit null means unassigned.
- `POST /customers/<id>/opening-cylinders` accepts the same `held` list and returns the updated holdings.
- `PUT /customers/<id>` ignores `held`; editing a customer never changes cylinder history.
- `POST /customers/<id>/return-empties` is retired and returns 410. Record returns through Sales → New sale so the deposits remain correct.

## GET /states

Returns the existing Indian state/territory codes and names sorted by name: `[{"code":"22","name":"Chhattisgarh"}, ...]`.
