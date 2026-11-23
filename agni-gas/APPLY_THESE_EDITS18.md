# APPLY_THESE_EDITS18 — v0.6.1: downloadable sales invoice PDF + customer cylinder checks

Paths are relative to `agni-gas/`. **Base:** GitHub `main` commit `5ab45c93b4d082365976e38d25a7ab8eaf5bb81f` (v0.6.0). Apply this patch to the v0.6.0 code you just pushed. It does not include or repeat the v0.6.0 work in `APPLY_THESE_EDITS17.md`.

**A** = create a whole file. **B** = exact small edits. **C** = tests and verification. Apply sections in order. Back up the active database first (`data/agni.db` by default; check `AGNI_DATA_DIR` if you override it). **Do not push these changes until the tests pass.**

## What changes

* A saved invoice gets a real **Download PDF** action. It creates an A4 PDF on the server from the immutable invoice snapshots, rather than relying on the browser print dialog. The existing **Print** option remains available.
* A customer's cylinders recorded in the customer-held cylinder ledger are treated as empty cylinders available for refill/return. If that customer holds none of that cylinder size, the refill, good-empty-return, and damaged-return controls are disabled. The server independently validates the same rule.
* A refill, good empty return, or damaged return cannot consume the same customer-held cylinder twice on one invoice.
* Each cylinder/catalogue product line displays a GST percentage input. It is prefilled from **Stock & Price** and can be adjusted for that invoice. The chosen rate is validated, used for the tax calculation, and snapshotted on the invoice. This does not change the product's saved stock GST rate.
* Existing GST amount, CGST/SGST/IGST split, HSN snapshots, deposits, and accounting separation remain in place.

## Important notes

1. GST percentage overrides are invoice-specific only. They do not update Stock & Price. Confirm any tax-rate change with the CA before issuing an invoice.
2. A customer's held-cylinder count is taken from `cylinder_ledger`, grouped by cylinder type. A cylinder issued as a new full cylinder is therefore eligible for a later refill/return. A refill itself leaves the customer's ownership count unchanged.
3. Walk-in refill sales remain possible because no customer account exists against which to verify held cylinders. A selected customer with zero held cylinders cannot create a refill or return for that size.
4. This patch adds ReportLab to `requirements.txt`. Run the normal requirements installation after applying it.
5. The PDF is generated from the saved invoice snapshot, including the saved customer and agency information. Later edits to stock/customer/business details do not rewrite an old invoice.
6. This patch does not make any changes to GitHub.

---

# A. CREATE WHOLE FILE

## A1. Create `invoice_pdf.py`

Paste the complete file below. This generates an A4 invoice PDF from the payload returned by `api.sales._sale_payload()`.

