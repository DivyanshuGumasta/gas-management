# APPLY_THESE_EDITS5 — Agni Gas V0.3.4

This patch updates the existing `agni-gas/` project. It is an **overlay**, not a new application. Paths in the ZIP are relative to the `agni-gas/` directory.

The implementation follows the current Figma screens for Purchases (PDF page 18), New purchase (page 19), Purchase record (page 20), Supplier profile (page 21) and Suppliers list (page 22), together with the corrections in Claude's APPLY_THESE_EDITS5 list.

## Before applying

1. Stop the running app.
2. Back up the project folder and `data/` directory. The database is not included in this ZIP and must remain where it is.
3. Check that your local code is based on the latest V0.3.3 repository state. Do not overwrite any newer changes you have made locally without reviewing them.

## Step 1 — Repository hygiene (run from the Git repository root)

The public repository currently tracks runtime files that should not be public source files: SQLite database/backups and Python bytecode. The ZIP includes `agni-gas/.gitignore`, but Git does not stop tracking files that are already tracked until you untrack them.

Run:

```bash
find agni-gas -type d -name __pycache__ -prune -exec git rm -r --cached --ignore-unmatch {} +
git rm -r --cached --ignore-unmatch agni-gas/data
git rm --cached --ignore-unmatch agni-gas/api/people.py
rm -f agni-gas/api/people.py
git add agni-gas/.gitignore
git commit -m "chore: stop tracking runtime data and dead API module"
```

`git rm --cached` leaves your local database and backup files on disk. The `data/` ignore rule prevents them being added again.

**Public-repository warning:** deleting a database in a new commit does not erase it from older Git history. If `data/agni.db` or a backup ever contained real agency/customer records, treat those records as exposed: make the repository private immediately and remove the sensitive blobs from history (or delete the repository). Do not assume a later repository deletion is a substitute for responding to a data exposure.

## Step 2 — Apply the source overlay

From the repository root:

```bash
unzip -o agni-gas-v0.3.4-design-aligned.zip -d agni-gas
```

The ZIP contains files under `api/`, `templates/`, `static/`, `tests/`, plus `.gitignore`, `README.md`, this instruction file and the V0.3.4 changelog. It does not contain `data/`, backups, `.venv`, build output or `__pycache__`.

Review `git status` and `git diff` before committing:

```bash
git status --short
git diff --stat
git diff
```

Then commit the application changes:

```bash
git add agni-gas
git commit -m "feat: align supplier and purchase flows with Figma"
```

## What this patch changes

### Supplier and purchase lists

- Shared `.tabs`, `.chip`, `.list-card`, `.row`, `.sum-grid` and `.sum-card` styles are reused from `customers.css`.
- The Suppliers page has search, shared Export dropdown, Add supplier and supplier rows. The additional supplier summary cards and CSV export have been removed.
- The Purchases page follows Figma page 18: Today, Last 7 days, This month, All and Custom filters; the two Purchases and Payable summary cards; Export dropdown; New purchase; and purchase rows.
- Supplier profile Export uses the same shared Export dropdown placeholder. The old CSV buttons and `exportCsv` implementation are removed.

### Supplier profile and items

- Supplier profile keeps Ledger, Purchases and Items supplied tabs, the supplier balance/profile, Purchase, Pay and Statement actions.
- The cylinder checklist remains. The supplier can link/unlink available cylinder types and maintain a separate purchase rate for each.
- Ordinary catalogue master items are **not created** on the supplier page. “Link item” lists existing active entries from `/api/items`, excluding entries already linked to this supplier.
- If `/api/items` is empty, the dialog says: “No items yet. Create items in Stock & Price first.”
- Editing an ordinary item relationship changes only that supplier's purchase rate. Item name, unit and sale price belong to Stock & Price.

### New purchase

- Supplier is selected through the shared supplier picker in a card, rather than a plain `<select>`.
- The “+ Add supplier” and “Create item” controls have been removed from this form.
- Cylinder cards show Rate, Full in and Empty out minus/plus steppers, a “Bought new empty cylinders?” expander, and an Amount footer.
- The payment panel has Date, Paid / Partially paid / Credit, Paid from, Paid to supplier, GST rate/amount, Update purchase prices, optional supplier-bill attachment, Note and totals.
- The ordinary-goods section is labelled “Other items”. Its rows can select only items linked to the currently selected supplier. There is no item-creation path in this form.

### Backend rules

- `GET /api/purchases/options` returns `[]` when no supplier is selected and returns only active cylinder types linked to the selected supplier.
- `POST /api/purchases` validates the cylinder/supplier link before calculating the purchase and again inside the write transaction. A stale form cannot save a cylinder after its supplier link is removed.
- Ordinary catalogue purchases continue to validate an active supplier/catalogue link.
- `POST /api/suppliers/<sid>/catalog-items` requires an existing `item_id`; it cannot create a master item.
- `PUT /api/suppliers/<sid>/catalog-items/<item_id>` updates only the supplier-specific purchase price.
- No schema migration is required by this patch. It uses the existing V0.3.2/V0.3.3 supplier, purchase and catalogue tables.

## Step 3 — Test in your project environment

Activate the project's virtual environment, then from `agni-gas/`:

```bash
python -m unittest discover tests
python app.py
```

The actual test file in this repository is `tests/test_api.py` (there is no `tests/test_suppliers_purchases.py`). This patch changes the purchase-number assertion so it does not depend on test execution order, adds the no-linked-cylinder test, and seeds catalogue master items directly in the test database before linking them to suppliers.

Check these flows manually in the running application:

1. Add a supplier and link only one cylinder type. New purchase should show only that cylinder.
2. Select another supplier with no cylinder links. The cylinder area should show the “no linked cylinders” message.
3. Add a master catalogue item through Stock & Price (when that module is present), then link it from Supplier → Items supplied.
4. Try a supplier purchase. The Other items selector should contain only that supplier's linked goods.
5. Save a purchase with a cylinder line and/or ordinary goods, GST and a partial payment. Verify stock, supplier balance, detail record and the original attachment.
6. Open an older purchase to confirm its saved item name, unit and rate have not changed when current supplier rates are edited.

## Limitations retained intentionally

- Stock & Price master-item creation/edit UI is still a separate module. Until it is built, the supplier “Link item” list will be empty unless catalogue items already exist in the database.
- Export dropdowns call the shared `Cust.exportData()` placeholder; actual PDF/Excel exports are not implemented by this patch.
- Purchase cancellation/reversal remains unimplemented. Do not delete purchase rows manually because they affect stock and supplier balances.
- The purchase detail page is an internal record, not a replacement supplier invoice. It opens the supplier's original attachment, can be printed and can share purchase details through WhatsApp.
