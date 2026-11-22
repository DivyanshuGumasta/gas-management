"""v0.4: FIFO stock lots (what was bought at which price, oldest sold first)."""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class LotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.tmp.name
        os.environ["AGNI_DB"] = os.path.join(self.tmp.name, "lots.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db, lots
        db.init_db()
        self.db, self.lots = db, lots
        self.conn = db.connect()
        self.tid = self.conn.execute("SELECT id FROM cylinder_types WHERE name='5 kg'").fetchone()[0]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def api(self, method, url, data=None):
        r = getattr(self.client, method)(url, json=data) if data is not None else getattr(self.client, method)(url)
        return r.status_code, r.get_json()

    def left(self):
        return [r[0] for r in self.conn.execute("SELECT qty_left FROM stock_lots ORDER BY id")]

    def test_oldest_goes_first_and_cost_is_exact(self):
        L = self.lots
        L.add_lot(self.conn, self.tid, 2, 130000, "2026-11-01")
        L.add_lot(self.conn, self.tid, 2, 140000, "2026-11-10")
        cost = L.consume_fifo(self.conn, self.tid, 3, "sale", 1)
        self.assertEqual(cost, 130000 * 2 + 140000)          # two at 1300, one at 1400
        self.assertEqual(self.left(), [0, 1])
        self.assertEqual(L.cost_of(self.conn, "sale", 1), cost)

    def test_price_change_does_not_touch_old_lots(self):
        """Bought at 1300, price becomes 1400: the 1300 cylinders still cost 1300."""
        L = self.lots
        L.add_lot(self.conn, self.tid, 2, 130000, "2026-11-01")
        self.conn.execute("UPDATE cylinder_types SET purchase_price_paise=140000 WHERE id=?", (self.tid,))
        L.add_lot(self.conn, self.tid, 2, 140000, "2026-11-10")
        self.assertEqual(L.consume_fifo(self.conn, self.tid, 2, "sale", 1), 260000)   # profit stays 200 each at 1500
        self.assertEqual(L.consume_fifo(self.conn, self.tid, 2, "sale", 2), 280000)

    def test_backdated_purchase_is_older(self):
        L = self.lots
        L.add_lot(self.conn, self.tid, 1, 140000, "2026-11-10")
        L.add_lot(self.conn, self.tid, 1, 130000, "2026-11-01")   # entered later, bought earlier
        self.assertEqual(L.consume_fifo(self.conn, self.tid, 1, "sale", 1), 130000)

    def test_cancel_restores_to_the_same_lots(self):
        L = self.lots
        L.add_lot(self.conn, self.tid, 2, 130000, "2026-11-01")
        L.add_lot(self.conn, self.tid, 2, 140000, "2026-11-10")
        L.consume_fifo(self.conn, self.tid, 3, "sale", 7)
        L.restore(self.conn, "sale", 7)
        self.assertEqual(self.left(), [2, 2])
        self.assertEqual(L.cost_of(self.conn, "sale", 7), 0)
        L.restore(self.conn, "sale", 7)                          # second time changes nothing
        self.assertEqual(self.left(), [2, 2])

    def test_short_lots_fall_back_to_latest_price(self):
        L = self.lots
        L.add_lot(self.conn, self.tid, 1, 130000, "2026-11-01")
        cost = L.consume_fifo(self.conn, self.tid, 2, "sale", 1)
        latest = self.conn.execute("SELECT purchase_price_paise FROM cylinder_types WHERE id=?", (self.tid,)).fetchone()[0]
        self.assertEqual(cost, 130000 + latest)
        self.assertEqual(self.left(), [0])

    def test_purchase_creates_lot_with_pid_and_rate(self):
        code, s = self.api("post", "/api/suppliers", {"name": "Lot Supplier", "gstin": "22AAAAA0000A1Z5"})
        sid = s["id"]
        code, c = self.api("post", f"/api/suppliers/{sid}/items", {"weight_kg": "5", "purchase_price": "1300"})
        tid = c["cylinder_type_id"]
        # 3 full in (1 refill + 2 new full) at 1300, then 2 more at 1400
        for qty, rate, day in ((3, "1300", "2026-11-01"), (2, "1400", "2026-11-10")):
            code, p = self.api("post", "/api/purchases", {"supplier_id": sid, "date": day, "paid_amount": "0",
                "items": [{"cylinder_type_id": tid, "full_in": qty, "new_full": 0, "rate": rate}]})
            self.assertEqual(code, 201, p)
        code, d = self.api("get", f"/api/stock-lots?cylinder_type_id={tid}")
        lots = d["lots"]
        self.assertEqual([(l["qty_in"], l["unit_cost"], l["purchase_number"]) for l in lots],
                         [(3, "1300.00", "P-00001"), (2, "1400.00", "P-00002")])
        self.assertEqual(d["stock_value"], "6700.00")        # 3*1300 + 2*1400
        self.assertEqual(lots[0]["supplier"], "Lot Supplier")
        # "update prices" moved the global price to 1400, but the first lot still says 1300
        code, d = self.api("get", f"/api/stock-lots?cylinder_type_id={tid}&open=1")
        self.assertEqual(d["lots"][0]["unit_cost"], "1300.00")

    def test_existing_stock_becomes_opening_lot_on_upgrade(self):
        path = os.path.join(self.tmp.name, "old.db")
        self.db.init_db(path)
        con = sqlite3.connect(path)
        con.execute("UPDATE cylinder_types SET full_qty=4 WHERE name='5 kg'")
        con.executescript("DROP TABLE lot_consumptions; DROP TABLE stock_lots;")   # a v0.3 database
        con.commit(); con.close()
        self.db.init_db(path)
        con = sqlite3.connect(path)
        rows = con.execute("SELECT source, qty_in, qty_left, unit_cost_paise FROM stock_lots").fetchall()
        con.close()
        self.assertEqual(rows, [("opening", 4, 4, 130000)])
        self.db.init_db(path)                                   # starting again must not add more
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM stock_lots").fetchone()[0], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()