```python
"""Build a downloadable A4 PDF from a saved Agni Gas invoice snapshot."""
from decimal import Decimal, InvalidOperation
from io import BytesIO
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


NAVY = colors.HexColor("#20364F")
PALE = colors.HexColor("#F1F4F7")
GRID = colors.HexColor("#D7DDE4")
MUTED = colors.HexColor("#5D6976")
GREEN = colors.HexColor("#28734B")
RED = colors.HexColor("#A52B2B")
_FONT_CACHE = None


def _register_fonts():
    """Use a common installed Unicode font where available; otherwise use PDF core fonts."""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE

    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        (str(Path(windir) / "Fonts" / "arial.ttf"),
         str(Path(windir) / "Fonts" / "arialbd.ttf")),
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for regular_path, bold_path in candidates:
        if Path(regular_path).is_file() and Path(bold_path).is_file():
            try:
                pdfmetrics.registerFont(TTFont("AgniInvoice", regular_path))
                pdfmetrics.registerFont(TTFont("AgniInvoice-Bold", bold_path))
                _FONT_CACHE = ("AgniInvoice", "AgniInvoice-Bold")
                return _FONT_CACHE
            except Exception:
                continue
    _FONT_CACHE = ("Helvetica", "Helvetica-Bold")
    return _FONT_CACHE


def _decimal(value):
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
        return result if result.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _money(value):
    return "Rs. {:,.2f}".format(_decimal(value))


def _safe(value):
    return escape(str(value if value is not None else "")).replace("\n", "<br/>")


def _amount_words(value):
    ones = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def under_hundred(number):
        return ones[number] if number < 20 else tens[number // 10] + (" " + ones[number % 10] if number % 10 else "")

    def words(number):
        number = int(number)
        if number < 100:
            return under_hundred(number)
        parts = []
        for divisor, label in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand")):
            if number >= divisor:
                parts.append(words(number // divisor) + " " + label)
                number %= divisor
        if number >= 100:
            parts.append(ones[number // 100] + " Hundred")
            number %= 100
        if number:
            parts.append(under_hundred(number))
        return " ".join(parts)

    paise = int((_decimal(value).copy_abs() * 100).quantize(Decimal("1")))
    rupees, cents = divmod(paise, 100)
    result = "Rupees " + words(rupees)
    if cents:
        result += " and " + words(cents) + " Paise"
    return result + " Only"


def _styles():
    regular, bold = _register_fonts()
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("AgniBody", parent=base["Normal"], fontName=regular, fontSize=8,
                               leading=10, textColor=colors.HexColor("#202832"), spaceAfter=0),
        "small": ParagraphStyle("AgniSmall", parent=base["Normal"], fontName=regular, fontSize=7,
                                leading=8.5, textColor=MUTED),
        "tiny": ParagraphStyle("AgniTiny", parent=base["Normal"], fontName=regular, fontSize=6.5,
                               leading=7.5, textColor=MUTED),
        "title": ParagraphStyle("AgniTitle", parent=base["Title"], fontName=bold, fontSize=17,
                                leading=20, textColor=NAVY, alignment=TA_RIGHT),
        "agency": ParagraphStyle("AgniAgency", parent=base["Heading1"], fontName=bold, fontSize=14,
                                 leading=17, textColor=NAVY, spaceAfter=3),
        "section": ParagraphStyle("AgniSection", parent=base["Heading3"], fontName=bold, fontSize=8,
                                  leading=10, textColor=NAVY, spaceAfter=4),
        "right": ParagraphStyle("AgniRight", parent=base["Normal"], fontName=regular, fontSize=7,
                                leading=8.5, alignment=TA_RIGHT),
        "table": ParagraphStyle("AgniTable", parent=base["Normal"], fontName=regular, fontSize=6.5,
                                leading=7.5, textColor=colors.HexColor("#202832")),
        "table_bold": ParagraphStyle("AgniTableBold", parent=base["Normal"], fontName=bold, fontSize=6.5,
                                     leading=7.5, textColor=colors.HexColor("#202832")),
        "table_head": ParagraphStyle("AgniTableHead", parent=base["Normal"], fontName=bold, fontSize=6.2,
                                     leading=7, textColor=colors.white),
        "label": ParagraphStyle("AgniLabel", parent=base["Normal"], fontName=regular, fontSize=6.5,
                                leading=8, textColor=MUTED),
        "value": ParagraphStyle("AgniValue", parent=base["Normal"], fontName=bold, fontSize=8,
                                leading=10, textColor=colors.HexColor("#202832")),
        "cancel": ParagraphStyle("AgniCancel", parent=base["Normal"], fontName=bold, fontSize=11,
                                 leading=13, textColor=RED, alignment=TA_RIGHT),
    }


def _p(value, style):
    return Paragraph(_safe(value), style)


def _table_style(font_regular, font_bold, header=False):
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), font_regular),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LEADING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ])
    return TableStyle(commands)


def build_invoice_pdf(invoice):
    """Return PDF bytes for a saved invoice payload produced by api.sales._sale_payload."""
    regular, bold = _register_fonts()
    styles = _styles()
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=10 * mm, leftMargin=10 * mm,
        topMargin=13 * mm, bottomMargin=17 * mm,
        title="Invoice " + str(invoice.get("number") or invoice.get("id") or ""),
        author=str((invoice.get("business") or {}).get("name") or "Agni Gas"),
    )
    width = A4[0] - 20 * mm
    story = []
    business = invoice.get("business") or {}
    customer = invoice.get("customer") or {}
    cancelled = invoice.get("status") == "cancelled"

    agency_lines = [_p(business.get("name") or "Agni Gas", styles["agency"])]
    if business.get("address"):
        agency_lines.append(_p(business["address"], styles["body"]))
    contacts = [business.get("phone"), business.get("email")]
    contacts = [str(v).strip() for v in contacts if v]
    if contacts:
        agency_lines.append(_p(" | ".join(contacts), styles["small"]))
    if business.get("gstin"):
        agency_lines.append(_p("GSTIN: " + business["gstin"], styles["body"]))

    doc_title = "TAX INVOICE" if business.get("gstin") else "INVOICE"
    if cancelled:
        doc_title += "<br/>CANCELLED"
    header_right = Paragraph(doc_title, styles["cancel"] if cancelled else styles["title"])
    header = Table([[agency_lines, header_right]], colWidths=[width * 0.70, width * 0.30])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, NAVY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([header, Spacer(1, 7)])

    meta_items = [
        ("Invoice number", invoice.get("number")),
        ("Invoice date", invoice.get("date")),
        ("Place of supply", invoice.get("place_state_code") or "—"),
        ("Reverse charge", "Yes" if invoice.get("reverse_charge") else "No"),
    ]
    meta = Table([
        [_p(label, styles["label"]) for label, _ in meta_items],
        [_p(value or "—", styles["value"]) for _, value in meta_items],
    ], colWidths=[width / 4] * 4)
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.45, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([meta, Spacer(1, 8), _p("BILL TO", styles["section"])])

    bill_lines = [_p(customer.get("name") or "Walk-in customer", styles["value"])]
    bill_address = customer.get("billing_address") or customer.get("address")
    if bill_address:
        bill_lines.append(_p(bill_address, styles["body"]))
    if customer.get("phone"):
        bill_lines.append(_p("Phone: " + customer["phone"], styles["small"]))
    if customer.get("gstin"):
        bill_lines.append(_p("GSTIN: " + customer["gstin"], styles["body"]))
    else:
        bill_lines.append(_p("Unregistered customer", styles["small"]))
    bill = Table([[bill_lines]], colWidths=[width])
    bill.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.45, GRID),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([bill, Spacer(1, 8)])

    headers = ["#", "Description", "HSN/SAC", "Qty", "Unit", "Rate", "Taxable", "GST %", "Tax", "Amount"]
    rows = [[_p(h, styles["table_head"]) for h in headers]]
    numeric_style = ParagraphStyle("AgniNum", parent=styles["table"], alignment=TA_RIGHT)
    for index, line in enumerate(invoice.get("lines") or [], 1):
        name = _safe(line.get("name") or "")
        if line.get("detail"):
            name += "<br/><font color='#5D6976' size='6'>" + _safe(line["detail"]) + "</font>"
        kind = line.get("kind")
        informational = kind in ("empty_in", "deposit_forfeit")
        amount = _decimal(line.get("amount"))
        tax = _decimal(line.get("cgst")) + _decimal(line.get("sgst")) + _decimal(line.get("igst"))
        rate = "—" if informational else _money(line.get("rate"))
        taxable = _money(line.get("taxable")) if kind == "product" else "—"
        gst_rate = "—" if line.get("gst_rate") is None else str(line.get("gst_rate")) + "%"
        tax_text = _money(tax) if tax else "—"
        amount_text = "—" if informational else ("- " if amount < 0 else "") + _money(abs(amount))
        cells = [str(index), name, _safe(line.get("hsn") or "—"), _safe(line.get("qty") or "0"),
                 _safe(line.get("unit") or "—"), rate, taxable, gst_rate, tax_text, amount_text]
        rows.append([_p(cells[0], numeric_style), Paragraph(cells[1], styles["table"]),
                     _p(cells[2], styles["table"]), _p(cells[3], numeric_style),
                     _p(cells[4], styles["table"]), _p(cells[5], numeric_style),
                     _p(cells[6], numeric_style), _p(cells[7], numeric_style),
                     _p(cells[8], numeric_style), _p(cells[9], styles["table_bold"] if not informational else styles["table"])])

    col_widths = [18, 118, 42, 34, 30, 54, 58, 35, 58, width - 447]
    line_table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    line_table.setStyle(_table_style(regular, bold, header=True))
    for col in (0, 3, 5, 6, 7, 8, 9):
        line_table.setStyle(TableStyle([("ALIGN", (col, 1), (col, -1), "RIGHT")]))
    story.extend([line_table, Spacer(1, 8)])

    tax_rows = [[_p("Tax component", styles["table_head"]), _p("Amount", styles["table_head"])]]
    tax_components = [("CGST", invoice.get("cgst")), ("SGST", invoice.get("sgst")), ("IGST", invoice.get("igst"))]
    tax_components = [(label, value) for label, value in tax_components if _decimal(value) != 0]
    if not tax_components:
        tax_components = [("GST", "0.00")]
    for label, value in tax_components:
        tax_rows.append([_p(label, styles["table"]), _p(_money(value), numeric_style)])
    tax_table = Table(tax_rows, colWidths=[95, 82], hAlign="LEFT")
    tax_table.setStyle(_table_style(regular, bold, header=True))

    total_rows = []
    for label, value, is_negative in [
        ("Product subtotal", invoice.get("subtotal"), False),
        ("Discount", invoice.get("discount"), True),
        ("Taxable value", invoice.get("taxable"), False),
        ("Total GST", invoice.get("gst"), False),
        ("Refundable security received", invoice.get("deposit_received"), False),
        ("Security deposit refunded", invoice.get("deposit_refunded"), True),
    ]:
        if label not in ("Product subtotal", "Taxable value", "Total GST") and _decimal(value) == 0:
            continue
        total_rows.append([_p(label, styles["table"]), _p(("- " if is_negative else "") + _money(value), numeric_style)])
    total_value = _decimal(invoice.get("total"))
    total_rows.append([_p("Amount to pay back" if total_value < 0 else "Invoice total", styles["table_bold"]),
                       _p(_money(abs(total_value)), numeric_style)])
    total_rows.append([_p("Amount received / paid back", styles["table"]),
                       _p(_money(abs(_decimal(invoice.get("paid")))), numeric_style)])
    if _decimal(invoice.get("due")) > 0 and not cancelled:
        total_rows.append([_p("Balance due", styles["table_bold"]), _p(_money(invoice.get("due")), numeric_style)])
    sum_table = Table(total_rows, colWidths=[175, 88], hAlign="LEFT")
    sum_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, -3), (-1, -3), 0.7, NAVY),
        ("LINEABOVE", (0, -2), (-1, -2), 0.7, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    bottom = Table([[tax_table, sum_table]], colWidths=[width * 0.44, width * 0.56], hAlign="LEFT")
    bottom.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(bottom)

    word_label = "Refund payable in words: " if total_value < 0 else "Amount in words: "
    story.extend([Spacer(1, 7), _p(word_label + _amount_words(total_value), styles["small"])])
    if invoice.get("note"):
        story.extend([Spacer(1, 5), _p("Note: " + invoice["note"], styles["small"])])

    bank = [business.get("bank_name"),
            ("A/c " + business["bank_account"]) if business.get("bank_account") else None,
            ("IFSC " + business["bank_ifsc"]) if business.get("bank_ifsc") else None]
    bank = [str(value) for value in bank if value]
    footer_left = [_p("PAYMENT / BANK DETAILS", styles["section"])]
    if bank:
        footer_left.append(_p(" | ".join(bank), styles["body"]))
    if business.get("terms"):
        footer_left.append(_p(business["terms"], styles["small"]))
    footer_right = [_p("For " + (business.get("name") or "Agni Gas"), styles["table_bold"]),
                    Spacer(1, 15), _p("Authorized signatory", styles["small"])]
    footer = Table([[footer_left, footer_right]], colWidths=[width * 0.68, width * 0.32])
    footer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEABOVE", (0, 0), (-1, -1), 0.5, GRID),
        ("LINEBELOW", (1, 0), (1, 0), 0.6, MUTED),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([Spacer(1, 10), footer, Spacer(1, 6),
                  Paragraph("Thank you for your business.", ParagraphStyle(
                      "AgniThanks", parent=styles["small"], alignment=TA_CENTER))])

    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.4)
        canvas.line(10 * mm, 12 * mm, A4[0] - 10 * mm, 12 * mm)
        canvas.setFont(regular, 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(10 * mm, 7 * mm, "Invoice " + str(invoice.get("number") or ""))
        canvas.drawRightString(A4[0] - 10 * mm, 7 * mm, "Page " + str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()
```

