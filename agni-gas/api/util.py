"""Validation helpers shared by the API modules. All raise ApiError (-> JSON error)."""
import re
from datetime import date

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
    except ValueError:
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
