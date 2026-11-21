# APPLY_THESE_EDITS6 — supplier item links and supplier invoice handling

Paths are relative to the `agni-gas/` folder. This is a focused update on top of the V0.3.4 design-aligned supplier/purchase files. It does not change the database schema.

## 1. Replace the following files

- `api/suppliers.py`
- `api/purchases.py`
- `static/js/supplier_detail.js`
- `static/js/suppliers_common.js`
- `static/js/purchase_detail.js`
- `static/js/purchase_new.js`
- `static/css/suppliers_purchases.css`
- `templates/purchase_detail.html`
- `templates/purchase_new.html`
- `tests/test_api.py`
- `README.md`
- `V0.3.5_CHANGELOG.md`

The ZIP keeps the root-relative folder structure. Extract it into `agni-gas/` and allow these files to overwrite their existing copies.

## 2. Supplier → Items supplied

The cylinder section now shows only cylinder sizes currently linked to that supplier. The user can:

- Add a cylinder size from the existing Stock & Price cylinder types.
- Update the purchase rate for that supplier without changing the global cylinder price.
- Remove the link when that supplier stops supplying that size.

Removing a supplier link does not alter stock, supplier balances or old purchase records. An unlinked size is no longer offered in the purchase form. Ordinary catalogue items continue to be linked from the existing Stock & Price catalogue and can have a supplier-specific purchase rate.

New/updated endpoints:

- `GET /api/suppliers/<sid>/items` — linked cylinder sizes only.
- `GET /api/suppliers/<sid>/available-cylinders` — active cylinder sizes not linked to the supplier.
- `POST /api/suppliers/<sid>/items` — link a cylinder size and supplier purchase rate.
- `PUT /api/suppliers/<sid>/items/<tid>` — update that supplier's rate.
- `DELETE /api/suppliers/<sid>/items/<tid>` — remove the supplier link.

`GET /api/purchases/options` returns an empty list until a supplier is selected and then returns only that supplier's linked cylinder sizes. Purchase creation rechecks the links on the server.

## 3. Supplier invoice handling

The purchase is saved as an internal inventory/ledger entry. The app does not create a supplier bill, print a supplier invoice, or provide a WhatsApp share of an Agni-generated purchase document.

The supplier's original invoice can be attached immediately during purchase registration or later from the saved purchase detail page. The detail page displays the original uploaded image inline or previews the original PDF. The user can replace or remove the attachment without changing the purchase, stock or supplier ledger.

New attachment endpoints:

- `POST /api/purchases/<pid>/attachment` — attach or replace the supplier's original PDF/image (max 5 MB).
- `DELETE /api/purchases/<pid>/attachment` — remove only the file attachment.
- `GET /api/purchases/<pid>/attachment` — serve the original attached file inline.

## 4. Database and backup

No schema migration is required. The existing attachment columns already store the supplier's original filename, MIME type and file bytes in the purchase row. Existing database files and backups must be kept.

## 5. Test

Run from `agni-gas/`:

```bash
python -m unittest discover tests
python app.py
```

The updated tests cover adding, editing and removing supplier cylinder links; supplier-specific purchase filtering; rejection of unlinked cylinder purchases; and adding, replacing and removing a supplier invoice after the purchase is registered.