---

# B. SMALL EDITS

## B1. Add ReportLab to `requirements.txt`

**Find:**

```text
flask>=3.0
pywebview>=5.0
```

**Replace with:**

```text
flask>=3.0
pywebview>=5.0
reportlab>=4.0,<5
```

After applying all edits, install/update dependencies from inside the project's virtual environment:

```bash
python -m pip install -r requirements.txt
```

## B2. Add the customer-held cylinder endpoint in `api/customers.py`

**Find:**

```python
@api_bp.get("/customers/<int:cid>")
def customer_get(cid):
    return jsonify(customer_dict(cid))
```

**Replace with:**

```python
@api_bp.get("/customers/<int:cid>")
def customer_get(cid):
    return jsonify(customer_dict(cid))


@api_bp.get("/customers/<int:cid>/held-cylinders")
def customer_held_cylinders(cid):
    """Return the customer's currently held cylinder count, grouped by size."""
    customer_row(cid)
    rows = get_db().execute(
        "SELECT cylinder_type_id, COALESCE(SUM(delta),0) AS qty "
        "FROM cylinder_ledger WHERE customer_id=? GROUP BY cylinder_type_id",
        (cid,),
    ).fetchall()
    return jsonify({str(row["cylinder_type_id"]): max(0, row["qty"])
                    for row in rows if row["qty"] > 0})
```

