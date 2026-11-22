"""v0.4.2: Stock & Price screen backend."""
import importlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class StockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.tmp.name
        os.environ["AGNI_DB"] = os.path.join(self.tmp.name, "stock.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        db.init_db()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def cyl(self, kg):
        return next(c for c in self.api("get", "/api/stock")[1]["cylinders"] if c["kg"] == kg)

    def test_overview_shape(self):
        code, d = self.api("get", "/api/stock")
        self.assertEqual(code, 200)
        self.assertEqual(set(d), {"summary", "cylinders", "items"})
        self.assertIn("stock_cost", d["summary"])

    def test_add_cylinder_with_starting_stock_makes_a_lot_and_history(self):
        code, c = self.api("post", "/api/cylinders", {
            "weight_kg": "19", "sale_price": "2000", "wholesale_price": "1900", "purchase_price": "1700",
            "security": "2500", "full": "4", "empty": "2"})
        self.assertEqual(code, 201, c)
        self.assertEqual((c["full"], c["empty"], c["name"]), (4, 2, "19 kg"))
        self.assertEqual(c["stock_value"], "6800.00")
        self.assertEqual(self.api("post", "/api/cylinders", {"weight_kg": "19"})[0], 409)
        hist = self.api("get", "/api/stock/history?limit=5")[1]
        self.assertTrue(any("19 kg" in h["title"] for h in hist))

    def test_prices_do_not_touch_lots(self):
        _, c = self.api("post", "/api/cylinders", {"weight_kg": "19", "purchase_price": "1300", "full": "3"})
        code, c2 = self.api("put", f"/api/cylinders/{c['id']}/prices", {
            "sale_price": "1500", "wholesale_price": "1450", "purchase_price": "1400", "security": "2000"})
        self.assertEqual(code, 200)
        self.assertEqual(c2["purchase_price"], "1400.00")
        self.assertEqual(c2["stock_value"], "3900.00")      # still 3 x 1300

    def test_adjust_cylinder_up_and_down(self):
        _, c = self.api("post", "/api/cylinders", {"weight_kg": "19", "purchase_price": "1300", "full": "3"})
        _, c = self.api("post", f"/api/cylinders/{c['id']}/adjust", {"full": "5", "empty": "1", "note": "counted"})
        self.assertEqual((c["full"], c["empty"]), (5, 1))
        _, c = self.api("post", f"/api/cylinders/{c['id']}/adjust", {"full": "2", "empty": "1"})
        self.assertEqual(c["full"], 2)
        left = self.conn.execute("SELECT COALESCE(SUM(qty_left),0) FROM stock_lots WHERE cylinder_type_id=?", (c["id"],)).fetchone()[0]
        self.assertEqual(left, 2)

    def test_delete_cylinder_rules(self):
        _, c = self.api("post", "/api/cylinders", {"weight_kg": "19", "full": "1"})
        self.assertEqual(self.api("delete", f"/api/cylinders/{c['id']}")[0], 409)
        self.api("post", f"/api/cylinders/{c['id']}/adjust", {"full": "0", "empty": "0"})
        self.assertEqual(self.api("delete", f"/api/cylinders/{c['id']}")[0], 200)

    def test_item_wholesale_price_round_trip(self):
        code, it = self.api("post", "/api/items", {
            "name": "Gas pipe", "unit": "m", "qty": "10", "sale_price": "120", "wholesale_price": "100", "purchase_price": "80"})
        self.assertEqual(code, 201, it)
        self.assertEqual(it["wholesale_price"], "100.00")
        self.assertEqual(it["stock_value"], "800.00")
        self.assertEqual(self.api("post", "/api/items", {"name": "gas PIPE"})[0], 409)
        _, it = self.api("put", f"/api/items/{it['id']}/prices", {"sale_price": "130", "wholesale_price": "105", "purchase_price": "85"})
        self.assertEqual((it["sale_price"], it["wholesale_price"]), ("130.00", "105.00"))

    def test_item_adjust_history_and_delete(self):
        _, it = self.api("post", "/api/items", {"name": "Regulator", "qty": "3"})
        _, it = self.api("post", f"/api/items/{it['id']}/adjust", {"qty": "1.5", "note": "broke 1.5"})
        self.assertEqual(it["qty"], "1.5")
        self.assertTrue(it["low"])
        hist = self.api("get", "/api/stock/history")[1]
        self.assertTrue(any("Regulator" in h["title"] for h in hist))
        self.assertEqual(self.api("delete", f"/api/items/{it['id']}")[0], 409)
        self.api("post", f"/api/items/{it['id']}/adjust", {"qty": "0"})
        self.assertEqual(self.api("delete", f"/api/items/{it['id']}")[0], 200)

    def test_damaged_counts(self):
        c = self.cyl(11.8)
        code, _ = self.api("put", "/api/stock/damaged", {"counts": {str(c["id"]): "2"}})
        self.assertEqual(code, 200)
        self.assertEqual(self.cyl(11.8)["damaged"], 2)

    def test_history_limit_and_filter(self):
        _, c = self.api("post", "/api/cylinders", {"weight_kg": "19", "full": "1"})
        self.api("post", "/api/items", {"name": "Pipe", "qty": "1"})
        self.assertEqual(len(self.api("get", "/api/stock/history?limit=1")[1]), 2)   # limit + 1 to detect "more"
        only = self.api("get", f"/api/stock/history?cylinder_type_id={c['id']}")[1]
        self.assertTrue(all("19 kg" in h["title"] for h in only))


if __name__ == "__main__":
    unittest.main()
