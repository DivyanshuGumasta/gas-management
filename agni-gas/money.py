"""Money handling.

Outside world (API, JSON, UI) : decimal rupees as text, e.g. "1450.50"
Inside the database           : whole paise as INTEGER (145050)

So you get the readable rupees.paise format everywhere you look, while all
arithmetic is exact (no floating point rounding errors in bills or ledgers).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_paise(value) -> int:
    """'1450.50' / 1450.5 / '1,450.50' -> 145050. Empty -> 0."""
    if value is None or str(value).strip() == "":
        return 0
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {value!r}")
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_rupees(paise) -> str:
    """145050 -> '1450.50'. Negative amounts keep their sign."""
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 100}.{p % 100:02d}"


def gst_paise(taxable_paise: int, percent) -> int:
    """GST on an amount, rounded to the nearest paisa."""
    d = Decimal(str(percent or 0))
    return int((Decimal(taxable_paise) * d / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