The response is a JSON object keyed by cylinder type ID, for example `{"3": 2}`.

## B3. Update sales validation, invoice GST snapshots, and PDF endpoint in `api/sales.py`

### B3.1 Imports

**Find:**

```python
from flask import jsonify, request
```

**Replace with:**

```python
from io import BytesIO

from flask import jsonify, request, send_file
```

**Find:**

```python
from .util import ApiError, RECEIVED_IN, body, day_field, int_field, money_field, quantity_milli_field, text
```

**Replace with:**

```python
from .util import (ApiError, RECEIVED_IN, body, day_field, gst_rate_bp_field,
                   int_field, money_field, quantity_milli_field, text)
```

### B3.2 Add a validated per-invoice GST rate helper

**Find the complete `_money()` function:**

```python
def _money(raw, label, allow_zero=True):
    try:
        value = to_paise(raw)
    except (ValueError, TypeError, ArithmeticError):
        raise ApiError(f"{label} is not a valid amount.", field=label)
    if value < 0 or (value == 0 and not allow_zero):
        raise ApiError(f"{label} must be {'zero or more' if allow_zero else 'more than zero'}.", field=label)
    return value
```

**Replace with:**

```python
def _money(raw, label, allow_zero=True):
    try:
        value = to_paise(raw)
    except (ValueError, TypeError, ArithmeticError):
        raise ApiError(f"{label} is not a valid amount.", field=label)
    if value < 0 or (value == 0 and not allow_zero):
        raise ApiError(f"{label} must be {'zero or more' if allow_zero else 'more than zero'}.", field=label)
    return value


def _effective_gst_rate(raw, stock_rate_bp, product_name):
    """Use the invoice's submitted percentage when present; otherwise use Stock & Price."""
    if "gst_rate" not in raw:
        return stock_rate_bp
    value = gst_rate_bp_field(raw)
    if value is None:
        raise ApiError(f"Set a GST rate for {product_name} before invoicing.", 422, "gst_rate")
    return value
```

### B3.3 Validate refill + return quantities against the customer's held cylinders

**Find:**

```python
            if customer and qty["empty_in"] + qty["damaged_in"] > _held_cylinders(db, customer["id"], tid):
                raise ApiError(f"{c['name']}: the customer does not hold that many cylinders.", 409)
```

**Replace with:**

```python
            if customer:
                held_qty = _held_cylinders(db, customer["id"], tid)
                held_cylinders_used = qty["refill"] + qty["empty_in"] + qty["damaged_in"]
                if held_cylinders_used > held_qty:
                    raise ApiError(
                        f"{c['name']}: the customer holds only {held_qty} cylinder(s). "
                        "A refill or return needs a cylinder already held by this customer.",
                        409,
                    )
```

This check intentionally does not add `new_full` or `new_empty` to the existing balance. Those are newly issued cylinders, not cylinders the customer already held when the invoice began.

### B3.4 Use the invoice GST percentage for cylinder product lines

**Find:**

```python
            hsn = c["hsn"]
            rate_bp = c["gst_rate_bp"]
```

**Replace with:**

```python
            hsn = c["hsn"]
            rate_bp = _effective_gst_rate(raw, c["gst_rate_bp"], c["name"])
```

The existing HSN/GST validation immediately below this block should remain unchanged. It now validates the submitted invoice percentage when one is present, and falls back to the stock-configured percentage when an older API client omits it.

### B3.5 Use the invoice GST percentage for catalogue product lines

In the `for raw in raw_items:` block, **find this block:**

```python
            if not item["hsn"]:
                raise ApiError(f"Set an HSN/SAC code for {item['name']} in Stock & Price before invoicing.", 422, "hsn")
            if item["gst_rate_bp"] is None:
                raise ApiError(f"Set the GST rate for {item['name']} in Stock & Price before invoicing.", 422, "gst_rate")
            if item["gst_rate_bp"] > 0 and not business.get("gstin"):
                raise ApiError(
                    "The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.",
                    422, "gstin",
                )
```

**Replace with:**

```python
            if not item["hsn"]:
                raise ApiError(f"Set an HSN/SAC code for {item['name']} in Stock & Price before invoicing.", 422, "hsn")
            item_rate_bp = _effective_gst_rate(raw, item["gst_rate_bp"], item["name"])
            if item_rate_bp is None:
                raise ApiError(f"Set the GST rate for {item['name']} in Stock & Price before invoicing.", 422, "gst_rate")
            if item_rate_bp > 0 and not business.get("gstin"):
                raise ApiError(
                    "The agency GSTIN is missing. An unregistered agency must not charge GST; confirm the agency's registration status and product tax setup with the CA.",
                    422, "gstin",
                )
```

Then, a few lines below in the catalogue `lines.append(...)`, **find:**

```python
                          "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": item["gst_rate_bp"],
```

**Replace with:**

```python
                          "rate_paise": rate, "gross_paise": gross, "gst_rate_bp": item_rate_bp,
```

### B3.6 Add the invoice PDF download route

**Find:**

