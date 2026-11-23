"""Standalone safety tests for additive SQLite backup restore."""
import os
import sqlite3
import tempfile
import unittest

from restore_merge import RestoreMergeError, merge_snapshot_into_database


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE counters(name TEXT PRIMARY KEY, value INTEGER);
CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE cylinder_types(id INTEGER PRIMARY KEY, name TEXT NOT NULL, full_qty INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sales(id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer_id INTEGER REFERENCES customers(id), total_paise INTEGER NOT NULL);
CREATE TABLE payments(id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer_id INTEGER REFERENCES customers(id), amount_paise INTEGER NOT NULL);
CREATE TABLE purchases(id INTEGER PRIMARY KEY, number TEXT UNIQUE, supplier_id INTEGER REFERENCES suppliers(id), total_paise INTEGER NOT NULL);
CREATE TABLE purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER REFERENCES purchases(id), cylinder_type_id INTEGER REFERENCES cylinder_types(id), qty INTEGER NOT NULL);
CREATE TABLE customer_prices(customer_id INTEGER REFERENCES customers(id), cylinder_type_id INTEGER REFERENCES cylinder_types(id), price_paise INTEGER NOT NULL, PRIMARY KEY(customer_id,cylinder_type_id));
"""


class BackupMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.target = sqlite3.connect(":memory:")
        self.target.row_factory = sqlite3.Row
        self.target.executescript(SCHEMA)
        self.target.executemany("INSERT INTO settings(key,value) VALUES(?,?)", [
            ("business.name", "Current agency"),
            ("backup.directory", "/current/backups"),
        ])
        self.target.executemany("INSERT INTO counters(name,value) VALUES(?,?)", [
            ("sale", 1), ("payment", 1),
        ])
        self.target.execute("INSERT INTO customers(id,name) VALUES(1,'Customer A')")
        self.target.execute("INSERT INTO suppliers(id,name) VALUES(1,'Supplier A')")
        self.target.execute("INSERT INTO cylinder_types(id,name,full_qty) VALUES(1,'14.2 kg',10)")
        self.target.execute("INSERT INTO sales(id,number,customer_id,total_paise) VALUES(1,'S-00001',1,10000)")
        self.target.execute("INSERT INTO payments(id,number,customer_id,amount_paise) VALUES(1,'R-00001',1,2000)")
        self.target.execute("INSERT INTO purchases(id,number,supplier_id,total_paise) VALUES(1,'P-00001',1,30000)")
        self.target.execute("INSERT INTO purchase_items(id,purchase_id,cylinder_type_id,qty) VALUES(1,1,1,2)")
        self.target.execute("INSERT INTO customer_prices(customer_id,cylinder_type_id,price_paise) VALUES(1,1,9500)")
        self.target.commit()

    def tearDown(self):
        self.target.close()
        self.temp.cleanup()

    def make_backup(self, extra=True, divergent=False):
        path = os.path.join(self.temp.name, "backup.db")
        source = sqlite3.connect(path)
        source.executescript(SCHEMA)
        source.executemany("INSERT INTO settings(key,value) VALUES(?,?)", [
            ("business.name", "Backup agency"),
            ("backup.directory", "/backup/old-path"),
            ("invoice.prefix", "AG"),
        ])
        source.executemany("INSERT INTO counters(name,value) VALUES(?,?)", [
            ("sale", 3), ("payment", 2), ("purchase", 2),
        ])
        source.execute("INSERT INTO customers(id,name) VALUES(1,'Customer A updated')")
        source.execute("INSERT INTO suppliers(id,name) VALUES(1,'Supplier A')")
        source.execute("INSERT INTO cylinder_types(id,name,full_qty) VALUES(1,'14.2 kg',7)")
        source.execute("INSERT INTO sales(id,number,customer_id,total_paise) VALUES(1,'S-00001',1,10000)")
        source.execute("INSERT INTO payments(id,number,customer_id,amount_paise) VALUES(1,'R-00001',1,2000)")
        source.execute("INSERT INTO purchases(id,number,supplier_id,total_paise) VALUES(1,'P-00001',1,30000)")
        source.execute("INSERT INTO purchase_items(id,purchase_id,cylinder_type_id,qty) VALUES(1,1,1,2)")
        source.execute("INSERT INTO customer_prices(customer_id,cylinder_type_id,price_paise) VALUES(1,1,9500)")
        if extra:
            source.execute("INSERT INTO customers(id,name) VALUES(2,'Customer B')")
            source.execute("INSERT INTO sales(id,number,customer_id,total_paise) VALUES(2,'S-00002',2,5000)")
            source.execute("INSERT INTO payments(id,number,customer_id,amount_paise) VALUES(2,'R-00002',2,1000)")
            source.execute("INSERT INTO purchases(id,number,supplier_id,total_paise) VALUES(2,'P-00002',1,40000)")
            source.execute("INSERT INTO purchase_items(id,purchase_id,cylinder_type_id,qty) VALUES(2,2,1,3)")
            source.execute("INSERT INTO customer_prices(customer_id,cylinder_type_id,price_paise) VALUES(2,1,9000)")
        if divergent:
            source.execute("INSERT INTO suppliers(id,name) VALUES(2,'Backup-only supplier')")
        source.commit()
        source.close()
        return path

    def test_newer_snapshot_fills_missing_rows_and_refreshes_existing_rows(self):
        path = self.make_backup(extra=True)
        result = merge_snapshot_into_database(self.target, path)
        self.assertEqual(result["status"], "merged")
        self.assertGreater(result["inserted"], 0)
        self.assertGreater(result["updated"], 0)
        self.assertEqual(self.target.execute("SELECT name FROM customers WHERE id=1").fetchone()[0], "Customer A updated")
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 2)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 2)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 2)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM purchase_items").fetchone()[0], 2)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM customer_prices").fetchone()[0], 2)
        self.assertEqual(self.target.execute("SELECT full_qty FROM cylinder_types WHERE id=1").fetchone()[0], 7)
        self.assertEqual(self.target.execute("SELECT value FROM counters WHERE name='sale'").fetchone()[0], 3)
        self.assertEqual(self.target.execute("SELECT value FROM settings WHERE key='backup.directory'").fetchone()[0], "/current/backups")
        self.assertEqual(self.target.execute("SELECT value FROM settings WHERE key='invoice.prefix'").fetchone()[0], "AG")
        self.assertEqual(self.target.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.target.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_restore_is_idempotent(self):
        path = self.make_backup(extra=True)
        first = merge_snapshot_into_database(self.target, path)
        second = merge_snapshot_into_database(self.target, path)
        self.assertEqual(first["status"], "merged")
        self.assertEqual(second["status"], "already_current")
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 2)

    def test_older_backup_does_not_overwrite_current_database(self):
        path = self.make_backup(extra=False)
        self.target.execute("UPDATE customers SET name='Locally updated customer' WHERE id=1")
        self.target.execute("INSERT INTO customers(id,name) VALUES(2,'Local-only customer')")
        self.target.commit()
        result = merge_snapshot_into_database(self.target, path)
        self.assertEqual(result["status"], "older_backup")
        self.assertEqual(self.target.execute("SELECT name FROM customers WHERE id=1").fetchone()[0], "Locally updated customer")
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 2)

    def test_divergent_copies_are_rejected_without_changes(self):
        self.target.execute("INSERT INTO customers(id,name) VALUES(3,'Local-only customer')")
        self.target.commit()
        path = self.make_backup(extra=True, divergent=True)
        before = self.target.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        with self.assertRaises(RestoreMergeError):
            merge_snapshot_into_database(self.target, path)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM customers").fetchone()[0], before)

    def test_backup_must_be_a_complete_agni_database(self):
        path = os.path.join(self.temp.name, "not-agni.db")
        other = sqlite3.connect(path)
        other.execute("CREATE TABLE customers(id INTEGER PRIMARY KEY)")
        other.commit()
        other.close()
        with self.assertRaises(RestoreMergeError):
            merge_snapshot_into_database(self.target, path)

    def test_backup_with_unsupported_extra_table_is_rejected(self):
        path = self.make_backup(extra=True)
        source = sqlite3.connect(path)
        source.execute("CREATE TABLE future_records(id INTEGER PRIMARY KEY, payload TEXT)")
        source.execute("INSERT INTO future_records(id,payload) VALUES(1,'newer schema data')")
        source.commit()
        source.close()
        with self.assertRaisesRegex(RestoreMergeError, "unsupported tables"):
            merge_snapshot_into_database(self.target, path)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
