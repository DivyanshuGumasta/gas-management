"""Regression tests for customer receipts appearing against Sales invoices."""
import unittest

from sale_receipts import allocate_customer_receipts


class ReceiptAllocationTests(unittest.TestCase):
    def sale(self, sale_id, day, total, paid=0, created="10:00:00", status="active"):
        return {
            "id": sale_id, "sale_date": day, "created_at": f"{day} {created}",
            "total_paise": total, "paid_paise": paid, "status": status,
        }

    def payment(self, payment_id, day, amount, created="11:00:00", status="active"):
        return {
            "id": payment_id, "payment_date": day, "created_at": f"{day} {created}",
            "amount_paise": amount, "status": status,
        }

    def test_later_receive_payment_updates_part_paid_invoice(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-01", 10_000, 4_000)],
            [self.payment(1, "2026-11-05", 3_000)],
        )
        self.assertEqual(result[1]["invoice_paid_paise"], 4_000)
        self.assertEqual(result[1]["credits_applied_paise"], 3_000)
        self.assertEqual(result[1]["paid_paise"], 7_000)
        self.assertEqual(result[1]["due_paise"], 3_000)
        self.assertEqual(result[1]["status"], "partial")

    def test_payment_is_allocated_oldest_open_invoice_first(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-01", 10_000, 2_000),
             self.sale(2, "2026-11-02", 5_000)],
            [self.payment(1, "2026-11-03", 10_000)],
        )
        self.assertEqual(result[1]["due_paise"], 0)
        self.assertEqual(result[1]["paid_paise"], 10_000)
        self.assertEqual(result[2]["credits_applied_paise"], 2_000)
        self.assertEqual(result[2]["due_paise"], 3_000)

    def test_payment_before_invoice_is_carried_as_customer_advance(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-03", 10_000, 2_000)],
            [self.payment(1, "2026-11-02", 3_000)],
        )
        self.assertEqual(result[1]["paid_paise"], 5_000)
        self.assertEqual(result[1]["due_paise"], 5_000)

    def test_opening_receivable_is_cleared_before_new_invoices(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-02", 10_000)],
            [self.payment(1, "2026-11-03", 7_000)],
            opening_balance_paise=5_000,
        )
        self.assertEqual(result[1]["credits_applied_paise"], 2_000)
        self.assertEqual(result[1]["due_paise"], 8_000)

    def test_opening_advance_is_applied_to_next_invoice(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-02", 10_000)], [], opening_balance_paise=-3_000,
        )
        self.assertEqual(result[1]["paid_paise"], 3_000)
        self.assertEqual(result[1]["due_paise"], 7_000)

    def test_cancelled_sales_and_payments_are_ignored(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-01", 10_000, status="cancelled"),
             self.sale(2, "2026-11-02", 10_000)],
            [self.payment(1, "2026-11-03", 9_000, status="cancelled"),
             self.payment(2, "2026-11-04", 4_000)],
        )
        self.assertNotIn(1, result)
        self.assertEqual(result[2]["paid_paise"], 4_000)
        self.assertEqual(result[2]["due_paise"], 6_000)

    def test_overpayment_carries_forward_to_the_next_invoice(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-01", 10_000),
             self.sale(2, "2026-11-04", 10_000)],
            [self.payment(1, "2026-11-03", 15_000)],
        )
        self.assertEqual(result[1]["due_paise"], 0)
        self.assertEqual(result[2]["paid_paise"], 5_000)
        self.assertEqual(result[2]["due_paise"], 5_000)

    def test_negative_sale_credit_is_carried_forward(self):
        result = allocate_customer_receipts(
            [self.sale(1, "2026-11-01", -2_000),
             self.sale(2, "2026-11-02", 10_000)], [],
        )
        self.assertEqual(result[2]["paid_paise"], 2_000)
        self.assertEqual(result[2]["due_paise"], 8_000)


if __name__ == "__main__":
    unittest.main()

# The pure allocation tests above remain runnable without Flask. This API-level
# regression is enabled in the application's normal environment.
try:
    import importlib.util
    HAS_FLASK = importlib.util.find_spec("flask") is not None
except (ImportError, ValueError):
    HAS_FLASK = False


@unittest.skipUnless(HAS_FLASK, "Flask is not installed in this test environment")
class ReceiptAllocationApiTests(unittest.TestCase):
    def setUp(self):
        import importlib
        import os
        import tempfile
        from datetime import date, timedelta

        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "receipt-allocation.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.conn = db.connect()
        self.customer_id = self.conn.execute(
            "INSERT INTO customers(name,type,opening_balance_paise) VALUES('Receipt Customer','retail',0)"
        ).lastrowid
        self.sale_date = (date.today() - timedelta(days=1)).isoformat()
        self.sale_id = self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,subtotal_paise,taxable_paise,gst_paise,"
            "total_paise,paid_paise,received_in,status) VALUES(?,?,?,?,?,?,?,?,?,'active')",
            ("RCPT-TEST-001", self.customer_id, self.sale_date, 10_000, 10_000, 0,
             10_000, 4_000, "cash"),
        ).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_receive_payment_refreshes_sales_list_and_invoice_detail(self):
        from datetime import date

        payment = self.client.post("/api/payments", json={
            "customer_id": self.customer_id, "amount": "30.00",
            "received_in": "bank", "date": date.today().isoformat(),
            "note": "Later collection",
        })
        self.assertEqual(payment.status_code, 201, payment.get_json())

        listing = self.client.get("/api/sales")
        self.assertEqual(listing.status_code, 200, listing.get_json())
        invoice = next(row for row in listing.get_json()["sales"] if row["id"] == self.sale_id)
        self.assertEqual(invoice["effective_paid"], "70.00")
        self.assertEqual(invoice["customer_credits_applied"], "30.00")
        self.assertEqual(invoice["due"], "30.00")
        self.assertEqual(invoice["status"], "partial")
        self.assertEqual(listing.get_json()["summary"]["udhaar"], "30.00")

        detail = self.client.get(f"/api/sales/{self.sale_id}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(detail.get_json()["paid"], "40.00")
        self.assertEqual(detail.get_json()["effective_paid"], "70.00")
        self.assertEqual(detail.get_json()["customer_credits_applied"], "30.00")
        self.assertEqual(detail.get_json()["due"], "30.00")
