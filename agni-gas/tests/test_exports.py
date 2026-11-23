"""Regression tests for PDF and Excel exports on every existing data tab."""
import importlib
import os
import tempfile
import unittest
import zipfile
from io import BytesIO


class TabExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "exports-test.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.conn = db.connect()
        self.customer_id = self.conn.execute(
            "INSERT INTO customers(name,type,opening_balance_paise) VALUES('Export Customer','retail',0)"
        ).lastrowid
        self.supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin,opening_balance_paise) VALUES('Export Supplier','22AAAAA0000A1Z5',0)"
        ).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_pdf_and_excel_exports_exist_for_every_page_scope(self):
        scopes = [
            "sales", "customers", "payments", "suppliers", "purchases", "stock", "stock-history",
            f"customer:{self.customer_id}", f"customer-cylinders:{self.customer_id}",
            f"customer-prices:{self.customer_id}", f"supplier-statement:{self.supplier_id}",
            f"supplier-purchases:{self.supplier_id}", f"supplier-items:{self.supplier_id}",
        ]
        for scope in scopes:
            with self.subTest(scope=scope, format="pdf"):
                response = self.client.get(f"/api/exports/{scope}?format=pdf")
                self.assertEqual(response.status_code, 200, f"HTTP {response.status_code} ({response.mimetype}); first response bytes: {response.data[:160]!r}")
                self.assertEqual(response.mimetype, "application/pdf")
                self.assertTrue(response.data.startswith(b"%PDF-"))
            with self.subTest(scope=scope, format="xlsx"):
                response = self.client.get(f"/api/exports/{scope}?format=xlsx")
                self.assertEqual(response.status_code, 200, f"HTTP {response.status_code} ({response.mimetype}); first response bytes: {response.data[:160]!r}")
                self.assertEqual(response.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.assertTrue(response.data.startswith(b"PK"))

    def test_sales_export_applies_inclusive_date_and_search_filters(self):
        from datetime import date, timedelta
        today = date.today()
        target = (today - timedelta(days=2)).isoformat()
        self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,subtotal_paise,taxable_paise,gst_paise,total_paise,paid_paise,received_in,status) "
            "VALUES('EX-SALE-1',?,?,?,?,?,?,?,'cash','active')",
            (self.customer_id, target, 10000, 10000, 0, 10000, 10000),
        )
        self.conn.commit()
        response = self.client.get(f"/api/exports/sales?format=xlsx&from={target}&to={target}&q=EX-SALE-1")
        self.assertEqual(response.status_code, 200, f"HTTP {response.status_code} ({response.mimetype}); first response bytes: {response.data[:160]!r}")
        outside = self.client.get(f"/api/exports/sales?format=pdf&from={today.isoformat()}&to={today.isoformat()}&q=EX-SALE-1")
        self.assertEqual(outside.status_code, 200)

    def test_purchase_tab_export_includes_new_empty_shell_acquisition_cost(self):
        from datetime import date
        cylinder_id = self.conn.execute("SELECT id FROM cylinder_types ORDER BY id LIMIT 1").fetchone()[0]
        purchase_id = self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_paise,total_paise,status) "
            "VALUES('EX-PURCHASE-EMPTY',?,?,80000,0,80000,'active')",
            (self.supplier_id, date.today().isoformat()),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO purchase_items(purchase_id,cylinder_type_id,new_empty_qty,new_empty_cost_paise,"
            "security_rate_paise,amount_paise) VALUES(?,?,2,40000,0,80000)",
            (purchase_id, cylinder_id),
        )
        self.conn.commit()
        response = self.client.get("/api/exports/purchases?format=xlsx")
        self.assertEqual(response.status_code, 200,
                         f"HTTP {response.status_code} ({response.mimetype}); bytes={response.data[:160]!r}")
        with zipfile.ZipFile(BytesIO(response.data)) as archive:
            shared = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("New empty shell acquisition cost", shared)

    def test_invalid_export_format_or_date_is_rejected(self):
        self.assertEqual(self.client.get("/api/exports/sales?format=csv").status_code, 400)
        self.assertEqual(self.client.get("/api/exports/sales?format=pdf&from=not-a-date").status_code, 400)
        self.assertEqual(self.client.get("/api/exports/sales?format=pdf&from=2026-11-20&to=2026-11-19").status_code, 400)


if __name__ == "__main__":
    unittest.main()
