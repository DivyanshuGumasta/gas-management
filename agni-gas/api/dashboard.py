"""GET /api/dashboard - everything the Home screen shows, in one call.

Money is returned as rupee strings ("4100.00"); see money.py.
The JSON shape is the contract static/js/dashboard.js depends on.
"""
from datetime import date, datetime, timedelta

from flask import jsonify

from db import get_db
from money import to_rupees

from . import api_bp


def _time_label(created_at: str) -> str:
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
    except (TypeError, ValueError):
        return ""


@api_bp.get("/dashboard")
def dashboard():
    db = get_db()
    today = date.today()
    t = today.isoformat()

    # --- today's numbers (cancelled bills never count) ---
    s = db.execute(
        """
        SELECT COALESCE(SUM(total_paise), 0)                                  AS sales,
               COALESCE(SUM(paid_paise), 0)                                   AS paid,
               COALESCE(SUM(MAX(total_paise - paid_paise, 0)), 0)             AS due,
               COUNT(DISTINCT CASE WHEN total_paise > paid_paise AND customer_id IS NOT NULL
                                   THEN customer_id END)                      AS due_customers
        FROM sales WHERE sale_date = ? AND status = 'active'
        """,
        (t,),
    ).fetchone()
    received = db.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) FROM payments WHERE payment_date = ? AND status = 'active'",
        (t,),
    ).fetchone()[0]

    # --- stock cards ---
    st = db.execute(
        """
        SELECT COALESCE(SUM(full_qty), 0) AS full, COALESCE(SUM(empty_qty), 0) AS empty,
               COALESCE(SUM(with_customers_qty), 0) AS with_customers
        FROM cylinder_types WHERE active = 1
        """
    ).fetchone()
    customer_count = db.execute("SELECT COUNT(*) FROM customers WHERE active = 1").fetchone()[0]

    # --- last 7 days (today is the last bar) ---
    start = (today - timedelta(days=6)).isoformat()
    per_day = {
        r["sale_date"]: r["total"]
        for r in db.execute(
            "SELECT sale_date, SUM(total_paise) AS total FROM sales "
            "WHERE sale_date BETWEEN ? AND ? AND status = 'active' GROUP BY sale_date",
            (start, t),
        )
    }
    last7, week_total = [], 0
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        total = per_day.get(d.isoformat(), 0)
        week_total += total
        last7.append({"date": d.isoformat(), "label": d.strftime("%d %b"), "total": to_rupees(total)})

    # --- recent sales ---
    recent = []
    rows = db.execute(
        """
        SELECT s.id, s.number, s.created_at, s.total_paise, s.paid_paise, c.name AS customer
        FROM sales s LEFT JOIN customers c ON c.id = s.customer_id
        WHERE s.status = 'active'
        ORDER BY s.created_at DESC, s.id DESC LIMIT 4
        """
    ).fetchall()
    for r in rows:
        items = db.execute(
            "SELECT si.qty_out, ct.name FROM sale_items si "
            "JOIN cylinder_types ct ON ct.id = si.cylinder_type_id "
            "WHERE si.sale_id = ? AND si.qty_out > 0 ORDER BY si.id",
            (r["id"],),
        ).fetchall()
        recent.append(
            {
                "id": r["id"],
                "number": r["number"],
                "customer": r["customer"] or "Walk-in customer",
                "walk_in": r["customer"] is None,
                "time": _time_label(r["created_at"]),
                "items": ", ".join(f"{i['qty_out']} x {i['name']}" for i in items),
                "amount": to_rupees(r["total_paise"]),
                "status": "paid" if r["paid_paise"] >= r["total_paise"] else "pending",
            }
        )

    return jsonify(
        {
            "today": {
                "sales": to_rupees(s["sales"]),
                "payments": to_rupees(s["paid"] + received),
                "udhaar_amount": to_rupees(s["due"]),
                "udhaar_customers": s["due_customers"],
            },
            "stock": {
                "full": st["full"],
                "empty": st["empty"],
                "with_customers": st["with_customers"],
                "total_customers": customer_count,
            },
            "last7": last7,
            "last7_total": to_rupees(week_total),
            "recent": recent,
        }
    )