```python
@api_bp.get("/sales/<int:sid>")
def sale_get(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)
    return jsonify(_sale_payload(db, row))
```

**Replace with:**

```python
@api_bp.get("/sales/<int:sid>")
def sale_get(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)
    return jsonify(_sale_payload(db, row))


@api_bp.get("/sales/<int:sid>/pdf")
def sale_pdf(sid):
    db = get_db()
    row = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise ApiError("Invoice not found.", 404)

    try:
        from invoice_pdf import build_invoice_pdf
    except ImportError as exc:
        raise ApiError("PDF support is not installed. Run pip install -r requirements.txt.", 503) from exc

    pdf_data = build_invoice_pdf(_sale_payload(db, row))
    safe_number = "".join(ch for ch in row["number"] if ch.isalnum() or ch in "-_") or str(sid)
    return send_file(
        BytesIO(pdf_data), mimetype="application/pdf", as_attachment=True,
        download_name=f"Invoice-{safe_number}.pdf", max_age=0,
    )
```

## B4. Update the Sales page in `static/js/sales_new.js`

### B4.1 Track each customer's held cylinders and each product's invoice GST rate

**Find:**

```javascript
  const state = { customer: null, cylinders: [], goods: [], suppliers: [], business: null, special: {}, saving: false, loaded: false };
```

**Replace with:**

```javascript
  const state = { customer: null, cylinders: [], goods: [], suppliers: [], business: null,
    special: {}, heldByType: {}, saving: false, loaded: false };
```

### B4.2 Use the selected GST input in tax calculations

**Find this section in `productLines()`:**

```javascript
    state.cylinders.forEach((c) => {
      const s = cyl[c.id], rate = cents(s.rate), rateBp = bp(c.gst_rate);
```

**Replace with:**

```javascript
    state.cylinders.forEach((c) => {
      const s = cyl[c.id], rate = cents(s.rate), rateBp = bp(s.gstRate);
```

Then **find:**

```javascript
      if (q > 0) out.push({ gross: Math.round(q * cents(s.rate)), rateBp: bp(g.gst_rate), name: g.name, hsn: g.hsn });
```

**Replace with:**

```javascript
      if (q > 0) out.push({ gross: Math.round(q * cents(s.rate)), rateBp: bp(s.gstRate), name: g.name, hsn: g.hsn });
```

### B4.3a Reject invalid invoice GST percentages before enabling Save

In `taxConfigError()`, **find:**

```javascript
      if (l.rateBp == null) return "Set a GST rate for " + l.name + " in Stock & Price before creating this invoice.";
      if (l.rateBp > 0 && state.business && !state.business.gstin) {
```

**Replace with:**

```javascript
      if (l.rateBp == null) return "Set a GST rate for " + l.name + " before creating this invoice.";
      if (!Number.isFinite(l.rateBp) || l.rateBp < 0 || l.rateBp > 10000) {
        return "GST rate for " + l.name + " must be between 0 and 100 percent.";
      }
      if (l.rateBp > 0 && state.business && !state.business.gstin) {
```

### B4.3 Replace the small fixed GST label with an editable invoice GST percentage

**Find the complete `taxLabel()` function:**

```javascript
  function taxLabel(x) {
    return '<small class="sn-product-tax">' + (x.hsn ? 'HSN ' + esc(x.hsn) : 'HSN not set') + ' · ' +
      (x.gst_rate == null ? 'GST not set' : 'GST ' + esc(x.gst_rate) + '%') + '</small>';
  }
```

**Replace with:**

```javascript
  function taxLabel(x, rate, kind, id) {
    return '<div class="sn-product-tax"><span>' + (x.hsn ? 'HSN ' + esc(x.hsn) : 'HSN not set') + '</span>' +
      '<label>GST % <input type="number" min="0" max="100" step="0.01" value="' + esc(rate == null ? '' : rate) + '" ' +
      'data-gst-kind="' + kind + '" data-gst-id="' + id + '" aria-label="GST percentage for ' + esc(x.name) + '"></label></div>';
  }
```

### B4.4 Replace `stepper()` so disabled and customer-held limits are reflected in the controls

**Find the complete function:**

```javascript
  function stepper(field, id, value, minusCls, plusCls) {
    return '<div class="pn-stepper"><button type="button" class="pn-step ' + minusCls + '" data-step="-1" data-f="' + field + '" data-id="' + id + '" aria-label="Less">−</button>' +
      '<input type="number" min="0" step="1" inputmode="numeric" value="' + value + '" data-f="' + field + '" data-id="' + id + '">' +
      '<button type="button" class="pn-step ' + plusCls + '" data-step="1" data-f="' + field + '" data-id="' + id + '" aria-label="More">+</button></div>';
  }
```

**Replace with:**

```javascript
  function stepper(field, id, value, minusCls, plusCls, disabled = false, max = null) {
    const maxAttr = max == null ? '' : ' max="' + max + '"';
    const minusDisabled = Number(value) <= 0 ? ' disabled' : '';
    const plusDisabled = disabled || (max != null && Number(value) >= max) ? ' disabled' : '';
    const inputDisabled = disabled ? ' disabled' : '';
    return '<div class="pn-stepper"><button type="button" class="pn-step ' + minusCls + '" data-step="-1" data-f="' + field + '" data-id="' + id + '" aria-label="Less"' + minusDisabled + '>−</button>' +
      '<input type="number" min="0"' + maxAttr + ' step="1" inputmode="numeric" value="' + value + '" data-f="' + field + '" data-id="' + id + '"' + inputDisabled + '>' +
      '<button type="button" class="pn-step ' + plusCls + '" data-step="1" data-f="' + field + '" data-id="' + id + '" aria-label="More"' + plusDisabled + '>+</button></div>';
  }
```

### B4.5 Update `cylinderCard()`

