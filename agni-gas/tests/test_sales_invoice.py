"""v0.6 HSN/tax-invoice/customer-deposit regression tests. GSTINs are test fixtures only."""
import importlib
import os
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InvoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "invoice-test.db")
        import app as app_module
        importlib.reload(app_module)
        self.app_module = app_module
        self.client = app_module.app.test_client()
        import db
        self.db = db
        self.conn = db.connect()
        self.assertEqual(self.client.put("/api/business", json={
            "name": "Test LPG Agency", "address": "1 Test Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "state_code": "22", "invoice_prefix": "T",
        }).status_code, 200)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def make_cylinder(self):
        result = self.client.post("/api/cylinders", json={
            "weight_kg": "8.6", "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": "500", "full": "5", "empty": "2",
            "hsn": "27111910", "gst_rate": "18",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()

    def make_customer(self):
        result = self.client.post("/api/customers", json={
            "name": "Test Restaurant", "type": "wholesale", "phone": "9876543210",
            "address": "Durg", "billing_address": "Restaurant Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "state_code": "22",
            "opening_type": "udhaar", "opening_amount": "0",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()

    def sell(self, cylinder, customer, **counts):
        line = {"cylinder_type_id": cylinder["id"], "rate": "100", "security": "500",
                "refill": 0, "new_full": 0, "new_empty": 0, "empty_in": 0,
                "damaged_in": 0, "deposit_each": "500"}
        line.update(counts)
        return self.client.post("/api/sales", json={
            "customer_id": customer["id"] if customer else None,
            "date": date.today().isoformat(), "place_state_code": "22",
            "lines": [line], "items": [], "discount": "0", "payment": "paid",
            "received_in": "cash", "paid": "0", "reverse_charge": "no",
        })

    def test_product_hsn_is_snapshotted_and_tax_is_split(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        invoice_id = response.get_json()["id"]
        detail = self.client.get(f"/api/sales/{invoice_id}").get_json()
        self.assertEqual(detail["lines"][0]["hsn"], "27111910")
        self.assertEqual(detail["cgst"], "9.00")
        self.assertEqual(detail["sgst"], "9.00")
        self.assertEqual(detail["igst"], "0.00")
        self.assertEqual(detail["total"], "118.00")

        changed = self.client.put(f"/api/cylinders/{cylinder['id']}", json={
            "weight_kg": "8.6", "hsn": "27111200", "gst_rate": "5",
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())
        old_detail = self.client.get(f"/api/sales/{invoice_id}").get_json()
        self.assertEqual(old_detail["lines"][0]["hsn"], "27111910")
        self.assertEqual(old_detail["lines"][0]["gst_rate"], 18)

    def test_new_full_deposit_is_separate_from_taxable_value(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        detail = self.client.get(f"/api/sales/{response.get_json()['id']}").get_json()
        self.assertEqual(detail["subtotal"], "100.00")
        self.assertEqual(detail["gst"], "18.00")
        self.assertEqual(detail["deposit_received"], "500.00")
        self.assertEqual(detail["total"], "618.00")
        deposit = self.conn.execute(
            "SELECT kind,qty,amount_paise,status FROM customer_deposit_events WHERE customer_id=?",
            (customer["id"],),
        ).fetchone()
        self.assertEqual((deposit["kind"], deposit["qty"], deposit["amount_paise"], deposit["status"]),
                         ("received", 1, 50000, "active"))

    def test_good_empty_refund_updates_only_customer_deposit_ledger(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        sale = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(sale.status_code, 201, sale.get_json())
        returned = self.sell(cylinder, customer, empty_in=1, deposit_back=True)
        self.assertEqual(returned.status_code, 201, returned.get_json())
        detail = self.client.get(f"/api/sales/{returned.get_json()['id']}").get_json()
        self.assertEqual(detail["deposit_refunded"], "500.00")
        events = self.conn.execute(
            "SELECT kind,amount_paise,status FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([e["kind"] for e in events], ["received", "refunded"])
        self.assertEqual([e["amount_paise"] for e in events], [50000, 50000])
        # The supplier deposit ledger is untouched by a normal customer deposit refund.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0], 0)

    def test_damaged_customer_return_forfeits_customer_deposit_and_marks_stock(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())
        events = self.conn.execute(
            "SELECT kind,amount_paise,status FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([e["kind"] for e in events], ["received", "forfeited"])
        stock = self.client.get("/api/stock").get_json()
        c = next(x for x in stock["cylinders"] if x["id"] == cylinder["id"])
        self.assertEqual(c["damaged"], 1)
        # With no suppliers in this isolated test, no supplier security event is fabricated.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0], 0)

    def test_damaged_customer_return_forfeits_the_matching_supplier_deposit(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin) VALUES(?,?)",
            ("Go Gas Test", "22AAAAA0000A1Z5"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
            "VALUES(?,?,?,?,0)", (supplier_id, cylinder["id"], 7000, 50000),
        )
        self.conn.execute(
            "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note) "
            "VALUES(?,?,'paid',5,250000,'Supplier purchase security')",
            (cylinder["id"], supplier_id),
        )
        self.conn.commit()

        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())

        supplier_events = self.conn.execute(
            "SELECT kind,qty,amount_paise,status FROM cylinder_deposits "
            "WHERE supplier_id=? ORDER BY id", (supplier_id,),
        ).fetchall()
        self.assertEqual(
            [(r["kind"], r["qty"], r["amount_paise"], r["status"]) for r in supplier_events],
            [("paid", 5, 250000, "active"), ("cancelled", 1, 50000, "active")],
        )

    def test_damaged_customer_return_cannot_overforfeit_supplier_deposit(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin) VALUES(?,?)",
            ("Go Gas Test", "22AAAAA0000A1Z5"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO supplier_items(supplier_id,cylinder_type_id,purchase_price_paise,security_paise,empty_qty) "
            "VALUES(?,?,?,?,0)", (supplier_id, cylinder["id"], 7000, 50000),
        )
        self.conn.commit()
        issued = self.sell(cylinder, customer, new_full=1)
        self.assertEqual(issued.status_code, 201, issued.get_json())

        before_full = self.conn.execute(
            "SELECT with_customers_qty,damaged_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)
        ).fetchone()
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 409, damaged.get_json())
        after_full = self.conn.execute(
            "SELECT with_customers_qty,damaged_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)
        ).fetchone()
        self.assertEqual(tuple(before_full), tuple(after_full))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM customer_deposit_events WHERE kind='forfeited'"
        ).fetchone()[0], 0)

    def test_missing_product_hsn_or_gst_blocks_final_invoice(self):
        result = self.client.post("/api/cylinders", json={
            "weight_kg": "7.7", "sale_price": "100", "full": "2", "empty": "0",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        cylinder = result.get_json()
        response = self.client.post("/api/sales", json={
            "date": date.today().isoformat(), "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "payment": "paid", "received_in": "cash",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("HSN", response.get_json()["error"])


    def test_nonzero_gst_requires_agency_gstin(self):
        cylinder = self.make_cylinder()
        self.assertEqual(self.client.put("/api/business", json={
            "name": "Test LPG Agency", "address": "1 Test Road, Durg", "state_code": "22",
            "invoice_prefix": "T",
        }).status_code, 200)
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.sell(cylinder, None, refill=1)
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertIn("GSTIN", response.get_json()["error"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], before)

    def test_reverse_charge_is_not_silently_treated_as_forward_charge(self):
        cylinder = self.make_cylinder()
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.client.post("/api/sales", json={
            "date": date.today().isoformat(), "place_state_code": "22", "reverse_charge": "yes",
            "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "payment": "paid", "received_in": "cash",
        })
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertIn("Reverse-charge", response.get_json()["error"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], before)

    def test_duplicate_cylinder_rows_are_rejected(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        before = self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0]
        payload = {
            "customer_id": customer["id"], "date": date.today().isoformat(), "place_state_code": "22",
            "payment": "paid", "received_in": "cash", "lines": [
                {"cylinder_type_id": cylinder["id"], "refill": 3, "rate": "100"},
                {"cylinder_type_id": cylinder["id"], "refill": 3, "rate": "100"},
            ], "items": [],
        }
        response = self.client.post("/api/sales", json=payload)
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0], before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)

    def test_zero_security_still_tracks_issued_cylinder_for_damage_return(self):
        cylinder = self.client.post("/api/cylinders", json={
            "weight_kg": "7.7", "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": "0", "full": "2", "empty": "0",
            "hsn": "27111910", "gst_rate": "18",
        }).get_json()
        customer = self.make_customer()
        issued = self.sell(cylinder, customer, new_full=1, security="0")
        self.assertEqual(issued.status_code, 201, issued.get_json())
        damaged = self.sell(cylinder, customer, damaged_in=1)
        self.assertEqual(damaged.status_code, 201, damaged.get_json())
        events = self.conn.execute(
            "SELECT kind,qty,amount_paise FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([(e["kind"], e["qty"], e["amount_paise"]) for e in events],
                         [("received", 1, 0), ("forfeited", 1, 0)])

    def test_paid_invoice_cannot_be_cancelled_without_refund_workflow(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.sell(cylinder, customer, refill=1)
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
        before = self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0]
        cancelled = self.client.post(f"/api/sales/{sale_id}/cancel", json={})
        self.assertEqual(cancelled.status_code, 409, cancelled.get_json())
        self.assertEqual(self.conn.execute("SELECT full_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()[0], before)

    def test_unpaid_credit_invoice_can_be_cancelled_and_restores_stock(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        response = self.client.post("/api/sales", json={
            "customer_id": customer["id"], "date": date.today().isoformat(), "place_state_code": "22",
            "lines": [{"cylinder_type_id": cylinder["id"], "refill": 1, "rate": "100"}],
            "items": [], "discount": "0", "payment": "credit", "received_in": "cash", "paid": "0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        sale_id = response.get_json()["id"]
        before = self.conn.execute("SELECT full_qty,empty_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()
        self.assertEqual((before["full_qty"], before["empty_qty"]), (4, 3))
        cancelled = self.client.post(f"/api/sales/{sale_id}/cancel", json={})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        after = self.conn.execute("SELECT full_qty,empty_qty FROM cylinder_types WHERE id=?", (cylinder["id"],)).fetchone()
        self.assertEqual((after["full_qty"], after["empty_qty"]), (5, 2))
        self.assertEqual(self.conn.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()[0], "cancelled")

    def test_failed_stock_validation_does_not_create_invoice(self):
        cylinder = self.make_cylinder()
        customer = self.make_customer()
        before = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        response = self.sell(cylinder, customer, refill=99)
        self.assertEqual(response.status_code, 409)
        after = self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()