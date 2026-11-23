"""Regression tests for CA Reports workbook, costing, and exports."""
import importlib
import os
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from io import BytesIO
from xml.etree import ElementTree


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "reports-test.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.db = db
        self.conn = db.connect()
        self.customer_id = self.conn.execute(
            "INSERT INTO customers(name,type,opening_balance_paise) VALUES('Report Test Customer','retail',0)"
        ).lastrowid
        self.supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin,opening_balance_paise) VALUES('Report Test Supplier','22AAAAA0000A1Z5',0)"
        ).lastrowid
        self.cylinder_id = self.conn.execute(
            "SELECT id FROM cylinder_types ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def add_sale(self, day, value_rupees, paid_rupees=0, status="active", line=True,
                 cylinder_qty=1, fifo_cost_rupees=0, number=None):
        value = int(round(value_rupees * 100))
        paid = int(round(paid_rupees * 100))
        sid = self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,subtotal_paise,discount_paise,gst_percent,"
            "gst_paise,total_paise,paid_paise,received_in,status,taxable_paise,deposit_received_paise,"
            "deposit_refunded_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number or f"R-{self.conn.execute('SELECT COUNT(*) FROM sales').fetchone()[0]+1:05d}",
             self.customer_id, day, value, 0, 0, 0, value, paid, "cash", status, value, 0, 0),
        ).lastrowid
        if line:
            self.conn.execute(
                "INSERT INTO sale_lines(sale_id,line_no,kind,action,cylinder_type_id,description,unit,"
                "qty_milli,rate_paise,gross_paise,taxable_paise,amount_paise) "
                "VALUES(1,1,'product','refill',?,?,?,?,?,?,?,?)".replace("VALUES(1,1", "VALUES(?,1"),
                (sid, self.cylinder_id, "Test cylinder", "NOS", cylinder_qty * 1000,
                 value // max(1, cylinder_qty), value, value, value),
            )
            if fifo_cost_rupees:
                self.conn.execute(
                    "INSERT INTO lot_consumptions(lot_id,cylinder_type_id,ref_type,ref_id,qty,unit_cost_paise,status) "
                    "VALUES(NULL,?,'sale',?,?,?,'active')",
                    (self.cylinder_id, sid, cylinder_qty, int(round(fifo_cost_rupees * 100))),
                )
        self.conn.commit()
        return sid

    def add_customer_payment(self, day, amount_rupees, status="active", method="cash"):
        self.conn.execute(
            "INSERT INTO payments(number,customer_id,amount_paise,payment_date,received_in,status) VALUES(?,?,?,?,?,?)",
            (f"RP-{day}-{amount_rupees}-{self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0]}",
             self.customer_id, int(round(amount_rupees * 100)), day, method, status),
        )
        self.conn.commit()

    def test_cancelled_bills_payments_and_purchases_are_excluded(self):
        today = date.today().isoformat()
        self.add_sale(today, 1000, 1000, "active", fifo_cost_rupees=400)
        self.add_sale(today, 9000, 9000, "cancelled", fifo_cost_rupees=100)
        self.add_customer_payment(today, 250, "active", "bank")
        self.add_customer_payment(today, 700, "cancelled", "cash")
        self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_paise,total_paise,status) "
            "VALUES('P-ACTIVE',?,?,10000,1800,11800,'active')", (self.supplier_id, today))
        self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_paise,total_paise,status) "
            "VALUES('P-CANCELLED',?,?,90000,16200,106200,'cancelled')", (self.supplier_id, today))
        self.conn.execute(
            "INSERT INTO supplier_payments(number,supplier_id,amount_paise,payment_date,paid_from,status) "
            "VALUES('SP-ACTIVE',?,5000,?,'cash','active')", (self.supplier_id, today))
        self.conn.execute(
            "INSERT INTO supplier_payments(number,supplier_id,amount_paise,payment_date,paid_from,status) "
            "VALUES('SP-CANCELLED',?,90000,?,'cash','cancelled')", (self.supplier_id, today))
        self.conn.commit()

        result = self.client.get("/api/reports?period=today").get_json()
        self.assertEqual(result["kpis"]["sales"], "1000.00")
        self.assertEqual(result["kpis"]["bills"], 1)
        self.assertEqual(result["kpis"]["cash_received"], "1250.00")
        self.assertEqual(result["kpis"]["purchases"], "118.00")
        self.assertEqual(result["kpis"]["purchase_bills"], 1)
        self.assertEqual(result["summary"]["paid_to_supplier"], "50.00")


    def test_existing_purchase_can_be_given_its_supplier_invoice_number(self):
        today = date.today().isoformat()
        purchase_id = self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_percent,gst_paise,total_paise,status) "
            "VALUES('P-OLD-REF',?,?,10000,18,1800,11800,'active')",
            (self.supplier_id, today),
        ).lastrowid
        self.conn.commit()
        response = self.client.put(
            f"/api/purchases/{purchase_id}/supplier-invoice-number",
            json={"supplier_invoice_number": "SUP-OLD-INV-42"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["supplier_invoice_number"], "SUP-OLD-INV-42")
        saved = self.conn.execute(
            "SELECT supplier_invoice_number FROM purchases WHERE id=?", (purchase_id,)
        ).fetchone()[0]
        self.assertEqual(saved, "SUP-OLD-INV-42")

    def test_ca_workbook_contains_supplier_invoice_number_separately(self):
        today = date.today().isoformat()
        self.conn.execute(
            "INSERT INTO purchases(number,supplier_invoice_number,supplier_id,purchase_date,subtotal_paise,gst_percent,gst_paise,total_paise,status) "
            "VALUES('P-INTERNAL-7','SUP-TAX-INV-2026-19',?,?,10000,18,1800,11800,'active')",
            (self.supplier_id, today),
        )
        self.conn.commit()
        response = self.client.get(f"/api/reports/export.xlsx?period=today")
        self.assertEqual(response.status_code, 200, f"HTTP {response.status_code}: {response.data[:160]!r}")
        with zipfile.ZipFile(BytesIO(response.data)) as archive:
            shared = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            text_values = [node.text or "" for node in shared.iter() if node.tag.endswith("}t")]
        self.assertIn("SUP-TAX-INV-2026-19", text_values)
        self.assertIn("P-INTERNAL-7", text_values)

    def test_sales_reconcile_across_kpi_chart_and_item_breakdown(self):
        today = date.today()
        self.add_sale(today.isoformat(), 1000, 300, fifo_cost_rupees=450)
        self.add_sale((today - timedelta(days=1)).isoformat(), 500, 100, fifo_cost_rupees=200)
        result = self.client.get("/api/reports?period=7d").get_json()
        sales = float(result["kpis"]["sales"])
        chart_total = sum(float(row["total"]) for row in result["by_day"])
        items_total = sum(float(row["amount"]) for row in result["by_item"] if row["type"] != "Total")
        self.assertAlmostEqual(sales, chart_total, places=2)
        self.assertAlmostEqual(sales, items_total, places=2)
        self.assertAlmostEqual(sales, float(result["by_item"][-1]["amount"]), places=2)
        self.assertEqual(result["money_in"][-1]["amount"], result["kpis"]["cash_received"])
        self.assertEqual(result["kpis"]["profit"], "850.00")

    def test_later_payment_for_old_bill_is_counted_on_payment_date_once(self):
        today = date.today()
        old_day = (today - timedelta(days=10)).isoformat()
        self.add_sale(old_day, 2000, 500, fifo_cost_rupees=1000)
        self.add_customer_payment(today.isoformat(), 700, "active", "bank")
        self.add_sale(today.isoformat(), 400, 200, fifo_cost_rupees=100)

        result = self.client.get("/api/reports?period=7d").get_json()
        self.assertEqual(result["kpis"]["sales"], "400.00")
        self.assertEqual(result["kpis"]["cash_received"], "900.00")
        self.assertEqual(result["money_in"][-1]["amount"], "900.00")

    def test_custom_range_is_inclusive_at_both_ends(self):
        today = date.today()
        first = today - timedelta(days=3)
        last = today - timedelta(days=1)
        self.add_sale((first - timedelta(days=1)).isoformat(), 100)
        self.add_sale(first.isoformat(), 200)
        self.add_sale(last.isoformat(), 300)
        self.add_sale((last + timedelta(days=1)).isoformat(), 400)
        result = self.client.get(
            f"/api/reports?period=custom&from={first.isoformat()}&to={last.isoformat()}"
        ).get_json()
        self.assertEqual(result["kpis"]["sales"], "500.00")
        self.assertEqual(result["period"]["from"], first.isoformat())
        self.assertEqual(result["period"]["to"], last.isoformat())

    def test_long_custom_range_weekly_buckets_do_not_skip_midweek_dates(self):
        today = date.today()
        first = today - timedelta(days=39)  # deliberately starts mid-week
        self.add_sale(first.isoformat(), 100)
        self.add_sale((first + timedelta(days=1)).isoformat(), 200)
        self.add_sale((first + timedelta(days=8)).isoformat(), 300)
        self.add_sale(today.isoformat(), 400)
        result = self.client.get(
            f"/api/reports?period=custom&from={first.isoformat()}&to={today.isoformat()}"
        ).get_json()
        chart_total = sum(float(row["total"]) for row in result["by_day"])
        self.assertEqual(result["kpis"]["sales"], "1000.00")
        self.assertAlmostEqual(chart_total, 1000.00, places=2)
        self.assertGreater(len(result["by_day"]), 1)
        self.assertLess(len(result["by_day"]), 40)

    def test_zero_sales_has_no_arbitrary_best_day(self):
        result = self.client.get("/api/reports?period=month").get_json()
        self.assertIsNone(result["best_day"]["date"])
        self.assertEqual(result["best_day"]["total"], "0.00")

    def test_empty_database_returns_zero_values(self):
        result = self.client.get("/api/reports?period=month").get_json()
        self.assertEqual(result["kpis"]["sales"], "0.00")
        self.assertEqual(result["kpis"]["bills"], 0)
        self.assertEqual(result["kpis"]["cash_received"], "0.00")
        self.assertEqual(result["kpis"]["purchases"], "0.00")
        self.assertEqual(result["kpis"]["profit"], "0.00")
        self.assertEqual(result["by_item"][-1]["amount"], "0.00")
        self.assertEqual(result["money_in"][-1]["amount"], "0.00")

    def test_export_endpoints_return_expected_formats(self):
        self.add_sale(date.today().isoformat(), 100, 100, fifo_cost_rupees=40)
        pdf = self.client.get("/api/reports/export.pdf?period=today")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF-"))

        excel = self.client.get("/api/reports/export.xlsx?period=today")
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(excel.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(excel.data.startswith(b"PK"))

    def test_custom_reversed_range_is_rejected(self):
        today = date.today()
        start, end = today.isoformat(), (today - timedelta(days=1)).isoformat()
        response = self.client.get(f"/api/reports?period=custom&from={start}&to={end}")
        self.assertEqual(response.status_code, 400)

    def test_catalogue_item_cogs_uses_supplier_fifo_price_not_latest_price(self):
        today = date.today().isoformat()
        item_id = self.conn.execute(
            "INSERT INTO catalog_items(name,unit,purchase_price_paise,sale_price_paise,stock_qty_milli) "
            "VALUES('FIFO Regulator','pcs',4000,10000,0)"
        ).lastrowid
        purchase_id = self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_paise,total_paise,status) "
            "VALUES('P-REG-FIFO',?,?,12000,2160,14160,'active')", (self.supplier_id, today)
        ).lastrowid
        self.conn.execute(
            "INSERT INTO purchase_catalog_items(purchase_id,item_id,item_name,unit,quantity_milli,rate_paise,amount_paise) "
            "VALUES(?,?,?,?,?,?,?)", (purchase_id,item_id,"FIFO Regulator","pcs",3000,4000,12000)
        )
        self.conn.execute(
            "INSERT INTO catalog_stock_movements(item_id,purchase_id,quantity_delta_milli) VALUES(?,?,3000)",
            (item_id,purchase_id),
        )
        self.conn.execute("UPDATE catalog_items SET stock_qty_milli=3000,purchase_price_paise=9000 WHERE id=?", (item_id,))
        sale_id = self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,subtotal_paise,discount_paise,gst_percent,gst_paise,total_paise,"
            "paid_paise,received_in,status,taxable_paise,cgst_paise,sgst_paise,deposit_received_paise,deposit_refunded_paise) "
            "VALUES('S-REG-FIFO',?,?,10000,0,18,1800,11800,11800,'cash','active',10000,900,900,0,0)",
            (self.customer_id,today),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO sale_lines(sale_id,line_no,kind,action,item_id,description,hsn,unit,qty_milli,rate_paise,"
            "gross_paise,taxable_paise,gst_rate_bp,cgst_paise,sgst_paise,amount_paise) "
            "VALUES(?,1,'product','item',?,'FIFO Regulator','8481','pcs',1000,10000,10000,10000,1800,900,900,11800)",
            (sale_id,item_id),
        )
        self.conn.execute(
            "INSERT INTO catalog_sale_movements(sale_id,item_id,quantity_delta_milli,kind,note) VALUES(?,?, -1000,'sale','sale')",
            (sale_id,item_id),
        )
        self.conn.execute("UPDATE catalog_items SET stock_qty_milli=2000 WHERE id=?", (item_id,))
        self.conn.commit()

        result = self.client.get("/api/reports?period=today").get_json()
        self.assertEqual(result["summary"]["cogs_catalogue"], "40.00")
        self.assertEqual(result["summary"]["gross_profit"], "60.00")
        self.assertEqual(result["summary"]["cogs_costing_complete"], True)
        self.assertEqual(result["by_item"][0]["cost"], "40.00")

    def test_new_empty_cylinders_are_deposits_not_sales_or_cogs(self):
        today = date.today().isoformat()
        cylinder_id = self.cylinder_id
        purchase_id = self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,subtotal_paise,gst_paise,total_paise,status) "
            "VALUES('P-EMPTY-DEP',?,?,50000,0,50000,'active')", (self.supplier_id,today)
        ).lastrowid
        self.conn.execute(
            "INSERT INTO purchase_items(purchase_id,cylinder_type_id,new_empty_qty,security_rate_paise,amount_paise) "
            "VALUES(?,?,2,25000,50000)", (purchase_id,cylinder_id)
        )
        self.conn.execute(
            "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,purchase_id,note,status) "
            "VALUES(?,?,'paid',2,50000,?,'New empty cylinder deposit','active')",
            (cylinder_id,self.supplier_id,purchase_id),
        )
        sale_id = self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,subtotal_paise,gst_percent,gst_paise,total_paise,paid_paise,"
            "received_in,status,taxable_paise,deposit_received_paise,deposit_refunded_paise) "
            "VALUES('S-EMPTY-DEP',?,?,0,0,0,25000,25000,'cash','active',0,25000,0)",
            (self.customer_id,today),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO sale_lines(sale_id,line_no,kind,action,cylinder_type_id,description,unit,qty_milli,rate_paise,"
            "gross_paise,taxable_paise,amount_paise) VALUES(?,1,'deposit','new_empty',?,'New empty cylinder','NOS',1000,25000,25000,0,25000)",
            (sale_id,cylinder_id),
        )
        self.conn.execute(
            "INSERT INTO customer_deposit_events(customer_id,cylinder_type_id,sale_id,supplier_id,kind,qty,amount_paise,event_date,note) "
            "VALUES(?,?,?,?,'received',1,25000,?,'Refundable deposit')",
            (self.customer_id,cylinder_id,sale_id,self.supplier_id,today),
        )
        self.conn.commit()

        result = self.client.get("/api/reports?period=today").get_json()
        self.assertEqual(result["kpis"]["sales"], "0.00")
        self.assertEqual(result["summary"]["total_cogs"], "0.00")
        self.assertEqual(result["summary"]["new_empty_purchased_qty"], 2)
        self.assertEqual(result["summary"]["new_empty_supplier_deposit_paid"], "500.00")
        self.assertEqual(result["summary"]["new_empty_issued_qty"], 1)
        self.assertEqual(result["summary"]["new_empty_customer_deposit_received"], "250.00")
        self.assertEqual(result["snapshots"]["supplier_cylinder_deposits"], "500.00")
        self.assertEqual(result["snapshots"]["customer_cylinder_deposits"], "250.00")

        # Damaging a supplier-owned cylinder forfeits part of the supplier deposit.
        self.conn.execute(
            "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,sale_id,note,status) "
            "VALUES(?,?,'cancelled',1,5000,?,'Damaged cylinder deposit loss','active')",
            (cylinder_id,self.supplier_id,sale_id),
        )
        self.conn.commit()
        after_damage = self.client.get("/api/reports?period=today").get_json()
        self.assertEqual(after_damage["summary"]["supplier_deposit_forfeited"], "50.00")
        self.assertEqual(after_damage["summary"]["result_after_recorded_losses"], "-50.00")
        self.assertEqual(after_damage["snapshots"]["supplier_cylinder_deposits"], "450.00")

    def test_new_empty_shell_acquisition_cost_is_separate_from_security_deposits(self):
        today = date.today().isoformat()
        self.conn.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
            "VALUES(?,?,100000,25000,0)", (self.supplier_id, self.cylinder_id),
        )
        self.conn.commit()

        response = self.client.post("/api/purchases", json={
            "supplier_id": self.supplier_id,
            "date": today,
            "gst_percent": "0",
            "paid_amount": "0",
            "items": [{
                "cylinder_type_id": self.cylinder_id,
                "full_in": 0,
                "empty_out": 0,
                "new_empty": 2,
                "new_full": 0,
                "rate": "0",
                "deposit": "250",
                "new_empty_cost": "40",
            }],
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        purchase_id = response.get_json()["id"]
        purchase = self.client.get(f"/api/purchases/{purchase_id}").get_json()
        self.assertEqual(purchase["items"][0]["new_empty_cost"], "40.00")
        self.assertEqual(purchase["subtotal"], "580.00")

        report = self.client.get("/api/reports?period=today").get_json()
        self.assertEqual(report["summary"]["new_empty_shell_acquisition_cost"], "80.00")
        self.assertEqual(report["summary"]["new_empty_supplier_deposit_paid"], "500.00")
        # Shell cost is capitalised while the cylinder remains the agency's asset;
        # refundable deposits are not revenue or ordinary cost of sales.
        self.assertEqual(report["summary"]["total_cogs"], "0.00")
        self.assertEqual(report["summary"]["gross_profit"], "0.00")

        workbook = self.client.get("/api/reports/export.xlsx?period=today")
        self.assertEqual(workbook.status_code, 200,
                         f"HTTP {workbook.status_code} ({workbook.mimetype}); bytes={workbook.data[:160]!r}")
        with zipfile.ZipFile(BytesIO(workbook.data)) as archive:
            shared = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("Capitalised Shell Cost", shared)
            self.assertIn("Shell Cost / Unit", shared)

    def test_ca_workbook_contains_register_costing_and_reconciliation_sheets(self):
        self.add_sale(date.today().isoformat(), 100, 100, fifo_cost_rupees=40)
        response = self.client.get("/api/reports/export.xlsx?period=today")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.data)) as workbook:
            xml = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            names = {sheet.attrib["name"] for sheet in xml.findall("x:sheets/x:sheet", ns)}
        expected = {
            "Overview", "Sales Register", "Sales Lines", "Purchase Bills", "Purchase Items",
            "Customer Receipts", "Supplier Payments", "Customer Ledger", "Supplier Ledger",
            "Sales GST", "Purchase GST", "Reconciliation", "Inventory & COGS",
            "Catalog Adjustments", "Cylinder Adjustments", "Period-end Stock",
            "Cylinder Deposits", "New Empty Cylinders", "Cancelled Documents", "Report Notes",
        }
        self.assertTrue(expected.issubset(names), f"Missing workbook sheets: {sorted(expected - names)}")


if __name__ == "__main__":
    unittest.main()