**Find the first line inside `cylinderCard(c)`:**

```javascript
    const s = cyl[c.id], used = s.refill + s.new_full, over = used > c.full;
```

**Replace with:**

```javascript
    const s = cyl[c.id], used = s.refill + s.new_full, over = used > c.full;
    const held = Number(state.heldByType[c.id] || 0);
    const customerLocked = !!state.customer && held <= 0;
    const refillMax = state.customer ? Math.max(0, held - s.empty_in - s.damaged_in) : null;
    const emptyReturnMax = state.customer ? Math.max(0, held - s.refill - s.damaged_in) : 0;
    const damagedReturnMax = state.customer ? Math.max(0, held - s.refill - s.empty_in) : 0;
```

Inside the returned card HTML, **find this fragment:**

```javascript
      '<div class="sn-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(c.name) + '</b>' + taxLabel(c) + '<small>Full: ' + c.full + ' · Empty: ' + c.empty + '</small></div>' +
```

**Replace with:**

```javascript
      '<div class="sn-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(c.name) + '</b>' + taxLabel(c, s.gstRate, 'cylinder', c.id) + '<small>Full: ' + c.full + ' · Empty: ' + c.empty + '</small>' +
      (state.customer ? '<small class="sn-held-count">Customer-held: ' + held + ' · treated as empty for refill/return</small>' : '') + '</div>' +
```

**Find the existing Refill row:**

```javascript
      '<div class="pn-qty-line"><div><b>Refill</b><small>Full cylinder supplied, customer returns an empty</small></div>' + stepper("refill", c.id, s.refill, "pn-step-minus", "pn-step-plus") + '</div>' +
```

**Replace with:**

```javascript
      '<div class="pn-qty-line"><div><b>Refill</b><small>Full cylinder supplied against one customer-held cylinder</small></div>' +
      stepper("refill", c.id, s.refill, "pn-step-minus", "pn-step-plus", customerLocked, refillMax) + '</div>' +
```

**Find the existing Good empty row:**

```javascript
      '<div class="pn-qty-line"><div><b>Good empty in</b><small>Customer returns a usable empty cylinder</small></div>' + stepper("empty_in", c.id, s.empty_in, "pn-step-minus", "sn-step-orange") + '</div>' +
```

**Replace with:**

```javascript
      '<div class="pn-qty-line"><div><b>Good empty in</b><small>Customer returns a usable held cylinder</small></div>' +
      stepper("empty_in", c.id, s.empty_in, "pn-step-minus", "sn-step-orange", !state.customer || customerLocked, emptyReturnMax) + '</div>' +
```

**Find the existing Damaged cylinder row:**

```javascript
      (state.customer ? '<div class="pn-qty-line"><div><b>Damaged cylinder in</b><small>Customer deposit is forfeited; cylinder moves to damaged stock</small></div>' + stepper("damaged_in", c.id, s.damaged_in, "pn-step-minus", "sn-step-orange") + '</div>' : '') +
```

**Replace with:**

```javascript
      (state.customer ? '<div class="pn-qty-line"><div><b>Damaged cylinder in</b><small>Customer deposit is forfeited; cylinder moves to damaged stock</small></div>' +
        stepper("damaged_in", c.id, s.damaged_in, "pn-step-minus", "sn-step-orange", customerLocked, damagedReturnMax) + '</div>' : '') +
```


### B4.6 Update catalogue item GST display

**Find the first `return` in `goodCard(g)`:**

```javascript
    return '<article class="sn-good" data-gid="' + g.id + '"><div class="pn-item-title"><b>' + esc(g.name) + '</b>' + taxLabel(g) + '<small>In stock: ' + esc(g.qty) + ' ' + esc(g.unit) + '</small></div>' +
```

**Replace with:**

```javascript
    return '<article class="sn-good" data-gid="' + g.id + '"><div class="pn-item-title"><b>' + esc(g.name) + '</b>' +
      taxLabel(g, s.gstRate, 'item', g.id) + '<small>In stock: ' + esc(g.qty) + ' ' + esc(g.unit) + '</small></div>' +
```

### B4.7 Load the selected customer's held-cylinder quantities

**Find the beginning of `setCustomer(c)`:**

```javascript
  async function setCustomer(c) {
    state.customer = c || null; state.special = {};
```

**Replace with:**

```javascript
  async function setCustomer(c) {
    state.customer = c || null; state.special = {}; state.heldByType = {};
```

Then, inside the `if (c) { ... }` block in that function, **find:**

```javascript
      try { (await Api.get('/api/customers/' + c.id + '/prices')).forEach((p) => { if (p.special_price != null) state.special[p.cylinder_type_id] = p.special_price; }); }
      catch (_) { /* standard retail/wholesale prices remain usable */ }
```

**Replace with:**

```javascript
      try {
        const [prices, held] = await Promise.all([
          Api.get('/api/customers/' + c.id + '/prices'),
          Api.get('/api/customers/' + c.id + '/held-cylinders'),
        ]);
        prices.forEach((p) => { if (p.special_price != null) state.special[p.cylinder_type_id] = p.special_price; });
        state.heldByType = held || {};
      } catch (_) {
        state.heldByType = {};
      }
```

### B4.8 Clamp return/refill quantity input to held cylinders

In the `document.addEventListener('click', ...)` handler, **find:**

```javascript
    if (step) { const s = cyl[step.dataset.id], f = step.dataset.f; s[f] = Math.max(0, s[f] + Number(step.dataset.step)); renderCylinders(); update(); return; }
```

**Replace with:**

```javascript
    if (step) {
      const id = step.dataset.id, s = cyl[id], f = step.dataset.f;
      const heldAction = ['refill', 'empty_in', 'damaged_in'].includes(f);
      if (state.customer && heldAction) {
        const held = Number(state.heldByType[id] || 0);
        const used = s.refill + s.empty_in + s.damaged_in;
        if (Number(step.dataset.step) > 0 && used >= held) return;
      }
      s[f] = Math.max(0, s[f] + Number(step.dataset.step));
      renderCylinders(); update(); return;
    }
```

