"""Deterministic allocation of customer receipts to outstanding sales invoices.

Money is handled as integer paise. Customer-level receipts are applied FIFO to
open invoices in transaction-date order. Any remaining amount stays as an
advance and can be applied to a later invoice.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping


def _value(row: Mapping, key: str, default=0):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = default
    return default if value is None else value


def _event_key(day, created_at, kind_order, row_id):
    return (str(day or ""), str(created_at or ""), kind_order, int(row_id or 0))


def allocate_customer_receipts(
    sales: Iterable[Mapping],
    payments: Iterable[Mapping],
    opening_balance_paise: int = 0,
) -> dict[int, dict[str, int | str]]:
    """Return effective paid/due amounts for each active invoice.

    Opening receivables are cleared before invoice balances. Opening advances,
    invoice overpayments and excess customer receipts carry forward to the next
    oldest outstanding invoice. Cancelled sales and payments are ignored.

    The initial amount paid on an invoice (sales.paid_paise) stays attributed to
    that invoice. Customer receipts and advances are allocated oldest-open-invoice-first.
    """
    events = []
    for sale in sales:
        if _value(sale, "status", "active") != "active":
            continue
        sale_id = int(_value(sale, "id"))
        day = _value(sale, "sale_date", "")
        events.append((_event_key(day, _value(sale, "created_at", ""), 0, sale_id), "sale", sale))
    for payment in payments:
        if _value(payment, "status", "active") != "active":
            continue
        payment_id = int(_value(payment, "id"))
        day = _value(payment, "payment_date", "")
        events.append((_event_key(day, _value(payment, "created_at", ""), 1, payment_id), "payment", payment))
    events.sort(key=lambda item: item[0])

    opening_due = max(0, int(opening_balance_paise or 0))
    advance = max(0, -int(opening_balance_paise or 0))
    balances: dict[int, dict[str, int | str]] = {}
    open_invoices: list[int] = []

    for _key, kind, row in events:
        if kind == "sale":
            sale_id = int(_value(row, "id"))
            total = int(_value(row, "total_paise"))
            base_paid = max(0, int(_value(row, "paid_paise")))
            due = max(0, total - base_paid)

            # Existing overpayment/credit on an invoice becomes an account advance.
            advance += max(0, base_paid - total)
            applied = min(advance, due)
            advance -= applied
            due -= applied
            balances[sale_id] = {
                "paid_paise": min(max(0, total), base_paid) + applied,
                "invoice_paid_paise": base_paid,
                "credits_applied_paise": applied,
                "due_paise": due,
                "status": "paid" if due == 0 else ("partial" if base_paid + applied else "udhaar"),
            }
            if due:
                open_invoices.append(sale_id)
            continue

        remaining = max(0, int(_value(row, "amount_paise")))
        if not remaining:
            continue

        # First clear any opening receivable that predates the invoice ledger.
        opening_payment = min(opening_due, remaining)
        opening_due -= opening_payment
        remaining -= opening_payment

        # Then allocate to the oldest currently-open invoice.
        for sale_id in open_invoices:
            if remaining <= 0:
                break
            item = balances[sale_id]
            due = int(item["due_paise"])
            if due <= 0:
                continue
            applied = min(due, remaining)
            item["due_paise"] = due - applied
            item["paid_paise"] = int(item["paid_paise"]) + applied
            item["credits_applied_paise"] = int(item["credits_applied_paise"]) + applied
            item["status"] = "paid" if int(item["due_paise"]) == 0 else "partial"
            remaining -= applied
        if remaining:
            advance += remaining

    # Return active invoices only; cancelled records never receive allocations.
    return balances
