"""v0.6.2 tax-invoice/document and cancellation audit regression tests."""
import importlib
import os
import tempfile
import unittest
from datetime import date


class InvoiceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "invoice-document.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.conn = db.connect()
        saved = self.client.put("/api/business", json={
            "name": "Document Test LPG", "address": "1 Test Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "pan": "AAAAA0000A",
            "state_code": "22", "invoice_prefix": "DOC",
            "bank_name": "Test Bank", "bank_account": "1234567890", "bank_ifsc": "TEST0001234",
            "terms": "Payment due on receipt.",
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def cylinder(self):
        response = self.client.post("/api/cylinders", json={
            "weight_kg": "8.6", "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": "500", "full": "0", "empty": "0",
            "hsn": "27111910", "gst_rate": "18",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def customer(self, cylinder):
        response = self.client.post("/api/customers", json={
            "name": "Document Customer", "type": "retail", "phone": "9876543210",
            "address": "Durg", "opening_type": "udhaar", "opening_amount": "0",
            "held": [{
                "cylinder_type_id": cylinder["id"], "qty": 2,
                "supplier_id": None, "deposit_each": "5.00",
            }],
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_amount_in_words_uses_indian_currency_groups_and_paise(self):
        from money import amount_in_words
        self.assertEqual(amount_in_words(12345), "Rupees One Hundred Twenty Three and Forty Five Paise Only")
        self.assertEqual(amount_in_words(1234567890),
                         "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight and Ninety Paise Only")
        self.assertEqual(amount_in_words(-300), "Minus Rupees Three Only")

    def test_agency_pan_must_be_valid_and_match_gstin(self):
        mismatch = self.client.put("/api/business", json={
            "name": "Document Test LPG", "address": "1 Test Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "pan": "BBBBB1111B", "state_code": "22",
        })
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("PAN must match", mismatch.get_json()["error"])
        invalid = self.client.put("/api/business", json={
            "name": "Document Test LPG", "address": "1 Test Road, Durg",
            "pan": "NOT-A-PAN", "state_code": "22",
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("valid 10-character PAN", invalid.get_json()["error"])

    def test_invoice_payload_and_pdf_include_retained_deposit_and_tax_document_fields(self):
        from money import amount_in_words
        c = self.cylinder()
        customer = self.customer(c)
        response = self.client.post("/api/sales", json={
            "customer_id": customer["id"], "date": date.today().isoformat(),
            "place_state_code": "22", "lines": [{
                "cylinder_type_id": c["id"], "rate": "100", "refill": 0,
                "new_full": 0, "new_empty": 0, "empty_in": 1, "damaged_in": 0,
                "deposit_back": True, "deposit_each": "3.00",
            }],
            "items": [], "discount": "0", "payment": "paid", "received_in": "cash", "paid": "0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        sid = response.get_json()["id"]
        detail = self.client.get(f"/api/sales/{sid}").get_json()
        self.assertEqual(detail["title"], "TAX INVOICE")
        self.assertEqual(detail["business"]["pan"], "AAAAA0000A")
        self.assertEqual(detail["tax_summary"]["taxable"], "0.00")
        self.assertEqual(detail["grouped_lines"], [])
        self.assertEqual(detail["retained_deposits"], "2.00")
        self.assertEqual(detail["amount_in_words"], amount_in_words(-300))
        self.assertEqual(detail["paid_label"], "Paid back")
        retained = next(line for line in detail["lines"] if line["kind"] == "deposit_refund")
        self.assertEqual(retained["retained"], "2.00")

        pdf = self.client.get(f"/api/sales/{sid}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF-"))
        self.assertIn("attachment", pdf.headers.get("Content-Disposition", ""))

    def test_cancelling_negative_paid_back_invoice_reports_collection_direction(self):
        c = self.cylinder()
        customer = self.customer(c)
        response = self.client.post("/api/sales", json={
            "customer_id": customer["id"], "date": date.today().isoformat(),
            "place_state_code": "22", "lines": [{
                "cylinder_type_id": c["id"], "empty_in": 1, "deposit_back": True,
            }], "items": [], "discount": "0", "payment": "paid", "received_in": "cash", "paid": "0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        cancelled = self.client.post(f"/api/sales/{response.get_json()['id']}/cancel", json={
            "reason": "Wrong customer return",
        })
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()["refund"], "5.00")
        self.assertEqual(cancelled.get_json()["refund_direction"], "collect")


if __name__ == "__main__":
    unittest.main()