In the `sn-cylinders` change handler, **find:**

```javascript
  $("sn-cylinders").addEventListener('change', (e) => {
    const t = e.target; if (!t.dataset.f) return;
    const s = cyl[t.dataset.id]; s[t.dataset.f] = (t.dataset.f === 'security' || t.dataset.f === 'dep_each') ? t.value : num(t.value);
    renderCylinders(); update();
  });
```

**Replace with:**

```javascript
  $("sn-cylinders").addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.gstKind === 'cylinder') {
      cyl[t.dataset.gstId].gstRate = t.value;
      update();
      return;
    }
    if (!t.dataset.f) return;
    const s = cyl[t.dataset.id], field = t.dataset.f;
    let value = (field === 'security' || field === 'dep_each') ? t.value : num(t.value);
    if (state.customer && ['refill', 'empty_in', 'damaged_in'].includes(field)) {
      const held = Number(state.heldByType[t.dataset.id] || 0);
      const alreadyUsed = s.refill + s.empty_in + s.damaged_in - s[field];
      value = Math.min(value, Math.max(0, held - alreadyUsed));
    }
    s[field] = value;
    renderCylinders(); update();
  });
```

### B4.9 Update catalogue GST percentage on the card

**Find:**

```javascript
  $("sn-goods").addEventListener('input', (e) => { const id = e.target.dataset.gqty; if (!id) return; good[id].qty = e.target.value; update(); });
```

**Replace with:**

```javascript
  $("sn-goods").addEventListener('input', (e) => {
    if (e.target.dataset.gstKind === 'item') {
      good[e.target.dataset.gstId].gstRate = e.target.value;
      update();
      return;
    }
    const id = e.target.dataset.gqty;
    if (!id) return;
    good[id].qty = e.target.value;
    update();
  });
```

### B4.10 Include the invoice GST percentage in the sale request

In the cylinder `lines` map in the submit handler, **find:**

```javascript
      deposit_each: String(cyl[c.id].dep_each), rate: String(cyl[c.id].rate), security: String(cyl[c.id].security) }))
```

**Replace with:**

```javascript
      deposit_each: String(cyl[c.id].dep_each), rate: String(cyl[c.id].rate), security: String(cyl[c.id].security),
      gst_rate: String(cyl[c.id].gstRate) }))
```

Then **find:**

```javascript
    const items = state.goods.filter((g) => Number(good[g.id].qty) > 0)
      .map((g) => ({ item_id: g.id, qty: String(good[g.id].qty), rate: String(good[g.id].rate) }));
```

**Replace with:**

```javascript
    const items = state.goods.filter((g) => Number(good[g.id].qty) > 0)
      .map((g) => ({ item_id: g.id, qty: String(good[g.id].qty), rate: String(good[g.id].rate),
        gst_rate: String(good[g.id].gstRate) }));
```

### B4.11 Initialise GST percentages from Stock & Price

In `start()`, **find:**

```javascript
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, damaged_in: 0,
        rate: c.sale_price, security: c.security, open: false, dep_back: false, dep_each: c.security }; });
      state.goods.forEach((g) => { good[g.id] = { qty: '', rate: g.sale_price }; });
```

**Replace with:**

```javascript
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, damaged_in: 0,
        rate: c.sale_price, security: c.security, gstRate: c.gst_rate == null ? '' : String(c.gst_rate),
        open: false, dep_back: false, dep_each: c.security }; });
      state.goods.forEach((g) => { good[g.id] = { qty: '', rate: g.sale_price,
        gstRate: g.gst_rate == null ? '' : String(g.gst_rate) }; });
```

### B4.12 Add customer-held validation to the Save button guard

In `update()`, **find:**

```javascript
    const over = state.cylinders.some((c) => cyl[c.id].refill + cyl[c.id].new_full > c.full || cyl[c.id].new_empty > c.empty);
```

**Replace with:**

```javascript
    const over = state.cylinders.some((c) => {
      const s = cyl[c.id], held = Number(state.heldByType[c.id] || 0);
      const customerUse = s.refill + s.empty_in + s.damaged_in;
      return s.refill + s.new_full > c.full || s.new_empty > c.empty ||
        (!!state.customer && customerUse > held);
    });
```

### B4.13 Use the loaded balance immediately when a customer is selected

At the end of `setCustomer(c)`, the existing code calls `resetRates();`. Keep that line; it already re-renders the cylinder cards after the API call has loaded `heldByType`.

## B5. Add a direct PDF download action on the saved invoice page

### B5.1 `templates/sale_detail.html`

**Find:**

```html
    <div class="rc-actions">
      <button class="btn btn-dark" id="rc-print" type="button">Print / Save PDF</button>
      <button class="btn btn-whatsapp" id="rc-wa" type="button">WhatsApp</button>
      <a class="btn btn-orange" href="/sales?tab=new"><i data-icon="plus"></i>New sale</a>
    </div>
```

**Replace with:**

```html
    <div class="rc-actions">
      <a class="btn btn-dark" id="rc-download-pdf" href="#">Download PDF</a>
      <button class="btn btn-white" id="rc-print" type="button">Print</button>
      <button class="btn btn-whatsapp" id="rc-wa" type="button">WhatsApp</button>
      <a class="btn btn-orange" href="/sales?tab=new"><i data-icon="plus"></i>New sale</a>
    </div>
```

### B5.2 `static/js/sale_detail.js`

Inside `render()`, **find:**

```javascript
    $('rc-title').textContent = 'Invoice ' + sale.number;
```

**Replace with:**

