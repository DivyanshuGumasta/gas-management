import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = cls.tmp.name
        os.environ["AGNI_DB"] = os.path.join(cls.tmp.name, "test.db")
        import app as app_module
        importlib.reload(app_module)
        cls.client = app_module.app.test_client()
        import db, seed_demo
        conn = db.connect()
        seed_demo.seed(conn)
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_money(self):
        from money import to_paise, to_rupees
        self.assertEqual(to_paise("1450.50"), 145050)
        self.assertEqual(to_paise("1,15,250"), 11525000)
        self.assertEqual(to_paise(0.1) + to_paise(0.2), 30)
        self.assertEqual(to_paise("10.005"), 1001)
        self.assertEqual(to_rupees(-175000), "-1750.00")
        with self.assertRaises(ValueError):
            to_paise("abc")

    def test_next_number_unique(self):
        import db
        conn = db.connect()
        a, b = db.next_number(conn, "test", "T"), db.next_number(conn, "test", "T")
        conn.rollback()
        self.assertEqual((a, b), ("T-00001", "T-00002"))

    def test_dashboard(self):
        d = self.client.get("/api/dashboard").get_json()
        self.assertEqual(d["today"]["sales"], "5550.00")
        self.assertEqual(d["today"]["payments"], "5050.00")
        self.assertEqual(d["today"]["udhaar_amount"], "500.00")
        self.assertEqual(d["today"]["udhaar_customers"], 1)
        self.assertEqual(d["last7_total"], "7000.00")
        self.assertEqual(len(d["last7"]), 7)
        self.assertEqual(d["stock"], {"full": 20, "empty": 3, "with_customers": 1, "total_customers": 3})
        self.assertEqual(d["recent"][0]["customer"], "harry")
        self.assertEqual(d["recent"][0]["status"], "pending")
        self.assertTrue(any(r["walk_in"] for r in d["recent"]))

    def test_customers(self):
        rows = {r["name"]: r for r in self.client.get("/api/customers").get_json()}
        self.assertEqual(rows["harry"]["balance"], "500.00")
        self.assertEqual(rows["karan"]["balance"], "-1750.00")
        self.assertEqual(rows["tiku"]["balance"], "0.00")
        self.assertEqual(len(self.client.get("/api/customers?q=ka").get_json()), 1)
        self.assertEqual(len(self.client.get("/api/customers?owing=1").get_json()), 1)

    def test_supplier_purchase_workflow(self):
        invalid_amount = self.client.post("/api/suppliers", json={
            "name": "Invalid Amount Supplier", "gstin": "22AABCD1234E1Z5",
            "opening_type": "payable", "opening_amount": "NaN",
        })
        self.assertEqual(invalid_amount.status_code, 400)

        # Add a supplier with an opening payable balance.
        response = self.client.post("/api/suppliers", json={
            "name": "Test Supplier V032", "gstin": "22AABCD1234E1Z5",
            "phone": "9876543210", "address": "Durg", "opening_type": "payable",
            "opening_amount": "500", "note": "workflow test",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        supplier = response.get_json()
        sid = supplier["id"]
        self.assertEqual(supplier["balance"], "500.00")

        # A supplier starts with no cylinder sizes linked. Link only the sizes it offers.
        import db
        conn = db.connect()
        cylinder_id = conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]
        second_cylinder_id = conn.execute("SELECT id FROM cylinder_types WHERE name='11.8 kg'").fetchone()[0]
        conn.close()
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}/items").get_json(), [])
        self.assertEqual(self.client.get(f"/api/purchases/options?supplier_id={sid}").get_json(), [])

        linked = self.client.post(f"/api/suppliers/{sid}/items", json={
            "weight_kg": "5", "purchase_price": "1300",
        })
        self.assertEqual(linked.status_code, 201, linked.get_json())
        linked_second = self.client.post(f"/api/suppliers/{sid}/items", json={
            "weight_kg": "11.8", "purchase_price": "2950",
        })
        self.assertEqual(linked_second.status_code, 201, linked_second.get_json())
        available = self.client.get(f"/api/suppliers/{sid}/available-cylinders").get_json()
        self.assertNotIn(cylinder_id, [row["cylinder_type_id"] for row in available])
        self.assertNotIn(second_cylinder_id, [row["cylinder_type_id"] for row in available])

        # Suppliers can introduce non-standard decimal weights and later change them.
        custom_weight = self.client.post(f"/api/suppliers/{sid}/items", json={
            "weight_kg": "5.4", "purchase_price": "1410",
        })
        self.assertEqual(custom_weight.status_code, 201, custom_weight.get_json())
        custom_row = custom_weight.get_json()
        self.assertEqual(custom_row["weight_kg"], 5.4)
        self.assertEqual(custom_row["name"], "5.4 kg")
        changed_weight = self.client.put(f"/api/suppliers/{sid}/items/{custom_row['cylinder_type_id']}", json={
            "weight_kg": "5.5", "purchase_price": "1420",
        })
        self.assertEqual(changed_weight.status_code, 200, changed_weight.get_json())
        self.assertEqual(changed_weight.get_json()["weight_kg"], 5.5)
        self.assertEqual(changed_weight.get_json()["name"], "5.5 kg")
        self.assertEqual(self.client.delete(f"/api/suppliers/{sid}/items/{changed_weight.get_json()['cylinder_type_id']}").status_code, 200)

        # Supplier rates can be edited independently; cylinder sizes can be unlinked.
        updated_rate = self.client.put(f"/api/suppliers/{sid}/items/{second_cylinder_id}", json={
            "weight_kg": "11.8", "purchase_price": "2990",
        })
        self.assertEqual(updated_rate.status_code, 200)
        self.assertEqual(updated_rate.get_json()["purchase_price"], "2990.00")
        self.assertEqual(self.client.delete(f"/api/suppliers/{sid}/items/{second_cylinder_id}").status_code, 200)
        supplier_cylinders = self.client.get(f"/api/suppliers/{sid}/items").get_json()
        self.assertEqual([row["cylinder_type_id"] for row in supplier_cylinders], [cylinder_id])

        options = self.client.get(f"/api/purchases/options?supplier_id={sid}").get_json()
        self.assertEqual([row["id"] for row in options], [cylinder_id])
        cylinder = options[0]
        self.assertEqual(cylinder["empty_stock"], 1)

        # Invalid GST input is rejected rather than producing a server error.
        invalid_gst = self.client.post("/api/purchases", json={
            "supplier_id": sid, "date": date.today().isoformat(), "gst_percent": "NaN",
            "items": [{"cylinder_type_id": cylinder_id, "full_in": 1, "rate": "1300"}],
        })
        self.assertEqual(invalid_gst.status_code, 400)

        # Record 2 full cylinders, return 1 empty, buy 1 new empty and pay part of the invoice.
        # The supplier invoice may not have arrived yet, so save the purchase without an attachment.
        payload = {
            "supplier_id": sid, "date": date.today().isoformat(), "gst_percent": "18",
            "paid_amount": "2000", "paid_from": "cash", "update_prices": True,
            "note": "Test incoming stock",
            "items": [{"cylinder_type_id": cylinder_id, "full_in": 2, "empty_out": 1,
                       "new_empty": 1, "rate": "1300"}],
        }
        response = self.client.post("/api/purchases", json=payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        purchase = response.get_json()
        pid = purchase["id"]
        self.assertRegex(purchase["number"], r"^P-\d{5}$")
        self.assertEqual(purchase["subtotal"], "5100.00")  # 2 x 1300 + 1 x 2500 security
        self.assertEqual(purchase["gst"], "918.00")
        self.assertEqual(purchase["total"], "6018.00")
        self.assertEqual(purchase["paid"], "2000.00")
        self.assertEqual(purchase["due"], "4018.00")
        self.assertFalse(purchase["has_attachment"])

        # The supplier account includes opening payable + purchase - initial payment.
        supplier = self.client.get(f"/api/suppliers/{sid}").get_json()
        self.assertEqual(supplier["balance"], "4518.00")
        self.assertEqual(supplier["total_purchases"], "6018.00")
        self.assertEqual(supplier["total_paid"], "2000.00")

        detail = self.client.get(f"/api/purchases/{pid}").get_json()
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(detail["items"][0]["full_in"], 2)
        self.assertEqual(detail["items"][0]["empty_out"], 1)
        self.assertEqual(detail["items"][0]["new_empty"], 1)
        self.assertEqual(len(detail["payments"]), 1)
        self.assertIsNone(detail["attachment_url"])

        # Attach the supplier's actual invoice after the purchase has already been registered.
        attached = self.client.post(f"/api/purchases/{pid}/attachment", data={
            "supplier_bill": (io.BytesIO(b"%PDF-1.4 supplier original invoice"), "supplier-original.pdf"),
        }, content_type="multipart/form-data")
        self.assertEqual(attached.status_code, 200, attached.get_json())
        detail = self.client.get(f"/api/purchases/{pid}").get_json()
        self.assertEqual(detail["attachment_mime"], "application/pdf")
        self.assertEqual(detail["attachment_name"], "supplier-original.pdf")
        attachment = self.client.get(detail["attachment_url"])
        self.assertEqual(attachment.status_code, 200)
        self.assertIn(b"%PDF", attachment.data)

        # A later scanned image can replace the PDF, and the actual image is served for preview.
        replaced = self.client.post(f"/api/purchases/{pid}/attachment", data={
            "supplier_bill": (io.BytesIO(b"fake png bytes for test"), "supplier-scan.png"),
        }, content_type="multipart/form-data")
        self.assertEqual(replaced.status_code, 200)
        detail = self.client.get(f"/api/purchases/{pid}").get_json()
        self.assertEqual(detail["attachment_mime"], "image/png")
        self.assertEqual(detail["attachment_name"], "supplier-scan.png")
        self.assertEqual(self.client.get(detail["attachment_url"]).mimetype, "image/png")
        self.assertEqual(self.client.delete(f"/api/purchases/{pid}/attachment").status_code, 200)
        self.assertIsNone(self.client.get(f"/api/purchases/{pid}").get_json()["attachment_url"])

        # Stock deltas are atomic with the saved purchase.
        import db
        conn = db.connect()
        stock = conn.execute("SELECT full_qty,empty_qty,purchase_price_paise FROM cylinder_types WHERE id=?", (cylinder_id,)).fetchone()
        self.assertEqual((stock["full_qty"], stock["empty_qty"], stock["purchase_price_paise"]), (5, 1, 130000))
        movement = conn.execute("SELECT full_delta,empty_delta FROM stock_movements WHERE ref_type='purchase' AND ref_id=?", (pid,)).fetchone()
        self.assertEqual((movement["full_delta"], movement["empty_delta"]), (2, 0))
        conn.close()

        # Updating purchase prices also creates the supplier-specific item rate.
        options = self.client.get(f"/api/purchases/options?supplier_id={sid}").get_json()
        self.assertEqual(next(x for x in options if x["id"] == cylinder_id)["rate"], "1300.00")
        supplier_items = self.client.get(f"/api/suppliers/{sid}/items").get_json()
        self.assertEqual(len(supplier_items), 1)
        self.assertEqual(supplier_items[0]["cylinder_type_id"], cylinder_id)
        self.assertEqual(supplier_items[0]["purchase_price"], "1300.00")

        # Unlinking stops future purchase options but never erases old purchase lines.
        self.assertEqual(self.client.delete(f"/api/suppliers/{sid}/items/{cylinder_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/purchases/options?supplier_id={sid}").get_json(), [])
        blocked = self.client.post("/api/purchases", json={
            "supplier_id": sid, "date": date.today().isoformat(),
            "items": [{"cylinder_type_id": cylinder_id, "full_in": 1, "rate": "1300"}],
        })
        self.assertEqual(blocked.status_code, 409)
        relinked = self.client.post(f"/api/suppliers/{sid}/items", json={
            "weight_kg": "5", "purchase_price": "1310",
        })
        self.assertEqual(relinked.status_code, 201)
        self.assertEqual(self.client.get(f"/api/purchases/{pid}").get_json()["items"][0]["full_in"], 2)

        # An allocated payment cannot exceed the remaining purchase balance.
        overpayment = self.client.post(f"/api/suppliers/{sid}/payments", json={
            "amount": "4018.01", "date": date.today().isoformat(), "paid_from": "bank", "purchase_id": pid,
        })
        self.assertEqual(overpayment.status_code, 409)

        # A payment allocated to the purchase settles that invoice; a general payment
        # then clears the opening payable balance. Cancelling a payment restores it.
        response = self.client.post(f"/api/suppliers/{sid}/payments", json={
            "amount": "4018", "date": date.today().isoformat(), "paid_from": "bank", "purchase_id": pid,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.client.get(f"/api/purchases/{pid}").get_json()["due"], "0.00")
        reversed_dates = self.client.get("/api/purchases?from=2026-11-22&to=2026-11-21")
        self.assertEqual(reversed_dates.status_code, 400)
        response = self.client.post(f"/api/suppliers/{sid}/payments", json={
            "amount": "500", "date": date.today().isoformat(), "paid_from": "cash",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], "0.00")
        payment_id = response.get_json()["id"]
        self.assertEqual(self.client.post(f"/api/supplier-payments/{payment_id}/cancel").status_code, 200)
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], "500.00")

        # A final payment settles the account; archive retains the records.
        self.assertEqual(self.client.post(f"/api/suppliers/{sid}/payments", json={
            "amount": "500", "date": date.today().isoformat(), "paid_from": "cash",
        }).status_code, 201)
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], "0.00")
        self.assertEqual(self.client.delete(f"/api/suppliers/{sid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/purchases/{pid}").status_code, 200)

    def test_catalog_items_and_other_goods_purchase(self):
        # General goods are catalogue records separate from cylinder_types.
        supplier_response = self.client.post("/api/suppliers", json={
            "name": "Accessory Supplier", "gstin": "22AACCD1234E1Z5",
            "opening_type": "payable", "opening_amount": "0",
        })
        self.assertEqual(supplier_response.status_code, 201, supplier_response.get_json())
        sid = supplier_response.get_json()["id"]

        # Items are entered directly from the supplier screen with buy and resale prices.
        created = self.client.post(f"/api/suppliers/{sid}/catalog-items", json={
            "name": "Regulator", "unit": "pcs", "purchase_price": "250", "sale_price": "400",
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        item = created.get_json()
        item_id = item["id"]
        self.assertGreater(item_id, 0)
        self.assertEqual((item["name"], item["unit"], item["purchase_price"], item["stock"]),
                         ("Regulator", "pcs", "250.00", "0"))
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}/catalog-items").get_json()[0]["id"], item_id)
        self.assertEqual(self.client.get(f"/api/purchases/catalog-options?supplier_id={sid}").get_json()[0]["rate"], "250.00")

        # Editing updates item details and this supplier's own purchase rate.
        duplicate = self.client.post(f"/api/suppliers/{sid}/catalog-items", json={
            "name": "Regulator", "unit": "pcs", "purchase_price": "250", "sale_price": "400",
        })
        self.assertEqual(duplicate.status_code, 201)
        self.assertEqual(duplicate.get_json()["id"], item_id)

        # Purchase an ordinary item without any cylinder line. Quantity is stored to 3 dp;
        # rate and amount are exact paise, and its item name/unit are snapshotted.
        purchase = self.client.post("/api/purchases", json={
            "supplier_id": sid, "date": date.today().isoformat(), "gst_percent": "18",
            "paid_amount": "200", "update_prices": True,
            "catalog_items": [{"item_id": item_id, "quantity": "2", "rate": "250"}],
        })
        self.assertEqual(purchase.status_code, 201, purchase.get_json())
        purchase_id = purchase.get_json()["id"]
        self.assertEqual(purchase.get_json()["subtotal"], "500.00")
        self.assertEqual(purchase.get_json()["gst"], "90.00")
        self.assertEqual(purchase.get_json()["total"], "590.00")
        self.assertEqual(purchase.get_json()["paid"], "200.00")
        self.assertEqual(purchase.get_json()["items_summary"], "2 Regulator")

        detail = self.client.get(f"/api/purchases/{purchase_id}").get_json()
        self.assertEqual(detail["items"], [])
        self.assertEqual(detail["catalog_items"], [{
            "item_id": item_id, "name": "Regulator", "unit": "pcs", "quantity": "2",
            "rate": "250.00", "amount": "500.00",
        }])
        supplier = self.client.get(f"/api/suppliers/{sid}").get_json()
        self.assertEqual(supplier["balance"], "390.00")
        ledger = self.client.get(f"/api/suppliers/{sid}/ledger").get_json()
        self.assertIn("2 Regulator", ledger["rows"][1]["sub"])

        import db
        conn = db.connect()
        stock = conn.execute("SELECT stock_qty_milli FROM catalog_items WHERE id=?", (item_id,)).fetchone()[0]
        movement = conn.execute("SELECT quantity_delta_milli FROM catalog_stock_movements WHERE purchase_id=?", (purchase_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(stock, 2000)
        self.assertEqual(movement, 2000)

        # Editing the catalogue item does not rewrite the historical purchase line.
        updated = self.client.put(f"/api/suppliers/{sid}/catalog-items/{item_id}", json={
            "name": "Regulator", "unit": "pcs", "purchase_price": "275", "sale_price": "450",
        })
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["name"], "Regulator")
        self.assertEqual(updated.get_json()["purchase_price"], "275.00")
        master_item = next(row for row in self.client.get("/api/items").get_json() if row["id"] == item_id)
        self.assertEqual(master_item["purchase_price"], "250.00")
        self.assertEqual(master_item["sale_price"], "450.00")
        self.assertEqual(self.client.get(f"/api/purchases/{purchase_id}").get_json()["catalog_items"][0]["name"], "Regulator")

        # An item may be attached to a second supplier without duplicating the master record.
        second = self.client.post("/api/suppliers", json={
            "name": "Second Accessory Supplier", "gstin": "22AAEED1234E1Z5",
        }).get_json()
        attached = self.client.post(f"/api/suppliers/{second['id']}/catalog-items", json={
            "name": "Regulator", "unit": "pcs", "purchase_price": "270", "sale_price": "450",
        })
        self.assertEqual(attached.status_code, 201, attached.get_json())
        self.assertEqual(attached.get_json()["purchase_price"], "270.00")

        removed = self.client.delete(f"/api/suppliers/{sid}/catalog-items/{item_id}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get(f"/api/purchases/catalog-options?supplier_id={sid}").get_json(), [])
        blocked_purchase = self.client.post("/api/purchases", json={
            "supplier_id": sid,
            "catalog_items": [{"item_id": item_id, "quantity": "1", "rate": "250"}],
        })
        self.assertEqual(blocked_purchase.status_code, 409)
        self.assertEqual(len(self.client.get(f"/api/suppliers/{second['id']}/catalog-items").get_json()), 1)
        self.assertEqual(self.client.get(f"/api/purchases/{purchase_id}").status_code, 200)

        invalid_quantity = self.client.post("/api/purchases", json={
            "supplier_id": second["id"], "catalog_items": [{"item_id": item_id, "quantity": "NaN", "rate": "270"}],
        })
        self.assertEqual(invalid_quantity.status_code, 400)

    def test_purchase_options_only_show_supplier_links(self):
        supplier = self.client.post("/api/suppliers", json={
            "name": "No Linked Cylinders", "gstin": "27AABCD1234E1Z5",
        })
        self.assertEqual(supplier.status_code, 201, supplier.get_json())
        sid = supplier.get_json()["id"]
        self.assertEqual(self.client.get("/api/purchases/options").get_json(), [])
        self.assertEqual(self.client.get(f"/api/purchases/options?supplier_id={sid}").get_json(), [])
        import db
        conn = db.connect()
        cylinder_id = conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]
        conn.close()
        response = self.client.post("/api/purchases", json={
            "supplier_id": sid, "date": date.today().isoformat(),
            "items": [{"cylinder_type_id": cylinder_id, "full_in": 1, "rate": "1300"}],
        })
        self.assertEqual(response.status_code, 409)

    def test_damaged_cylinder_dispatch_does_not_refund_or_change_supplier_account(self):
        supplier_response = self.client.post("/api/suppliers", json={
            "name": "Damaged Dispatch Test Supplier",
            "gstin": "27ZZZZZ1234A1Z5",
            "opening_type": "payable",
            "opening_amount": "0",
        })
        self.assertEqual(supplier_response.status_code, 201, supplier_response.get_json())
        sid = supplier_response.get_json()["id"]

        cylinder_response = self.client.post("/api/cylinders", json={
            "weight_kg": "88.8",
            "purchase_price": "1000",
            "security": "125",
            "full": "0",
            "empty": "2",
        })
        self.assertEqual(cylinder_response.status_code, 201, cylinder_response.get_json())
        tid = cylinder_response.get_json()["id"]

        linked = self.client.post(f"/api/cylinders/{tid}/suppliers", json={
            "supplier_id": sid,
            "purchase_price": "1000",
            "security": "125",
        })
        self.assertEqual(linked.status_code, 201, linked.get_json())

        damaged = self.client.post("/api/stock/damaged/add", json={
            "source": "empty",
            "supplier_id": sid,
            "items": [{"cylinder_type_id": tid, "qty": "2", "deposit": "125"}],
        })
        self.assertEqual(damaged.status_code, 200, damaged.get_json())

        before_extra = self.client.get("/api/stock/extra").get_json()
        before_deposits = dict(before_extra["deposits"])
        before_supplier_balance = self.client.get(f"/api/suppliers/{sid}").get_json()["balance"]
        option = next(x for x in before_extra["damaged_dispatch_options"] if x["cylinder_type_id"] == tid)
        self.assertEqual(option["remaining_qty"], 2)
        self.assertEqual(option["supplier_id"], sid)
        self.assertEqual(option["deposit_reference"], "125.00")

        first_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "note": "First partial dispatch",
            "items": [{
                "damage_event_id": option["damage_event_id"],
                "qty": "1",
                "supplier_id": str(sid),
                "deposit_reference": "150",
            }],
        })
        self.assertEqual(first_dispatch.status_code, 200, first_dispatch.get_json())

        after_extra = self.client.get("/api/stock/extra").get_json()
        remaining = next(x for x in after_extra["damaged_dispatch_options"] if x["damage_event_id"] == option["damage_event_id"])
        self.assertEqual(remaining["remaining_qty"], 1)
        self.assertEqual(next(x for x in after_extra["damaged"] if x["cylinder_type_id"] == tid)["qty"], 1)
        self.assertEqual(after_extra["deposits"], before_deposits)
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], before_supplier_balance)

        import db
        conn = db.connect()
        cancelled = conn.execute(
            "SELECT COUNT(*), SUM(amount_paise) FROM cylinder_deposits "
            "WHERE cylinder_type_id=? AND kind='cancelled'", (tid,)
        ).fetchone()
        dispatch_reference = conn.execute(
            "SELECT deposit_reference_paise FROM damaged_cylinder_dispatch_items WHERE dispatch_id=?",
            (first_dispatch.get_json()["dispatch_id"],),
        ).fetchone()[0]
        damaged_qty = conn.execute("SELECT damaged_qty FROM cylinder_types WHERE id=?", (tid,)).fetchone()[0]
        conn.close()
        self.assertEqual((cancelled[0], cancelled[1]), (1, 25000))
        self.assertEqual(dispatch_reference, 15000)  # reference snapshot only
        self.assertEqual(damaged_qty, 1)

        second_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "items": [{
                "damage_event_id": option["damage_event_id"],
                "qty": "1",
                "supplier_id": str(sid),
                "deposit_reference": "125",
            }],
        })
        self.assertEqual(second_dispatch.status_code, 200, second_dispatch.get_json())
        self.assertFalse(any(x["cylinder_type_id"] == tid for x in self.client.get("/api/stock/extra").get_json()["damaged_dispatch_options"]))
        self.assertEqual(self.client.get(f"/api/suppliers/{sid}").get_json()["balance"], before_supplier_balance)

        over_dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "items": [{"damage_event_id": option["damage_event_id"], "qty": "1", "supplier_id": str(sid)}],
        })
        self.assertEqual(over_dispatch.status_code, 409)

        history = self.client.get(f"/api/stock/history?cylinder_type_id={tid}").get_json()
        self.assertTrue(any("Damaged cylinders sent back" in row["title"] for row in history))
        self.assertEqual(self.client.get("/api/stock/extra").get_json()["deposits"], before_deposits)

    def test_sole_supplier_auto_link_helpers(self):
        import sqlite3
        from db import (sole_active_supplier_id, link_all_stock_to_supplier,
                        link_new_cylinder_to_sole_supplier, link_new_item_to_sole_supplier)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE suppliers(id INTEGER PRIMARY KEY, active INTEGER NOT NULL);
            CREATE TABLE cylinder_types(
                id INTEGER PRIMARY KEY, active INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, security_paise INTEGER NOT NULL
            );
            CREATE TABLE supplier_items(
                supplier_id INTEGER NOT NULL, cylinder_type_id INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, security_paise INTEGER,
                empty_qty INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(supplier_id,cylinder_type_id)
            );
            CREATE TABLE catalog_items(
                id INTEGER PRIMARY KEY, active INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL
            );
            CREATE TABLE supplier_catalog_items(
                supplier_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
                purchase_price_paise INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(supplier_id,item_id)
            );
            INSERT INTO suppliers(id,active) VALUES(1,1);
            INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise)
                VALUES(10,1,130000,250000),(11,1,295000,500000);
            INSERT INTO catalog_items(id,active,purchase_price_paise)
                VALUES(20,1,25000),(21,1,40000);
        """)
        self.assertEqual(sole_active_supplier_id(conn), 1)
        link_all_stock_to_supplier(conn, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_items WHERE supplier_id=1").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_catalog_items WHERE supplier_id=1 AND active=1").fetchone()[0], 2)

        conn.execute("INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise) VALUES(12,1,50000,100000)")
        conn.execute("INSERT INTO catalog_items(id,active,purchase_price_paise) VALUES(22,1,7000)")
        link_new_cylinder_to_sole_supplier(conn, 12)
        link_new_item_to_sole_supplier(conn, 22)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM supplier_items WHERE supplier_id=1 AND cylinder_type_id=12").fetchone())
        self.assertIsNotNone(conn.execute("SELECT 1 FROM supplier_catalog_items WHERE supplier_id=1 AND item_id=22 AND active=1").fetchone())

        conn.execute("INSERT INTO suppliers(id,active) VALUES(2,1)")
        self.assertIsNone(sole_active_supplier_id(conn))
        conn.execute("INSERT INTO cylinder_types(id,active,purchase_price_paise,security_paise) VALUES(13,1,60000,120000)")
        conn.execute("INSERT INTO catalog_items(id,active,purchase_price_paise) VALUES(23,1,9000)")
        link_new_cylinder_to_sole_supplier(conn, 13)
        link_new_item_to_sole_supplier(conn, 23)
        self.assertIsNone(conn.execute("SELECT 1 FROM supplier_items WHERE cylinder_type_id=13").fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM supplier_catalog_items WHERE item_id=23").fetchone())
        conn.close()

    def test_suppliers(self):
        rows = {row["name"]: row for row in self.client.get("/api/suppliers").get_json()}
        self.assertIn("goo goo", rows)
        self.assertEqual(rows["goo goo"]["balance"], "25000.00")

    def test_pages(self):
        for url in ["/", "/sales", "/sales/5", "/customers", "/customers/1",
                    "/suppliers-purchases", "/suppliers-purchases/supplier/1", "/purchases/new",
                    "/purchases/1", "/stock", "/reports", "/data", "/help"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/suppliers").status_code, 302)
        self.assertEqual(self.client.get("/purchases").status_code, 302)
        self.assertEqual(self.client.get("/udhaar").status_code, 302)
        self.assertEqual(self.client.get("/sales/new?customer=2").headers["Location"], "/sales?tab=new&customer=2")


if __name__ == "__main__":
    unittest.main()
