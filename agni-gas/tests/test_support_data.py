"""Tests for the Help & support and Data & Backup pages and endpoints."""
import importlib
import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest
from datetime import date

HAS_FLASK = importlib.util.find_spec("flask") is not None


@unittest.skipUnless(HAS_FLASK, "Flask is not installed in this test environment")
class SupportAndDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "support-data-test.db")

        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.db = db
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()
        os.environ.pop("AGNI_DATA_DIR", None)
        os.environ.pop("AGNI_DB", None)

    def add_sample_records(self):
        customer_id = self.conn.execute(
            "INSERT INTO customers(name,type) VALUES('Data Test Customer','retail')"
        ).lastrowid
        supplier_id = self.conn.execute(
            "INSERT INTO suppliers(name,gstin) VALUES('Data Test Supplier','22AAAAA0000A1Z5')"
        ).lastrowid
        self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,total_paise,paid_paise) VALUES(?,?,?,?,?)",
            ("DATA-S-001", customer_id, date.today().isoformat(), 10000, 5000),
        )
        self.conn.execute(
            "INSERT INTO payments(number,customer_id,amount_paise,payment_date) VALUES(?,?,?,?)",
            ("DATA-R-001", customer_id, 2500, date.today().isoformat()),
        )
        self.conn.execute(
            "INSERT INTO purchases(number,supplier_id,purchase_date,total_paise) VALUES(?,?,?,?)",
            ("DATA-P-001", supplier_id, date.today().isoformat(), 20000),
        )
        self.conn.commit()
        return customer_id, supplier_id

    def test_help_and_data_pages_render_real_page_shells(self):
        help_page = self.client.get("/help")
        self.assertEqual(help_page.status_code, 200)
        help_html = help_page.get_data(as_text=True)
        self.assertIn("Help &amp; support", help_html)
        self.assertIn("help-contacts", help_html)
        self.assertIn("js/help.js", help_html)
        self.assertNotIn("To be built", help_html)

        data_page = self.client.get("/data")
        self.assertEqual(data_page.status_code, 200)
        data_html = data_page.get_data(as_text=True)
        self.assertIn("Data &amp; Backup", data_html)
        self.assertIn("count-customers", data_html)
        self.assertIn("data-manual-backup", data_html)
        self.assertIn("Automatic backup settings", data_html)
        self.assertIn("Manual backup", data_html)
        self.assertIn("data-restore-button", data_html)
        self.assertIn("type=\"file\"", data_html)
        self.assertIn("js/data.js", data_html)
        self.assertNotIn("To be built", data_html)
        self.assertNotIn("Contact support to restore", data_html)

    def test_support_contacts_are_returned_for_email_and_call_actions(self):
        response = self.client.get("/api/support")
        self.assertEqual(response.status_code, 200, response.get_json())
        contacts = response.get_json()
        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[0], {
            "name": "Divyanshu Gumasta",
            "email": "divyanshugumasta4933@gmail.com",
            "phone": "+91 88174 12806",
        })
        self.assertEqual(contacts[1], {
            "name": "Harsh Das",
            "email": "harshdas2621@gmail.com",
            "phone": "62668 78903",
        })

    def test_data_summary_counts_all_six_record_types(self):
        self.add_sample_records()
        response = self.client.get("/api/data/summary")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["counts"], {
            "customers": 1,
            "sales": 1,
            "payments": 1,
            "purchases": 1,
            "suppliers": 1,
            "cylinder_types": 4,
        })
        self.assertEqual(payload["count_scope"], "all")
        self.assertTrue(payload["generated_at"])


    def test_backup_settings_can_be_saved_and_manual_backup_uses_selected_folder(self):
        folder = os.path.join(self.temp.name, "agency-backups")
        saved = self.client.put("/api/data/backup-settings", json={
            "frequency_value": 1,
            "frequency_unit": "hours",
            "retention_count": 2,
            "directory": folder,
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        settings = self.client.get("/api/data/backup-settings")
        self.assertEqual(settings.status_code, 200, settings.get_json())
        self.assertEqual(settings.get_json()["frequency_value"], 1)
        self.assertEqual(settings.get_json()["frequency_unit"], "hours")
        self.assertEqual(settings.get_json()["retention_count"], 2)
        self.assertEqual(settings.get_json()["directory"], folder)
        self.assertTrue(os.path.isdir(folder))

        manual = self.client.post("/api/data/backup", json={})
        self.assertEqual(manual.status_code, 201, manual.get_json())
        result = manual.get_json()
        self.assertTrue(result["filename"].startswith("agni-manual-"))
        manual_path = os.path.join(folder, result["filename"])
        self.assertTrue(os.path.isfile(manual_path))
        with sqlite3.connect(manual_path) as saved:
            self.assertEqual(saved.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
            self.assertEqual(saved.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        import time
        from backup import maybe_create_automatic_backup
        # The GET settings request above runs the request-time scheduler after
        # the new folder is saved, so it already creates the first due backup.
        # A second backup 60 seconds later must be suppressed for a 1-hour
        # interval; the next simulated runs are each more than an hour apart.
        future = time.time() + 60
        self.assertIsNone(
            maybe_create_automatic_backup(now=future),
            "a recent automatic backup must not be duplicated before its interval",
        )
        for index in range(1, 5):
            self.assertTrue(maybe_create_automatic_backup(now=future + index * 3601))
        automatic_files = [name for name in os.listdir(folder) if name.startswith("agni-auto-")]
        self.assertEqual(len(automatic_files), 2)
        self.assertTrue(os.path.isfile(manual_path), "automatic rotation must not delete manual backups")

    def test_restore_merges_a_later_snapshot_and_is_idempotent(self):
        customer_id, _ = self.add_sample_records()
        backup_path = os.path.join(self.temp.name, "later-snapshot.db")
        source = sqlite3.connect(self.db.db_path())
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
            new_customer = destination.execute(
                "INSERT INTO customers(name,type) VALUES('Restored Customer','retail')"
            ).lastrowid
            destination.execute(
                "INSERT INTO sales(number,customer_id,sale_date,total_paise,paid_paise) VALUES(?,?,?,?,?)",
                ("RESTORE-S-001", new_customer, date.today().isoformat(), 7500, 0),
            )
            destination.commit()
        finally:
            destination.close()
            source.close()

        with open(backup_path, "rb") as handle:
            payload = handle.read()
        response = self.client.post("/api/data/restore", data={
            "backup_file": (io.BytesIO(payload), "agni-later-backup.db"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_json())
        restored = response.get_json()
        self.assertEqual(restored["status"], "merged")
        self.assertGreater(restored["inserted"], 0)
        self.assertTrue(restored["safety_backup"].startswith("agni-before-restore-"))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM customers WHERE name='Restored Customer'"
        ).fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM sales WHERE number='RESTORE-S-001'"
        ).fetchone()[0], 1)

        repeated = self.client.post("/api/data/restore", data={
            "backup_file": (io.BytesIO(payload), "agni-later-backup.db"),
        }, content_type="multipart/form-data")
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        self.assertEqual(repeated.get_json()["status"], "already_current")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM customers WHERE name='Restored Customer'"
        ).fetchone()[0], 1)

    def test_restore_rejects_divergent_copies_without_importing_rows(self):
        self.add_sample_records()
        backup_path = os.path.join(self.temp.name, "divergent-snapshot.db")
        source = sqlite3.connect(self.db.db_path())
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
            destination.execute("INSERT INTO customers(name,type) VALUES('Backup-only Customer','retail')")
            destination.commit()
        finally:
            source.close()
            destination.close()

        # Add a different row to the live database after the backup was made.
        self.conn.execute("INSERT INTO customers(name,type) VALUES('Local-only Customer','retail')")
        self.conn.commit()
        with open(backup_path, "rb") as handle:
            payload = handle.read()
        before = self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        response = self.client.post("/api/data/restore", data={
            "backup_file": (io.BytesIO(payload), "agni-divergent-backup.db"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], before)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM customers WHERE name='Backup-only Customer'"
        ).fetchone()[0], 0)

    def test_backup_snapshot_is_self_contained_and_deserializable(self):
        self.add_sample_records()
        from backup import create_temporary_backup

        backup_path = create_temporary_backup()
        self.assertTrue(backup_path and os.path.isfile(backup_path))
        try:
            with sqlite3.connect(backup_path) as on_disk:
                self.assertEqual(on_disk.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
                self.assertEqual(on_disk.execute("PRAGMA integrity_check").fetchone()[0], "ok")

            with open(backup_path, "rb") as handle:
                snapshot_bytes = handle.read()
            snapshot = sqlite3.connect(":memory:")
            try:
                snapshot.deserialize(snapshot_bytes)
                self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 1)
            finally:
                snapshot.close()
        finally:
            try:
                os.remove(backup_path)
            except FileNotFoundError:
                pass

    def test_backup_download_is_a_valid_sqlite_snapshot_with_current_data(self):
        customer_id, _ = self.add_sample_records()
        response = self.client.get("/api/data/backup")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/vnd.sqlite3")
        self.assertIn("agni-gas-backup-", response.headers.get("Content-Disposition", ""))
        self.assertTrue(response.data.startswith(b"SQLite format 3\x00"))

        snapshot = sqlite3.connect(":memory:")
        try:
            snapshot.deserialize(response.data)
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                snapshot.execute("SELECT name FROM customers WHERE id=?", (customer_id,)).fetchone()[0],
                "Data Test Customer",
            )
            self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 1)
        finally:
            snapshot.close()
            response.close()


if __name__ == "__main__":
    unittest.main()
