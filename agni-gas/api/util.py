"""Validation helpers shared by the API modules. All raise ApiError (-> JSON error)."""
import re
from datetime import date
from decimal import InvalidOperation

from flask import request

from money import to_paise

RECEIVED_IN = {"cash": "Cash in hand", "bank": "Bank / UPI"}


class ApiError(Exception):
    def __init__(self, message, status=400, field=None):
        super().__init__(message)
        self.message, self.status, self.field = message, status, field


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send the data as JSON.")
    return data


def text(data, key, label, required=False, max_len=200):
    v = data.get(key)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise ApiError(f"{label} is required.", field=key)
    if len(v) > max_len:
        raise ApiError(f"{label} is too long (max {max_len} characters).", field=key)
    return v or None


def phone_field(data, key="phone"):
    v = text(data, key, "Phone", max_len=30)
    if v:
        digits = re.sub(r"\D", "", v)
        if re.search(r"[^0-9+\-\s()]", v) or not 7 <= len(digits) <= 15:
            raise ApiError("Enter a valid phone number.", field=key)
    return v


def money_field(data, key, label, allow_zero=True):
    try:
        p = to_paise(data.get(key))
    except (ValueError, InvalidOperation, TypeError, OverflowError):
        raise ApiError(f"{label} is not a valid amount.", field=key)
    if p < 0:
        raise ApiError(f"{label} cannot be negative.", field=key)
    if p == 0 and not allow_zero:
        raise ApiError(f"{label} must be more than 0.", field=key)
    if p > 10**11:
        raise ApiError(f"{label} is too large.", field=key)
    return p


def day_field(data, key="date", label="Date"):
    raw = data.get(key)
    if not raw:
        return date.today().isoformat()
    try:
        d = date.fromisoformat(str(raw))
    except ValueError:
        raise ApiError("Enter a valid date.", field=key)
    if d > date.today():
        raise ApiError(f"{label} cannot be in the future.", field=key)
    if d.year < 2000:
        raise ApiError("Enter a valid date.", field=key)
    return d.isoformat()


def int_field(value, label, field=None, minimum=0, maximum=100000):
    if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value).strip() if value is not None else ""):
        raise ApiError(f"{label} must be a whole number.", field=field)
    n = int(value)
    if not minimum <= n <= maximum:
        raise ApiError(f"{label} must be between {minimum} and {maximum}.", field=field)
    return n


def quantity_milli_field(value, label="Quantity", field=None, allow_zero=False):
    """Parse a quantity to thousandths, avoiding binary-float arithmetic."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        number = Decimal(str(value if value is not None else "").strip())
    except (InvalidOperation, ValueError):
        raise ApiError(f"{label} must be a valid number.", field=field)
    if not number.is_finite():
        raise ApiError(f"{label} must be a valid number.", field=field)
    if number < 0 or (number == 0 and not allow_zero):
        qualifier = "cannot be negative" if number < 0 else "must be greater than zero"
        raise ApiError(f"{label} {qualifier}.", field=field)
    if number > Decimal("1000000"):
        raise ApiError(f"{label} is too large.", field=field)
    milli = int((number * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if milli == 0 and number > 0:
        raise ApiError(f"{label} must be at least 0.001.", field=field)
    return milli


def quantity_from_milli(value):
    value = int(value or 0)
    whole, fraction = divmod(value, 1000)
    return str(whole) if not fraction else f"{whole}.{fraction:03d}".rstrip("0")

# ---------- GST / HSN reference validation (v0.6) ----------
STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}


def hsn_field(data, key="hsn"):
    """Return HSN/SAC as text; optional on product setup, required by invoice logic."""
    value = data.get(key)
    value = "" if value is None else str(value).strip().replace(" ", "")
    if not value:
        return None
    if not re.fullmatch(r"[0-9]{2,10}", value):
        raise ApiError("HSN/SAC must contain 2 to 10 digits.", field=key)
    return value


def gst_rate_bp_field(data, key="gst_rate"):
    """Convert a percentage (e.g. 18 or 5.5) into integer basis points."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    raw = data.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ApiError("GST rate must be a valid percentage.", field=key)
    if not value.is_finite() or value < 0 or value > 100:
        raise ApiError("GST rate must be between 0 and 100 percent.", field=key)
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def state_code_field(data, key="state_code", required=False):
    raw = data.get(key)
    value = "" if raw is None else str(raw).strip()
    if not value:
        if required:
            raise ApiError("Choose a state code.", field=key)
        return None
    if value not in STATES:
        raise ApiError("Choose a valid two-digit Indian state code.", field=key)
    return value


def gstin_field(data, key="gstin", required=False):
    value = (data.get(key) or "")
    value = str(value).strip().upper()
    if not value:
        if required:
            raise ApiError("GSTIN is required for invoice settings.", field=key)
        return None
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        raise ApiError("Enter a valid 15-character GSTIN.", field=key)
    if value[:2] not in STATES:
        raise ApiError("GSTIN contains an unknown state code.", field=key)
    return value