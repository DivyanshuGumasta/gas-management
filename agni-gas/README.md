# Agni Gas Agency - cylinder ledger & billing

Offline Windows app now, server-ready later. Flask + HTML/CSS/JS + SQLite.

## Run it

```
pip install -r requirements.txt
python app.py              # browser dev mode  -> http://127.0.0.1:5000
python desktop.py          # real app window (no browser look)
python seed_demo.py        # OPTIONAL sample data for demos (never on the client's DB)
python -m unittest discover tests
```
Build the .exe on Windows with `build_exe.bat`.
Data lives in `./data/agni.db` (dev) or `%APPDATA%\AgniGas` (.exe), with a
daily backup in a `backups` folder next to it (newest 30 kept).

## Architecture rule (this is what makes the server move cheap)

- Flask serves only the page shell (`templates/`) and static files.
- Pages hold no data. JavaScript loads everything from `/api/...` through `static/js/api.js`.
- Money: JSON/UI use rupee text (`"1450.50"`); the database stores whole paise. See `money.py`.
- Bill numbers come from `db.next_number()` inside the saving transaction.

### Moving to a server (the Rs 3,000 upgrade)
1. Run `app.py`'s API on the server (Oracle) with a real DB; keep `schema.sql` table names.
2. Host `static/` + the rendered pages anywhere; set `apiBase` in `static/js/config.js`.
3. Enable CORS and add login on the server.

## Status

| Screen | Frontend | Backend |
|---|---|---|
| Shell (sidebar, top bar, Quick Add, Select customer / supplier) | done | done |
| Home / dashboard | done | done |
| Sales, New sale, Tax invoice, Cancel bill | to be built | to be built |
| Customers, customer ledger, receave payment | done | list API done |
| Suppliers & Purchases (combined navigation; separate workflows) | shell + supplier list done; purchase view placeholder | supplier list API done; purchase API still to be built |
| Stock & Price, damaged cylinders | to be built | to be built |
| Reports (5, PDF + Excel) | to be built | to be built |
| Data & sync (backup / restore / export / import) | to be built | daily auto-backup done |
| Help & support | to be built | - |

Bill format: the **tax invoice** (Pdf1) is the customer bill - business name only,
no developer credits. Purchases are records of the supplier's own bill, with an
option to attach that bill; we do not generate purchase bills.

## changes in V0.2:
- Merged and Update the Customers / Udhaar rows and rename Data & sync.
- Merging Purchase + Supplier and the supplier-per-item link in Stock & Price are
  planned in `schema.sql` (comment at the bottom) and still to be built.
- PDF / Excel export: every Export button already calls `Cust.exportData(kind, scope)`
  in `static/js/customers_common.js`. Implement it there when we do exports.

## changes in V0.3:
- Combined Suppliers and Purchases into one sidebar workspace with separate tabs.
- Kept supplier and purchase backend responsibilities separate; no schema or API merge.
- The Suppliers tab uses the existing supplier-list endpoint. Purchase history remains a placeholder until its backend and screen are implemented.

## V0.3.2 — Suppliers & Purchases

- Combined workspace has Suppliers and Purchase history tabs.
- Supplier records support add, edit, search, archive, GSTIN/contact details and opening payable/advance.
- Supplier detail provides a running ledger, purchase list, payments, and supplier-specific cylinder prices.
- Payments allocated to a purchase are capped at that invoice's outstanding due; general payments may create an advance.
- Purchase entry records full cylinders received, empty cylinders returned to the supplier, and newly purchased empty cylinders.
- Full cylinder value uses the entered purchase rate. Newly purchased empty cylinders use that cylinder type's security price. Empty cylinders returned to the supplier reduce available empty stock and do not add to the invoice subtotal.
- GST is calculated on the subtotal. Any amount paid immediately is stored as a supplier-payment entry; a remaining amount is payable later.
- Optional supplier invoice attachment accepts PDF/JPG/PNG/WEBP up to 5 MB. It is stored in the purchase row as a BLOB so normal database backups include it.
- “Update purchase prices” saves the rate for that supplier and updates the global latest purchase price shown for the cylinder type.
- Purchase detail is an internal purchase record. The app stores/opens the supplier's own invoice; it does not issue a replacement purchase invoice.
- Existing `/suppliers` and `/purchases` URLs redirect to the combined workspace. `/purchases/new` remains the purchase-entry route.

 Balance rules

Supplier balance is calculated as:

`opening payable - opening advance + active purchase totals - active supplier payments`

A positive balance means **To pay**. A negative balance means **Supplier advance**. Payments may be linked to an individual purchase or recorded against the supplier generally.

 Database additions

