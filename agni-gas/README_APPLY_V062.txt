Agni Gas Agency — v0.6.2 local override
========================================

BASELINE
--------
This override is built on the v0.6.1 source at commit:
3b0609a0f647db44a5c05743670b33cb33f8ad7f

It contains the v0.6.2 backend, frontend, invoice/PDF, and regression-test changes.
It is a LOCAL override only. It does not make or require any GitHub commit or push.

Revision 1 hotfix: optional agency PAN is now handled as blank when omitted. This
keeps legacy/API callers without a PAN field compatible; GSTIN/PAN consistency
validation still applies whenever both values are supplied.

INSTALL
-------
1. Close the Agni Gas Agency app.
2. Make a backup of your existing agni-gas folder (or at least every file listed
   in this ZIP) before overwriting anything.
3. Open the ZIP and extract its contents directly INTO your existing agni-gas
   folder. For example, api/sales.py in the ZIP must replace
   agni-gas/api/sales.py. Allow files to be overwritten.
4. From the agni-gas folder, run exactly one cleanup helper:
     Windows:       apply_v062_cleanup.bat
     macOS/Linux:   sh apply_v062_cleanup.sh
   This removes only api/mock_sales.py, which v0.6.2 retires. The helper refuses
   to run unless it is started from the agni-gas folder.
5. Restart the application. The database changes are additive migrations; keep
   your existing data/ folder and database in place.

IMPORTANT EXCLUSIONS
-------------------
This ZIP intentionally does NOT contain data/, .gitignore, __pycache__, or any
APPLY_THESE_EDITS*.md / apply_these_edits*.md instruction files. It will not
replace your local database, backups, ignore rules, or those instruction docs.

WHAT CHANGED
------------
- Supplier-aware cylinder ownership and stock movement on each sale line.
- Customer opening cylinder holdings, deposit tracking, good returns, damaged
  returns, refunds/forfeitures, and stock-safe paid invoice cancellation.
- Sales-value summaries exclude refundable cylinder deposits while bill totals
  continue to show the invoice amount.
- Stock-controlled HSN/GST values, state selection, GST/PAN validation, compact
  tax labels, and deterministic largest-remainder discount allocation.
- Tax invoice/document payload, retained-deposit accounting, Indian amount in
  words, printable invoice and multi-page PDF improvements.
- New v0.6.2 backend and invoice-document regression tests; updated sale tests
  and Sales API contract.

TESTING NOTES
-------------
Static validation performed for this build:
- Python source compilation passed.
- JavaScript syntax checks passed.
- Invoice PDF smoke test rendered and was visually inspected, including a
  multi-page invoice and retained-deposit text.

The Flask API integration suite was NOT run in this workspace because Flask is
not installed here and package downloads are unavailable from this environment.
Run your test suite in your normal project environment from agni-gas:

    python -m unittest discover -s tests

If that environment uses a virtualenv, activate it first. Review any reported
failures before using v0.6.2 for live agency transactions.
