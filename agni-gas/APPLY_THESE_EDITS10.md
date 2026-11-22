# APPLY_THESE_EDITS10 — Stock & Price screen (frontend only)

**Frontend only, as asked.** The page is finished and tested in a browser, but it reads from a Stock API that does not
exist yet (next step), so until then `/stock` shows a red "Could not load stock" bar with a Retry button. The exact
API the page expects is in `STOCK_API_CONTRACT.md`.

## Easy way
Unzip `v0.4.1_stock_screen.zip` over `agni-gas/`. It contains 3 new files and 1 changed file (`app.py`, one line).

## By hand (4 changes)
| # | File | What |
|---|------|------|
| 1 | `templates/stock.html` | NEW file, copy from the zip |
| 2 | `static/js/stock.js` | NEW file, copy from the zip |
| 3 | `static/css/stock.css` | NEW file, copy from the zip |
| 4 | `app.py` | change one word, below |

### `app.py` — in the `PAGES` dict (search for `"/stock"`)
**Find:**
```python
    "/stock": ("placeholder.html", "stock", "Stock & Price",
```
**Replace with:**
```python
    "/stock": ("stock.html", "stock", "Stock & Price",
```
(Only `placeholder.html` → `stock.html`; keep the rest of that line as it is.)

## What is on the page (top to bottom, as in the Figma)
1. Header: Export ▾ (PDF/Excel placeholder), **Add item**, New purchase.
2. Five number cards: Ready to sell, To refill, With customers, Total owned, **Other items**; then Stock at cost / Stock at sale price.
3. Damaged cylinders (per size, "Update damaged stock").
4. **Cylinder stock & pricing**: one card per size with sale / wholesale / purchase price, Full / Empty / With customers,
   security, stock value, margin, **which suppliers sell it** (or "No supplier linked yet"), and Adjust stock / Update price / Edit / Delete.
5. **Other items** (new, between cylinders and history): gas pipes, regulators, stoves. Same card style, with unit, quantity,
   prices, margin, suppliers and the same four buttons. "Add item" is here and in the header.
6. **Stock history**: size chips, a **Filter** button (shows "coming in the next step" for now), Export ▾.

All popups (Add cylinder, Add item, Adjust stock, Update price, Edit, Delete confirm) are built; Update price on a
cylinder says that a new purchase price only applies to cylinders bought from now on (matches the stock-lots rule).

## Changes from the Figma (tell me if you disagree)
- Title line: "Gas cylinders and other items like gas pipes, stoves and regulators" (the design said "loose gas ... chulhas").
- The "0 damaged" badge is green when nothing is damaged and red otherwise (the design had it red even at zero).
- The Figma has no "Items" section; this is the new one you asked for.
- Damaged cylinders is built as the design shows it (counts per size). Its rules are still waiting for your answer.

## Tested
A real-browser run against a fake in-memory API (not included): page renders like the design, adjust / update price /
add item work and refresh the cards, server errors show inside the popup, empty-field check, delete refusal message,
damaged badge, size chips, no sideways scroll on a phone width. Not tested against the real backend (it does not exist yet).
