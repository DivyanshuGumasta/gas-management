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
| Customers, customer ledger | to be built | list API done |
| Udhaar & payments, Receive payment | to be built | to be built |
| Purchases (record + attach supplier's bill) | to be built | to be built |
| Suppliers | to be built | list API done |
| Stock & Price, damaged cylinders | to be built | to be built |
| Reports (5, PDF + Excel) | to be built | to be built |
| Data & sync (backup / restore / export / import) | to be built | daily auto-backup done |
| Help & support | to be built | - |

Bill format: the **tax invoice** (Pdf1) is the customer bill - business name only,
no developer credits. Purchases are records of the supplier's own bill, with an
option to attach that bill; we do not generate purchase bills.
