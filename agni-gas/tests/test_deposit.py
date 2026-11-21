"""v0.3.7: editable deposit, selling price on Add cylinder, new full cylinders."""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class DepositTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = cls.tmp.name
        os.environ["AGNI_DB"] = os.path.join(cls.tmp.name, "deposit.db")
        import app as app_module
        importlib.reload(app_module)
        cls.client = app_module.app.test_client()
        import db
        db.init_db()
        cls.db = db

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def make_supplier(self, name="Dep Supplier", gstin="22AAAAA0000A1Z5"):
        code, s = self.api("post", "/api/suppliers", {"name": name, "gstin": gstin})
        self.assertEqual(code, 201, s)
        return s["id"]

    def test_add_cylinder_with_deposit_and_sale_price(self):
        sid = self.make_supplier("S1")
        code, c = self.api("post", f"/api/suppliers/{sid}/items",
                           {"weight_kg": "5.5", "purchase_price": "1200", "deposit": "2800", "sale_price": "1600"})
        self.assertEqual(code, 201, c)
        self.assertEqual(c["security_price"], "2800.00")
        self.assertEqual(c["sale_price"], "1600.00")
        # blank fields keep what is saved
        code, c2 = self.api("put", f"/api/suppliers/{sid}/items/{c['cylinder_type_id']}",
                            {"weight_kg": "5.5", "purchase_price": "1250", "deposit": "", "sale_price": ""})
        self.assertEqual(code, 200, c2)
        self.assertEqual((c2["security_price"], c2["sale_price"], c2["purchase_price"]), ("2800.00", "1600.00", "1250.00"))
        # editing changes them
        code, c3 = self.api("put", f"/api/suppliers/{sid}/items/{c['cylinder_type_id']}",
                            {"weight_kg": "5.5", "purchase_price": "1250", "deposit": "3000", "sale_price": "1700"})
        self.assertEqual((c3["security_price"], c3["sale_price"]), ("3000.00", "1700.00"))

    def test_new_full_priced_at_rate_plus_deposit(self):
        sid = self.make_supplier("S2", "27BBBBB1111B1Z6")
        code, c = self.api("post", f"/api/suppliers/{sid}/items",
                           {"weight_kg": "19", "purchase_price": "1300", "deposit": "2500"})
        tid = c["cylinder_type_id"]
        # give the shop 2 empties to refill with
        conn = self.db.connect(); conn.execute("UPDATE cylinder_types SET empty_qty=2 WHERE id=?", (tid,)); conn.commit(); conn.close()
        # 1 refill + 2 new full (full_in 3), 1 new empty, 1 return (empty_out 2); deposit edited to 3000
        payload = {"supplier_id": sid, "date": "2026-11-22", "paid_amount": "0", "update_prices": True,
                   "items": [{"cylinder_type_id": tid, "full_in": 3, "new_full": 2, "empty_out": 2, "new_empty": 1,
                              "rate": "1300", "deposit": "3000"}]}
        code, p = self.api("post", "/api/purchases", payload)
        self.assertEqual(code, 201, p)
        # 3*1300 + (2+1)*3000 = 12900
        self.assertEqual(p["total"], "12900.00")
        code, d = self.api("get", f"/api/purchases/{p['id']}")
        line = d["items"][0]
        self.assertEqual((line["full_in"], line["new_full"], line["new_empty"], line["empty_out"]), (3, 2, 1, 2))
        self.assertEqual(line["security_rate"], "3000.00")
        conn = self.db.connect()
        row = conn.execute("SELECT full_qty, empty_qty, security_paise FROM cylinder_types WHERE id=?", (tid,)).fetchone()
        conn.close()
        # full +3, empty 2 - 2 + 1 = 1; "update prices" saved the new deposit
        self.assertEqual((row["full_qty"], row["empty_qty"], row["security_paise"]), (3, 1, 300000))

    def test_new_full_cannot_exceed_full_in(self):
        sid = self.make_supplier("S3", "29CCCCC2222C1Z7")
        code, c = self.api("post", f"/api/suppliers/{sid}/items", {"weight_kg": "7", "purchase_price": "900"})
        code, p = self.api("post", "/api/purchases", {"supplier_id": sid, "date": "2026-11-22", "paid_amount": "0",
            "items": [{"cylinder_type_id": c["cylinder_type_id"], "full_in": 1, "new_full": 2, "rate": "900"}]})
        self.assertEqual(code, 400, p)

    def test_old_requests_still_work(self):
        """No new_full / deposit sent: behaves exactly like v0.3.6 (saved deposit used)."""
        sid = self.make_supplier("S4", "30DDDDD3333D1Z8")
        code, c = self.api("post", f"/api/suppliers/{sid}/items", {"weight_kg": "9", "purchase_price": "1000", "deposit": "2000"})
        code, p = self.api("post", "/api/purchases", {"supplier_id": sid, "date": "2026-11-22", "paid_amount": "0",
            "items": [{"cylinder_type_id": c["cylinder_type_id"], "full_in": 1, "new_empty": 1, "rate": "1000"}]})
        self.assertEqual(code, 201, p)
        self.assertEqual(p["total"], "3000.00")

    def test_migration_adds_column_to_old_database(self):
        path = os.path.join(self.tmp.name, "old.db")
        self.db.init_db(path)
        con = sqlite3.connect(path)
        con.executescript("ALTER TABLE purchase_items RENAME TO pi_old;"
                          "CREATE TABLE purchase_items AS SELECT id,purchase_id,cylinder_type_id,full_in_qty,empty_out_qty,"
                          "new_empty_qty,rate_paise,security_rate_paise,amount_paise FROM pi_old;"
                          "DROP TABLE pi_old;")
        self.assertNotIn("new_full_qty", [r[1] for r in con.execute("PRAGMA table_info(purchase_items)")])
        con.commit(); con.close()
        self.db.init_db(path)
        con = sqlite3.connect(path)
        self.assertIn("new_full_qty", [r[1] for r in con.execute("PRAGMA table_info(purchase_items)")])
        con.close()


if __name__ == "__main__":
    unittest.main()