```javascript
    $('rc-title').textContent = 'Invoice ' + sale.number;
    $('rc-download-pdf').href = '/api/sales/' + sid + '/pdf';
```

Keep the existing print handler unchanged:

```javascript
  $('rc-print').addEventListener('click', () => window.print());
```

## B6. Add styling for the per-line GST input and held-cylinder note in `static/css/sales.css`

Append this at the end of the file:

```css
/* v0.6.1: invoice-specific GST rate and customer-held cylinder availability */
.sn-product-tax {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 3px;
  color: var(--muted);
  font-size: 9px;
  font-weight: 500;
}
.sn-product-tax label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
}
.sn-product-tax input {
  width: 58px;
  min-height: 24px;
  padding: 2px 5px;
  border: 1px solid var(--line, #d7d7df);
  border-radius: 6px;
  background: var(--surface, #fff);
  color: var(--text, #20202a);
  font: inherit;
}
.sn-held-count { color: var(--muted); }
```

---

# C. TESTS AND VERIFICATION

## C1. Update tests affected by the stricter refill rule in `tests/test_sales_invoice.py`

### `test_product_hsn_is_snapshotted_and_tax_is_split`

**Find:**

```python
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
```

**Replace with:**

```python
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
```

### `test_paid_invoice_cannot_be_cancelled_without_refund_workflow`

In that test, **find:**

```python
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
```

**Replace with:**

```python
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
```

### `test_unpaid_credit_invoice_can_be_cancelled_and_restores_stock`

Immediately after `customer = self.make_customer()`, **insert:**

```python
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
```

Then **find:**

```python
        self.assertEqual((before["full_qty"], before["empty_qty"]), (4, 3))
```

**Replace with:**

```python
        self.assertEqual((before["full_qty"], before["empty_qty"]), (3, 3))
```

Then **find:**

```python
        self.assertEqual((after["full_qty"], after["empty_qty"]), (5, 2))
```

**Replace with:**

```python
        self.assertEqual((after["full_qty"], after["empty_qty"]), (4, 2))
```

The first new-full invoice remains active; cancelling the second, refill-only invoice should restore only that refill's stock movement.

### `test_failed_stock_validation_does_not_create_invoice`

After `customer = self.make_customer()`, **insert:**

```python
        self.conn.execute(
            "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,ref_id,entry_date,note) "
            "VALUES(?,?,99,'test',0,?,?)",
            (customer["id"], cylinder["id"], date.today().isoformat(), "Test held-cylinder balance"),
        )
        self.conn.commit()
```

This test fixture gives the customer enough held cylinders to reach the warehouse stock check; it is intentionally synthetic test data, not a real transaction.

## C2. Add regression tests to `tests/test_sales_invoice.py`

Insert the following methods inside `class InvoiceTests`, before the `if __name__ == "__main__":` block:

```python
    def test_refill_requires_a_customer_held_cylinder(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertIn("customer holds only", response.get_json()["error"].lower())
        after = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        self.assertEqual(after, before)

    def test_refill_and_return_cannot_use_the_same_held_cylinder_twice(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]

        response = self.sell(cylinder, customer, refill=1, empty_in=1)
        self.assertEqual(response.status_code, 409, response.get_json())
        after = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        self.assertEqual(after, before)

    def test_invoice_gst_rate_can_override_stock_rate_without_changing_stock(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())

        response = self.sell(cylinder, customer, refill=1, gst_rate="5")
        self.assertEqual(response.status_code, 201, response.get_json())
        detail = self.client.get(f"/api/sales/{response.get_json()['id']}").get_json()
        self.assertEqual(detail["lines"][0]["gst_rate"], 5)
        self.assertEqual(detail["gst"], "5.00")
        self.assertEqual(detail["total"], "105.00")

        stock = self.client.get("/api/stock").get_json()
        saved = next(x for x in stock["cylinders"] if x["id"] == cylinder["id"])
        self.assertEqual(float(saved["gst_rate"]), 18.0)

    def test_invoice_pdf_endpoint_returns_a_downloadable_pdf(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        sale_id = issued.get_json()["id"]

        response = self.client.get(f"/api/sales/{sale_id}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))

    def test_customer_held_cylinders_endpoint_groups_by_cylinder_type(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=2)
        self.assertEqual(issued.status_code, 201, issued.get_json())

        response = self.client.get(f"/api/customers/{customer['id']}/held-cylinders")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {str(cylinder["id"]): 2})
```

## C3. Apply and verify

From the `agni-gas/` directory, with the project's virtual environment active:

```bash
python -m pip install -r requirements.txt
python -m compileall -q api invoice_pdf.py tests
node --check static/js/sales_new.js
node --check static/js/sale_detail.js
python -m unittest discover -s tests -v
```

Then manually verify these cases in the UI:

1. Select a customer with no cylinders held. The Refill, Good empty in, and Damaged cylinder in controls for each size should be disabled. Create a new-full-cylinder sale for that customer; the same size should then show a customer-held count and enable refill/return.
2. Select a customer with one held cylinder. A refill of one should work. A refill of one plus a second return of that same size in the same invoice should be rejected/clamped; it must not double-use the held cylinder.
3. Change a product's GST percentage on the sales page. The GST amount and CGST/SGST or IGST split should recalculate. Save the invoice, download its PDF, and confirm the PDF shows the selected rate. Return to Stock & Price and confirm the saved stock GST rate is unchanged.
4. Download a PDF for an invoice, then edit the customer or stock details. Download the old invoice again and confirm its original snapshot still appears.
5. Download a cancelled unpaid invoice PDF and confirm it is clearly marked CANCELLED.

The PDF regression test needs ReportLab, which is added in B1. If `python -m unittest` fails, fix that failure before pushing v0.6.1. This patch was not applied to your local checkout and no integration test suite was run here.
