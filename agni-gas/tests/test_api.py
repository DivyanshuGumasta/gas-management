import importlib
import os
import sys
import tempfile
import unittest

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
        self.assertEqual(to_paise(0.1) + to_paise(0.2), 30)       # no float drift
        self.assertEqual(to_paise("10.005"), 1001)                # rounds half up
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
        self.assertEqual(d["today"]["sales"], "5550.00")      # tiku 4100 + harry 1450
        self.assertEqual(d["today"]["payments"], "5050.00")   # 4100 + 950 paid
        self.assertEqual(d["today"]["udhaar_amount"], "500.00")
        self.assertEqual(d["today"]["udhaar_customers"], 1)
        self.assertEqual(d["last7_total"], "7000.00")         # + yesterday's walk-in 1450
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

    def test_suppliers(self):
        rows = self.client.get("/api/suppliers").get_json()
        self.assertEqual(rows[0]["balance"], "25000.00")

    def test_pages(self):
        for url in ["/", "/sales", "/sales/new", "/sales/5", "/customers", "/udhaar", "/purchases",
                    "/purchases/new", "/suppliers", "/stock", "/reports", "/data", "/help"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()
