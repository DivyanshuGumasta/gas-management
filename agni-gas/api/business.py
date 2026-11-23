"""Agency invoice details stored in the existing settings table."""
from flask import jsonify

from db import get_db, transaction
from . import api_bp
from .util import STATES, ApiError, body, gstin_field, state_code_field, text

FIELDS = (
    "name", "address", "gstin", "state_code", "phone", "email",
    "bank_name", "bank_account", "bank_ifsc", "terms", "invoice_prefix",
)
PREFIX = "business."


def business_dict(db):
    values = {
        r["key"][len(PREFIX):]: r["value"]
        for r in db.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'business.%'"
        )
    }
    result = {name: values.get(name) or None for name in FIELDS}
    result["invoice_prefix"] = result["invoice_prefix"] or "S"
    result["state_name"] = STATES.get(result["state_code"])
    return result


def missing_business(values):
    required = (("name", "Agency name"), ("address", "Agency address"),
                ("state_code", "Agency state"))
    return [label for key, label in required if not values.get(key)]


@api_bp.get("/business")
def business_get():
    return jsonify(business_dict(get_db()))


@api_bp.put("/business")
def business_save():
    data = body()
    values = {
        "name": text(data, "name", "Agency name", required=True, max_len=120),
        "address": text(data, "address", "Agency address", required=True, max_len=300),
        "gstin": gstin_field(data, required=False),
        "state_code": state_code_field(data, required=True),
        "phone": text(data, "phone", "Phone", max_len=30),
        "email": text(data, "email", "Email", max_len=120),
        "bank_name": text(data, "bank_name", "Bank name", max_len=100),
        "bank_account": text(data, "bank_account", "Bank account", max_len=40),
        "bank_ifsc": text(data, "bank_ifsc", "IFSC", max_len=20),
        "terms": text(data, "terms", "Terms", max_len=500),
        "invoice_prefix": text(data, "invoice_prefix", "Invoice prefix", max_len=8) or "S",
    }
    if values["gstin"] and values["gstin"][:2] != values["state_code"]:
        raise ApiError("Agency state must match the first two digits of its GSTIN.", field="state_code")
    if not values["invoice_prefix"].isalnum():
        raise ApiError("Invoice prefix can contain letters and numbers only.", field="invoice_prefix")
    db = get_db()
    with transaction(db):
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (PREFIX + key, value),
            )
    return jsonify(business_dict(db))