The updated `schema.sql` creates `supplier_items`, `purchases`, `purchase_items`, and `supplier_payments`. It uses `CREATE TABLE IF NOT EXISTS`, so it can be applied to an existing V0.2/V0.3 database without deleting existing customer, supplier, sales or payment records.

Deliberate scope boundaries

- Purchase cancellation/reversal is not implemented in this version. Purchase history is retained; do not delete purchase rows manually because they affect stock and supplier balances.
- Supplier archive is allowed only when its payable/advance balance is settled. History is retained.
- Stock & Price's full management screen is still a separate unfinished module; this version reads the existing cylinder types and updates their stock counts.
- PDF/Excel exports for supplier/purchase statements are not included here; browser printing is available for the current supplier detail and purchase record views.


- Completed supplier CRUD, ledger, supplier payments and supplier item pricing.
- Completed purchase creation/history/detail, supplier invoice attachment, GST, initial/partial payment and stock movement updates.
- Kept the supplier + purchase frontend merge and existing customer module intact.

## V0.3.3 — Suppliers & Purchases

- Combined workspace has Suppliers and Purchase history tabs.
- Supplier records support add, edit, search, archive, GSTIN/contact details and opening payable/advance.
- Supplier detail provides a running ledger, purchase list, payments, supplier-specific cylinder prices, and a manageable catalogue of ordinary goods.
- Payments allocated to a purchase are capped at that invoice's outstanding due; general payments may create an advance.
- Purchase entry records full cylinders received, empty cylinders returned to the supplier, and newly purchased empty cylinders.
- Full cylinder value uses the entered purchase rate. Newly purchased empty cylinders use that cylinder type's security price. Empty cylinders returned to the supplier reduce available empty stock and do not add to the invoice subtotal.
- GST is calculated on the subtotal. Any amount paid immediately is stored as a supplier-payment entry; a remaining amount is payable later.
- Optional supplier invoice attachment accepts PDF/JPG/PNG/WEBP up to 5 MB. It is stored in the purchase row as a BLOB so normal database backups include it.
- “Update purchase prices” saves the rate for that supplier and updates the global latest purchase price shown for the cylinder type or ordinary catalogue item.
- Purchase detail is an internal purchase record. The app stores/opens the supplier's own invoice; it does not issue a replacement purchase invoice.
- Existing `/suppliers` and `/purchases` URLs redirect to the combined workspace. `/purchases/new` remains the purchase-entry route.

Balance rules

Supplier balance is calculated as:

`opening payable - opening advance + active purchase totals - active supplier payments`

A positive balance means **To pay**. A negative balance means **Supplier advance**. Payments may be linked to an individual purchase or recorded against the supplier generally.

Database additions

The updated `schema.sql` creates `supplier_items`, `purchases`, `purchase_items`, `supplier_payments`, `catalog_items`, `supplier_catalog_items`, `purchase_catalog_items`, and `catalog_stock_movements`. It uses `CREATE TABLE IF NOT EXISTS`, so it can be applied to an existing V0.2/V0.3 database without deleting existing customer, supplier, sales or payment records.

Cylinder types remain separate because full/empty cylinders have special stock and security handling. General catalogue items cover accessories and ordinary goods such as regulators, stoves, hoses, packets and other items. They have a name, unit, usual purchase price, sale price and stock quantity. A supplier can be linked to any catalogue item with its own supplier-specific purchase rate. Items can be created, attached from an existing catalogue, edited or removed from a supplier without deleting historical purchase lines.

General goods purchased are stored with an item-name/unit/rate snapshot on the purchase, and their stock is incremented in thousandths of a unit (0.001 precision). Whole-count units (`pcs`, `packet`, `box`, `set`, `pair`) require whole quantities. Historical purchase rows retain the details that were present when that purchase was recorded.

Deliberate scope boundaries

- Purchase cancellation/reversal is not implemented in this version. Purchase history is retained; do not delete purchase rows manually because they affect stock and supplier balances.
- Supplier archive is allowed only when its payable/advance balance is settled. History is retained.
- Stock & Price's full management screen is still a separate unfinished module. Cylinder types are configured there; general catalogue items are currently created/edited from a supplier's Items supplied tab or the New purchase form.
- PDF/Excel exports for supplier/purchase statements are not included here; browser printing is available for the current supplier detail and purchase record views.

Version history

V0.3.3
- Completed supplier CRUD, ledger, supplier payments and supplier item pricing.
- Completed purchase creation/history/detail, supplier invoice attachment, GST, initial/partial payment and stock movement updates.
- Added a general item catalogue for ordinary goods, supplier-item links, create/edit/attach/remove controls, and quantity-based purchase stock movements.
- Kept cylinder full/empty accounting separate from general goods, and preserved historical item details on purchase lines.
- Kept the supplier + purchase frontend merge and existing customer module intact.