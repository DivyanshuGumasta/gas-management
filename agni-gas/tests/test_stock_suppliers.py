"""v0.4.4: suppliers per cylinder, damaged cylinders, security deposits - everything per supplier."""
import importlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class StockSupplierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.tmp.name
        os.environ["AGNI_DB"] = os.path.join(self.tmp.name, "ss.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        db.init_db()
        self.conn = db.connect()
        self.conn.execute("INSERT INTO suppliers (name, gstin) VALUES ('Alpha', '22AAAAA0000A1Z5'), ('Beta', '22BBBBB0000B1Z5')")
        self.tid = self.conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]
        self.conn.execute("UPDATE cylinder_types SET full_qty=0, empty_qty=3, security_paise=250000, sale_price_paise=150000 WHERE id=?", (self.tid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def row(self):
        return self.conn.execute("SELECT * FROM cylinder_types WHERE id=?", (self.tid,)).fetchone()

    def sups(self):
        return {s["name"]: s for s in self.api("get", "/api/stock/extra")[1]["cylinders"][str(self.tid)]["suppliers"]}

    def two_suppliers(self):
        """4 x 5 kg from Alpha (1300, deposit 2500) and 5 x 5 kg from Beta (1350, deposit 3000)."""
        for sid, price, dep, qty in ((1, "1300", "2500", 4), (2, "1350", "3000", 5)):
            self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers",
                                      {"supplier_id": sid, "purchase_price": price, "security": dep})[0], 201)
            code, p = self.api("post", "/api/purchases", {"supplier_id": sid, "items": [
                {"cylinder_type_id": self.tid, "full_in": qty, "new_full": qty, "rate": price, "deposit": dep}]})
            self.assertEqual(code, 201, p)

    def test_each_supplier_has_own_price_deposit_and_stock(self):
        self.two_suppliers()
        s = self.sups()
        self.assertEqual((s["Alpha"]["price"], s["Alpha"]["security"], s["Alpha"]["full"], s["Alpha"]["margin"]),
                         ("1300.00", "2500.00", 4, "200.00"))
        self.assertEqual((s["Beta"]["price"], s["Beta"]["security"], s["Beta"]["full"], s["Beta"]["margin"]),
                         ("1350.00", "3000.00", 5, "150.00"))
        self.assertEqual((s["Alpha"]["deposit_held"], s["Beta"]["deposit_held"]), ("10000.00", "15000.00"))
        self.assertEqual(self.row()["full_qty"], 9)
        # the purchase form asks for each supplier's own deposit
        self.assertEqual(self.api("get", "/api/purchases/options?supplier_id=2")[1][0]["security_rate"], "3000.00")
        self.assertEqual(self.api("get", "/api/purchases/options?supplier_id=1")[1][0]["security_rate"], "2500.00")

    def test_change_price_and_deposit_for_one_supplier_only(self):
        self.two_suppliers()
        self.assertEqual(self.api("put", f"/api/cylinders/{self.tid}/suppliers/2", {"purchase_price": "1400", "security": "3200"})[0], 200)
        s = self.sups()
        self.assertEqual((s["Beta"]["price"], s["Beta"]["security"]), ("1400.00", "3200.00"))
        self.assertEqual((s["Alpha"]["price"], s["Alpha"]["security"]), ("1300.00", "2500.00"))
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/suppliers", {"supplier_id": 1})[0], 400)
        self.api("delete", f"/api/cylinders/{self.tid}/suppliers/1")
        self.assertEqual(list(self.sups()), ["Beta"])

    def test_purchase_tracks_supplier_empties(self):
        self.two_suppliers()
        self.api("post", "/api/purchases", {"supplier_id": 1, "items": [{"cylinder_type_id": self.tid, "full_in": 0, "new_empty": 2, "rate": "0", "deposit": "2500"}]})
        self.assertEqual(self.sups()["Alpha"]["empty"], 2)

    def test_adjust_one_supplier(self):
        self.two_suppliers()
        code, _ = self.api("post", f"/api/cylinders/{self.tid}/suppliers/1/adjust", {"full": "6", "empty": "1"})
        self.assertEqual(code, 200)
        s = self.sups()
        self.assertEqual((s["Alpha"]["full"], s["Alpha"]["empty"], s["Beta"]["full"]), (6, 1, 5))
        r = self.row()
        self.assertEqual((r["full_qty"], r["empty_qty"]), (11, 4))
        self.api("post", f"/api/cylinders/{self.tid}/suppliers/1/adjust", {"full": "1", "empty": "1"})
        self.assertEqual(self.sups()["Alpha"]["full"], 1)
        self.assertEqual(self.row()["full_qty"], 6)

    def test_damaged_empty_cancels_that_suppliers_deposit(self):
        self.two_suppliers()
        self.api("post", f"/api/cylinders/{self.tid}/suppliers/2/adjust", {"full": "5", "empty": "2"})
        code, _ = self.api("post", "/api/stock/damaged/add", {"source": "empty", "supplier_id": "2", "items": [{"cylinder_type_id": self.tid, "qty": "2"}]})
        self.assertEqual(code, 200)
        r = self.row()
        self.assertEqual((r["empty_qty"], r["damaged_qty"]), (3, 2))
        d = self.api("get", "/api/stock/extra")[1]
        self.assertEqual(d["deposits"]["cancelled"], "6000.00")        # Beta's own deposit (3000 x 2), not the size's
        self.assertEqual(self.sups()["Beta"]["empty"], 0)
        self.assertEqual(self.sups()["Beta"]["deposit_held"], "9000.00")
        self.assertEqual(self.api("post", "/api/stock/damaged/add", {"source": "empty", "items": [{"cylinder_type_id": self.tid, "qty": "9"}]})[0], 409)

    def test_damaged_full_takes_from_that_suppliers_lots(self):
        self.two_suppliers()
        self.api("post", "/api/stock/damaged/add", {"source": "full", "supplier_id": "2", "items": [{"cylinder_type_id": self.tid, "qty": "2", "deposit": "100"}]})
        s = self.sups()
        self.assertEqual((s["Alpha"]["full"], s["Beta"]["full"]), (4, 3))
        self.assertEqual(self.api("get", "/api/stock/extra")[1]["deposits"]["cancelled"], "200.00")

    def test_send_back_refunds_real_money_to_cash_or_bank(self):
        self.two_suppliers()
        code, _ = self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "2", "supplier_id": "2", "received_in": "bank"})
        self.assertEqual(code, 200)
        self.assertEqual(self.row()["empty_qty"], 1)
        dep = self.api("get", "/api/stock/extra")[1]["deposits"]
        self.assertEqual((dep["refunded"], dep["refunded_bank"], dep["refunded_cash"]), ("6000.00", "6000.00", "0.00"))
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "1", "received_in": "x"})[0], 400)
        self.assertEqual(self.api("post", f"/api/cylinders/{self.tid}/send-back", {"qty": "5"})[0], 409)

    def test_lots_remember_supplier(self):
        self.two_suppliers()
        rows = self.conn.execute("SELECT supplier_id, qty_left FROM stock_lots ORDER BY supplier_id").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [(1, 4), (2, 5)])


if __name__ == "__main__":
    unittest.main()