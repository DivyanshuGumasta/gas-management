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