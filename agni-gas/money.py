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


def format_inr(paise) -> str:
    """145050 -> 'Rs 1,450.50'; 11525000 -> 'Rs 1,15,250' (Indian grouping)."""
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    rupees, ps = divmod(abs(p), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}Rs {s}" + (f".{ps:02d}" if ps else "")


def amount_in_words(paise) -> str:
    """Format integer paise as Indian currency words (Rupees/Lakh/Crore)."""
    p = int(paise or 0)
    sign = "Minus " if p < 0 else ""
    p = abs(p)
    ones = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    def under100(n):
        return ones[n] if n < 20 else tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
    def words(n):
        n = int(n)
        if n < 100: return under100(n)
        parts = []
        for divisor, label in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand")):
            if n >= divisor:
                parts.append(words(n // divisor) + " " + label)
                n %= divisor
        if n >= 100:
            parts.append(ones[n // 100] + " Hundred")
            n %= 100
        if n: parts.append(under100(n))
        return " ".join(parts)
    rupees, cents = divmod(p, 100)
    result = sign + "Rupees " + words(rupees)
    if cents: result += " and " + words(cents) + " Paise"
    return result + " Only"
