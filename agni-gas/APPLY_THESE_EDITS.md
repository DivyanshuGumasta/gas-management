# Edits to make by hand (existing files only)

The customer frontend is all NEW files, so nothing of yours was overwritten.
Four small edits in existing files switch it on. Each was tested.

## 1. `app.py`  (3 changes)

**a)** Top import - add `redirect`:
```python
from flask import Flask, redirect, render_template
```

**b)** In `PAGES`: change the `/customers` line and DELETE the whole `/udhaar` line:
```python
    "/customers": ("customers.html", "customers", "Customers", ""),
    # "/udhaar": ...   <- delete this line
```
Also rename the Data line title: `"Data & sync"` -> `"Data & Backup"`.

**c)** In `create_app()`, just ABOVE the `# Sale detail / receipt` comment, add:
```python
    app.add_url_rule("/customers/<int:cid>", "page_customer_detail",
                     make_view("customer_detail.html", "customers", "Customer", ""))
    app.add_url_rule("/udhaar", "page_udhaar", lambda: redirect("/customers"))
```

## 2. `templates/base.html`  (the `items` list in the sidebar)
- DELETE the line `('udhaar', '/udhaar', 'Uddhar & Payments', 'wallet'),`
- Change `'Data & sync'` to `'Data & Backup'`

## 3. `static/js/ui.js`  (function `receivePayment`, about line 130)
Change `"/udhaar?receive="` to `"/customers?receive="`

## 4. `tests/test_api.py`  (function `test_pages`)
Remove `"/udhaar"` from the list of URLs (it now redirects instead of returning 200),
and add `"/customers/1"` if you like.

## Later (not needed now)
- README status table: update the Customers / Udhaar rows and rename Data & sync.
- Merging Purchase + Supplier and the supplier-per-item link in Stock & Price are
  planned in `schema.sql` (comment at the bottom) and still to be built.
- PDF / Excel export: every Export button already calls `Cust.exportData(kind, scope)`
  in `static/js/customers_common.js`. Implement it there when we do exports.
