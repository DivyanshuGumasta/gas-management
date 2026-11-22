# Stock & Price — what the frontend expects from the backend (built in the next step)

Money is a rupees string like `"1450.00"`. Counts are integers. Item quantities may have decimals (`12.5`).
Errors use the usual `{ "error": "message", "field": "name_of_input" }` with 400/404/409.

## Read
**`GET /api/stock`**
```json
{
  "summary": { "ready": 20, "to_refill": 3, "with_customers": 1, "total_owned": 24, "other_items": 2,
               "stock_cost": "94650.00", "stock_value": "103450.00", "damaged_total": 0 },
  "cylinders": [ { "id": 1, "name": "5 kg", "kg": 5, "full": 3, "empty": 1, "damaged": 0, "with_customers": 0,
                   "sale_price": "1450.00", "wholesale_price": "1400.00", "purchase_price": "1300.00", "security": "2500.00",
                   "low": true, "stock_value": "3900.00", "margin": "150.00", "suppliers": ["goo goo"] } ],
  "items":     [ { "id": 1, "name": "Gas pipe", "unit": "metre", "qty": 12.5, "sale_price": "90.00", "purchase_price": "60.00",
                   "low": false, "stock_value": "750.00", "margin": "30.00", "suppliers": ["goo goo"] } ]
}
```
- `total_owned` = full + empty + with_customers (+ damaged if you decide). `stock_cost` should come from **stock lots**
  (qty_left × lot cost), not from the current purchase price. `stock_value` = full × sale price.
- `low`: backend decides the rule (e.g. full ≤ 5 for cylinders).
- `suppliers`: names of suppliers linked to that cylinder/item (supplier_items / supplier_catalog_items).

**`GET /api/stock/history?limit=31&cylinder_type_id=`** → newest first
```json
[ { "id": 9, "at": "2026-11-14 10:23:00", "title": "15 kg · Sale", "ref": "S-00005",
    "changes": [ { "n": -1, "label": "Full" }, { "n": 1, "label": "Empty" } ] } ]
```
Cylinder movements come from `stock_movements`; item movements from `catalog_stock_movements`
(`title` "Gas pipe · Purchase", `changes` `[{ "n": 12.5, "label": "metre" }]`). Manual adjustments appear as "… · Adjusted".
(The Filter popup in the next step adds more query parameters.)

## Cylinders
| Call | Body | Notes |
|---|---|---|
| `POST /api/cylinders` | `weight_kg, sale_price, wholesale_price, purchase_price, security, full, empty` (all strings; prices/counts may be blank = 0) | Name becomes "5 kg". Duplicate size → 409. Starting full stock creates an *opening* lot. |
| `PUT /api/cylinders/<id>` | `weight_kg` | Rename only. |
| `PUT /api/cylinders/<id>/prices` | `sale_price, wholesale_price, purchase_price, security` | Does **not** touch existing lots. |
| `POST /api/cylinders/<id>/adjust` | `full, empty, note` = the counts now on the shelf | Writes a stock movement of the difference. Adding full cylinders adds an `adjustment` lot; removing consumes oldest lots first. |
| `DELETE /api/cylinders/<id>` | — | 409 with a clear message if it still has stock / is held by customers; otherwise soft-delete (`active=0`). |
| `PUT /api/stock/damaged` | `{ "counts": { "<cylinder id>": 0 } }` | Sets damaged counts. (Damaged rules are still to be decided.) |

## Items (catalogue)
| Call | Body | Notes |
|---|---|---|
| `POST /api/items` | `name, unit, qty, sale_price, purchase_price` | This is the only place items are created. |
| `PUT /api/items/<id>` | `name, unit` | |
| `PUT /api/items/<id>/prices` | `sale_price, purchase_price` | |
| `POST /api/items/<id>/adjust` | `qty, note` = quantity now | Writes `catalog_stock_movements`. |
| `DELETE /api/items/<id>` | — | 409 if it still has stock; else soft-delete. |

`GET /api/items` already exists (used by the supplier "Link item" popup) and must keep working.
