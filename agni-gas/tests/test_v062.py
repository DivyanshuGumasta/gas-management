"""v0.6.2 backend regression tests. GSTIN values are test fixtures only."""
import importlib
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal


class V062Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["AGNI_DATA_DIR"] = self.temp.name
        os.environ["AGNI_DB"] = os.path.join(self.temp.name, "v062-test.db")
        import app as app_module
        importlib.reload(app_module)
        self.client = app_module.app.test_client()
        import db
        self.db = db
        self.conn = db.connect()
        self._supplier_counter = 0
        self.client.put("/api/business", json={
            "name": "Test LPG Agency", "address": "1 Test Road, Durg",
            "gstin": "22AAAAA0000A1Z5", "state_code": "22", "invoice_prefix": "T",
        })

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def cylinder(self, weight="8.6", full="5", empty="2", security="500"):
        response = self.client.post("/api/cylinders", json={
            "weight_kg": weight, "sale_price": "100", "wholesale_price": "95",
            "purchase_price": "70", "security": security, "full": full, "empty": empty,
            "hsn": "27111910", "gst_rate": "18",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def supplier(self, name, cylinder, empty="0", security="500"):
        self._supplier_counter += 1
        gstin = f"22AAAAA{self._supplier_counter:04d}A1Z5"
        response = self.client.post("/api/suppliers", json={
            "name": name, "gstin": gstin, "opening_type": "payable", "opening_amount": "0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        sid = response.get_json()["id"]
        linked = self.client.post(f"/api/cylinders/{cylinder['id']}/suppliers", json={
            "supplier_id": sid, "purchase_price": "70", "security": security,
        })
        self.assertEqual(linked.status_code, 201, linked.get_json())
        self.conn.execute(
            "UPDATE supplier_items SET empty_qty=? WHERE supplier_id=? AND cylinder_type_id=?",
            (int(empty), sid, cylinder["id"]),
        )
        self.conn.commit()
        return sid

    def customer(self, name="Test Customer", held=None):
        response = self.client.post("/api/customers", json={
            "name": name, "type": "retail", "phone": "9876543210",
            "address": "Durg", "opening_type": "udhaar", "opening_amount": "0",
            "held": held or [],
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def sale(self, customer, rows, extra=None):
        payload = {
            "customer_id": customer["id"] if customer else None,
            "date": date.today().isoformat(), "place_state_code": "22",
            "lines": rows, "items": [], "discount": "0", "payment": "paid",
            "received_in": "cash", "paid": "0",
        }
        payload.update(extra or {})
        return self.client.post("/api/sales", json=payload)

    def row(self, cylinder, **values):
        result = {
            "cylinder_type_id": cylinder["id"], "rate": "100", "security": "500",
            "refill": 0, "new_full": 0, "new_empty": 0, "empty_in": 0,
            "damaged_in": 0,
        }
        result.update(values)
        return result

    def test_customer_creation_records_multiple_supplier_owned_opening_cylinders(self):
        c1, c2 = self.cylinder(), self.cylinder("11.7")
        s1, s2 = self.supplier("Supplier One", c1), self.supplier("Supplier Two", c2)
        customer = self.customer(held=[
            {"cylinder_type_id": c1["id"], "qty": 2, "supplier_id": s1, "deposit_each": "2500.00"},
            {"cylinder_type_id": c2["id"], "qty": 1, "supplier_id": s2, "deposit_each": "5000.00"},
        ])
        ledger = self.conn.execute(
            "SELECT cylinder_type_id,delta,ref_type,note FROM cylinder_ledger WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([(r["cylinder_type_id"], r["delta"], r["ref_type"]) for r in ledger],
                         [(c1["id"], 2, "opening"), (c2["id"], 1, "opening")])
        deposits = self.conn.execute(
            "SELECT cylinder_type_id,supplier_id,kind,qty,amount_paise,sale_id,note "
            "FROM customer_deposit_events WHERE customer_id=? ORDER BY id", (customer["id"],)
        ).fetchall()
        self.assertEqual([(r["cylinder_type_id"], r["supplier_id"], r["kind"], r["qty"], r["amount_paise"], r["sale_id"])
                          for r in deposits],
                         [(c1["id"], s1, "received", 2, 500000, None),
                          (c2["id"], s2, "received", 1, 500000, None)])
        counts = self.conn.execute(
            "SELECT with_customers_qty FROM cylinder_types WHERE id IN (?,?) ORDER BY id", (c1["id"], c2["id"])
        ).fetchall()
        self.assertEqual([r[0] for r in counts], [2, 1])
        holdings = self.client.get(f"/api/customers/{customer['id']}/holdings").get_json()
        self.assertEqual([(r["name"], r["supplier_id"], r["qty"], r["deposit_each"], r["deposit_total"])
                          for r in holdings],
                         [(c1["name"], s1, 2, "2500.00", "5000.00"),
                          (c2["name"], s2, 1, "5000.00", "5000.00")])

    def test_invalid_opening_row_rolls_back_customer_creation(self):
        c1, c2 = self.cylinder(), self.cylinder("11.7")
        s1 = self.supplier("Supplier One", c1)
        s2_response = self.client.post("/api/suppliers", json={"name": "Supplier Two", "gstin": "22AAAAA1234A1Z5"})
        s2 = s2_response.get_json()["id"]
        before = self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        response = self.client.post("/api/customers", json={
            "name": "Should Roll Back", "held": [
                {"cylinder_type_id": c1["id"], "qty": 1, "supplier_id": s1},
                {"cylinder_type_id": c2["id"], "qty": 1, "supplier_id": s2},
            ],
        })
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_ledger").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM customer_deposit_events").fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT SUM(with_customers_qty) FROM cylinder_types WHERE id IN (?,?)", (c1["id"], c2["id"])
        ).fetchone()[0], 0)

    def test_opening_cylinders_endpoint_adds_existing_customer_holdings(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        customer = self.customer()
        response = self.client.post(f"/api/customers/{customer['id']}/opening-cylinders", json={
            "held": [{"cylinder_type_id": c["id"], "qty": 3, "supplier_id": s, "deposit_each": "200.00"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()[0]["qty"], 3)
        self.assertEqual(response.get_json()[0]["deposit_total"], "600.00")

    def test_refill_succeeds_for_customer_with_zero_held_and_updates_supplier_empties(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        lot_id = self.conn.execute(
            "SELECT id FROM stock_lots WHERE cylinder_type_id=? AND qty_left>0 ORDER BY id LIMIT 1",
            (c["id"],),
        ).fetchone()[0]
        self.conn.execute("UPDATE stock_lots SET supplier_id=? WHERE id=?", (s, lot_id))
        self.conn.commit()
        customer = self.customer()
        before_ledger = self.conn.execute(
            "SELECT COALESCE(SUM(delta),0) FROM cylinder_ledger WHERE customer_id=?", (customer["id"],)
        ).fetchone()[0]
        response = self.sale(customer, [self.row(c, refill=1, supplier_id=s)])
        self.assertEqual(response.status_code, 201, response.get_json())
        lot_left = self.conn.execute("SELECT qty_left FROM stock_lots WHERE id=?", (lot_id,)).fetchone()[0]
        supplier_empty = self.conn.execute(
            "SELECT empty_qty FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (s, c["id"])
        ).fetchone()[0]
        after_ledger = self.conn.execute(
            "SELECT COALESCE(SUM(delta),0) FROM cylinder_ledger WHERE customer_id=?", (customer["id"],)
        ).fetchone()[0]
        self.assertEqual(lot_left, 4)
        self.assertEqual(supplier_empty, 1)
        self.assertEqual(after_ledger, before_ledger)

    def test_good_empty_return_refunds_recorded_deposit_by_default(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 2, "supplier_id": s, "deposit_each": "1750.00",
        }])
        response = self.sale(customer, [self.row(c, empty_in=1, return_supplier_id=s, deposit_back=True)])
        self.assertEqual(response.status_code, 201, response.get_json())
        detail = self.client.get(f"/api/sales/{response.get_json()['id']}").get_json()
        self.assertEqual(detail["deposit_refunded"], "1750.00")
        self.assertEqual(self.conn.execute(
            "SELECT empty_qty FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (s, c["id"])
        ).fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cylinder_deposits").fetchone()[0], 0)
        event = self.conn.execute(
            "SELECT supplier_id,kind,qty,amount_paise FROM customer_deposit_events "
            "WHERE customer_id=? ORDER BY id DESC LIMIT 1", (customer["id"],)
        ).fetchone()
        self.assertEqual((event["supplier_id"], event["kind"], event["qty"], event["amount_paise"]),
                         (s, "refunded", 1, 175000))

    def test_good_return_cannot_refund_more_than_outstanding_deposit(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 1, "supplier_id": s, "deposit_each": "100.00",
        }])
        response = self.sale(customer, [self.row(
            c, empty_in=1, return_supplier_id=s, deposit_back=True, deposit_each="101.00"
        )])
        self.assertEqual(response.status_code, 409, response.get_json())

    def test_partial_customer_deposit_refund_preserves_remaining_holding(self):
        c = self.cylinder()
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 2, "supplier_id": None, "deposit_each": "5.00",
        }])
        response = self.sale(customer, [self.row(c, empty_in=1, deposit_back=True, deposit_each="3.00")])
        self.assertEqual(response.status_code, 201, response.get_json())
        events = self.conn.execute(
            "SELECT kind,qty,amount_paise FROM customer_deposit_events WHERE customer_id=? ORDER BY id",
            (customer["id"],),
        ).fetchall()
        self.assertEqual([(r["kind"], r["qty"], r["amount_paise"]) for r in events], [
            ("received", 2, 1000), ("refunded", 1, 300), ("forfeited", 0, 200),
        ])
        holdings = self.client.get(f"/api/customers/{customer['id']}/holdings").get_json()
        self.assertEqual(len(holdings), 1)
        self.assertEqual((holdings[0]["qty"], holdings[0]["deposit_total"]), (1, "5.00"))

    def test_damaged_return_forfeits_customer_deposit_and_only_selected_supplier_deposit(self):
        c = self.cylinder()
        s1, s2 = self.supplier("Go Gas", c), self.supplier("Other Gas", c)
        for sid in (s1, s2):
            self.conn.execute(
                "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note) "
                "VALUES(?,?,'paid',2,100000,'Test purchase deposit')", (c["id"], sid)
            )
        self.conn.commit()
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 1, "supplier_id": s1, "deposit_each": "500.00",
        }])
        response = self.sale(customer, [self.row(c, damaged_in=1, return_supplier_id=s1)])
        self.assertEqual(response.status_code, 201, response.get_json())
        statuses = self.conn.execute(
            "SELECT supplier_id,kind,qty,status FROM cylinder_deposits WHERE kind='cancelled'"
        ).fetchall()
        self.assertEqual([(r["supplier_id"], r["kind"], r["qty"], r["status"]) for r in statuses],
                         [(s1, "cancelled", 1, "active")])
        event = self.conn.execute(
            "SELECT supplier_id,kind,qty,amount_paise FROM customer_deposit_events "
            "WHERE customer_id=? ORDER BY id DESC LIMIT 1", (customer["id"],)
        ).fetchone()
        self.assertEqual((event["supplier_id"], event["kind"], event["qty"], event["amount_paise"]),
                         (s1, "forfeited", 1, 50000))
        self.assertEqual(self.client.get(f"/api/sales/{response.get_json()['id']}").get_json()["deposit_refunded"], "0.00")

    def test_two_suppliers_require_explicit_stock_supplier_but_one_is_automatic(self):
        c = self.cylinder()
        s1, s2 = self.supplier("Supplier One", c), self.supplier("Supplier Two", c)
        customer = self.customer()
        missing = self.sale(customer, [self.row(c, refill=1)])
        self.assertEqual(missing.status_code, 422, missing.get_json())
        self.assertEqual(missing.get_json()["field"], "supplier_id")

        # A fresh database has one supplier, so the missing value resolves automatically.
        c2 = self.cylinder("11.7")
        s3 = self.supplier("Only Supplier", c2)
        # Archive the first two suppliers to leave exactly one active supplier.
        self.conn.execute("UPDATE suppliers SET active=0 WHERE id IN (?,?)", (s1, s2))
        self.conn.commit()
        ok = self.sale(customer, [self.row(c2, refill=1)])
        self.assertEqual(ok.status_code, 201, ok.get_json())
        line = self.conn.execute(
            "SELECT supplier_id FROM sale_lines WHERE sale_id=? AND kind='product'", (ok.get_json()["id"],)
        ).fetchone()
        self.assertEqual(line["supplier_id"], s3)

    def test_paid_invoice_can_be_cancelled_with_reason_and_refund_amount(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        lot_id = self.conn.execute(
            "SELECT id FROM stock_lots WHERE cylinder_type_id=? AND qty_left>0 ORDER BY id LIMIT 1",
            (c["id"],),
        ).fetchone()[0]
        self.conn.execute("UPDATE stock_lots SET supplier_id=? WHERE id=?", (s, lot_id))
        self.conn.commit()
        customer = self.customer()
        sale = self.sale(customer, [self.row(c, new_full=1, refill=1, supplier_id=s)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        sid = sale.get_json()["id"]
        balance_before = self.client.get(f"/api/customers/{customer['id']}").get_json()["balance"]
        before = self.conn.execute(
            "SELECT full_qty,empty_qty,with_customers_qty FROM cylinder_types WHERE id=?", (c["id"],)
        ).fetchone()
        cancelled = self.client.post(f"/api/sales/{sid}/cancel", json={"reason": "Duplicate invoice"})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()["refund"], "736.00")
        after = self.conn.execute(
            "SELECT full_qty,empty_qty,with_customers_qty FROM cylinder_types WHERE id=?", (c["id"],)
        ).fetchone()
        self.assertEqual((after["full_qty"], after["empty_qty"], after["with_customers_qty"]),
                         (before["full_qty"] + 2, before["empty_qty"] - 1, before["with_customers_qty"] - 1))
        self.assertEqual(self.conn.execute("SELECT qty_left FROM stock_lots WHERE id=?", (lot_id,)).fetchone()[0], 5)
        self.assertEqual(self.conn.execute(
            "SELECT empty_qty FROM supplier_items WHERE supplier_id=? AND cylinder_type_id=?", (s, c["id"])
        ).fetchone()[0], 0)
        event = self.conn.execute(
            "SELECT status FROM customer_deposit_events WHERE sale_id=?", (sid,)
        ).fetchone()
        self.assertEqual(event["status"], "reversed")
        detail = self.client.get(f"/api/sales/{sid}").get_json()
        self.assertEqual(detail["cancel_reason"], "Duplicate invoice")
        self.assertTrue(detail["cancelled_at"])
        self.assertEqual(detail["paid"], "736.00")
        balance_after = self.client.get(f"/api/customers/{customer['id']}").get_json()["balance"]
        self.assertEqual(balance_after, balance_before)
        self.assertEqual(self.client.post(f"/api/sales/{sid}/cancel", json={}).status_code, 409)

    def test_cancel_is_blocked_when_supplier_empty_stock_was_already_used(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        lot_id = self.conn.execute(
            "SELECT id FROM stock_lots WHERE cylinder_type_id=? AND qty_left>0 ORDER BY id LIMIT 1",
            (c["id"],),
        ).fetchone()[0]
        self.conn.execute("UPDATE stock_lots SET supplier_id=? WHERE id=?", (s, lot_id))
        self.conn.commit()
        customer = self.customer()
        sale = self.sale(customer, [self.row(c, refill=1, supplier_id=s)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        sid = sale.get_json()["id"]
        self.conn.execute(
            "UPDATE supplier_items SET empty_qty=0 WHERE supplier_id=? AND cylinder_type_id=?", (s, c["id"])
        )
        self.conn.commit()
        cancelled = self.client.post(f"/api/sales/{sid}/cancel", json={})
        self.assertEqual(cancelled.status_code, 409, cancelled.get_json())
        self.assertEqual(self.client.get(f"/api/sales/{sid}").get_json()["status"], "paid")

    def test_invoice_with_damaged_cylinder_already_dispatched_cannot_be_cancelled(self):
        c = self.cylinder()
        s = self.supplier("Go Gas", c)
        self.conn.execute(
            "INSERT INTO cylinder_deposits(cylinder_type_id,supplier_id,kind,qty,amount_paise,note) "
            "VALUES(?,?,'paid',1,50000,'Opening supplier security')", (c["id"], s)
        )
        self.conn.commit()
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 1, "supplier_id": s, "deposit_each": "500.00",
        }])
        sale = self.sale(customer, [self.row(c, damaged_in=1, return_supplier_id=s)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        damage_event = self.conn.execute(
            "SELECT id FROM cylinder_deposits WHERE sale_id=? AND kind='cancelled'", (sale.get_json()["id"],)
        ).fetchone()[0]
        dispatch = self.client.post("/api/stock/damaged/send-back", json={
            "date": date.today().isoformat(),
            "items": [{"damage_event_id": damage_event, "qty": 1, "supplier_id": s}],
        })
        self.assertEqual(dispatch.status_code, 200, dispatch.get_json())
        cancelled = self.client.post(f"/api/sales/{sale.get_json()['id']}/cancel", json={})
        self.assertEqual(cancelled.status_code, 409, cancelled.get_json())

    def test_cancel_reason_over_200_characters_is_rejected(self):
        c = self.cylinder()
        customer = self.customer()
        sale = self.sale(customer, [self.row(c, refill=1)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        response = self.client.post(f"/api/sales/{sale.get_json()['id']}/cancel", json={"reason": "x" * 201})
        self.assertEqual(response.status_code, 400)

    def test_sales_summary_excludes_deposits_and_row_keeps_invoice_total(self):
        c = self.cylinder()
        customer = self.customer()
        sale = self.sale(customer, [self.row(c, new_full=1)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        rows = self.client.get("/api/sales").get_json()
        self.assertEqual(rows["summary"]["total"], "118.00")
        self.assertEqual(rows["summary"]["deposits_held_change"], "500.00")
        row = next(x for x in rows["sales"] if x["id"] == sale.get_json()["id"])
        self.assertEqual(row["total"], "618.00")
        self.assertEqual(row["sales_value"], "118.00")
        self.assertEqual(row["cylinders"], 1)
        self.assertRegex(row["time"], r"^(0[1-9]|1[0-2]):[0-5][0-9] [AP]M$")

    def test_sales_summary_uses_all_matching_bills_beyond_500_row_cap(self):
        day = date.today().isoformat()
        self.conn.executemany(
            "INSERT INTO sales(number,customer_id,sale_date,created_at,subtotal_paise,taxable_paise,gst_paise,total_paise,paid_paise,received_in,status) "
            "VALUES(?,NULL,?,datetime('now','localtime'),100,100,0,100,100,'cash','active')",
            [(f"BULK-{index:05d}", day) for index in range(501)],
        )
        self.conn.commit()
        result = self.client.get("/api/sales").get_json()
        self.assertEqual(len(result["sales"]), 500)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["summary"]["bills"], 501)
        self.assertEqual(result["summary"]["total"], "501.00")

    def test_dashboard_sales_value_excludes_deposits(self):
        c = self.cylinder()
        customer = self.customer()
        sale = self.sale(customer, [self.row(c, new_full=1)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        dashboard = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dashboard["today"]["sales"], "118.00")
        self.assertEqual(dashboard["last7"][-1]["total"], "118.00")

    def test_discount_largest_remainder_is_exact_and_deterministic(self):
        from api.sales import _allocate_discount
        lines = [{"gross_paise": 1}, {"gross_paise": 1}, {"gross_paise": 1}]
        self.assertEqual(_allocate_discount(lines, 2, 3), [1, 1, 0])
        self.assertEqual(sum(_allocate_discount(lines, 2, 3)), 2)

    def test_gst_rate_text_and_request_tax_overrides_are_ignored(self):
        from api.util import gst_rate_text
        self.assertEqual(gst_rate_text(500), "5")
        self.assertEqual(gst_rate_text(1800), "18")
        self.assertEqual(gst_rate_text(250), "2.5")
        c = self.cylinder()
        customer = self.customer()
        issued = self.sale(customer, [self.row(c, new_full=1)])
        self.assertEqual(issued.status_code, 201, issued.get_json())
        ignored = self.sale(customer, [self.row(c, refill=1, gst_rate="5", hsn="00000000")],
                            {"reverse_charge": "yes"})
        self.assertEqual(ignored.status_code, 201, ignored.get_json())
        detail = self.client.get(f"/api/sales/{ignored.get_json()['id']}").get_json()
        self.assertEqual(detail["lines"][0]["gst_rate"], "18")
        self.assertFalse(detail["reverse_charge"])

    def test_legacy_invoice_detail_has_fallback_customer_and_sale_item_lines(self):
        c = self.cylinder()
        customer = self.customer()
        cursor = self.conn.execute(
            "INSERT INTO sales(number,customer_id,sale_date,created_at,subtotal_paise,total_paise,paid_paise,received_in,status,note) "
            "VALUES('LEG-00001',?,?,datetime('now','localtime'),10000,10000,10000,'cash','active',NULL)",
            (customer["id"], date.today().isoformat()),
        )
        sid = cursor.lastrowid
        self.conn.execute(
            "INSERT INTO sale_items(sale_id,cylinder_type_id,mode,qty_out,qty_empty_in,rate_paise,amount_paise) "
            "VALUES(?,?, 'refill',1,0,10000,10000)", (sid, c["id"]),
        )
        self.conn.commit()
        detail = self.client.get(f"/api/sales/{sid}").get_json()
        self.assertTrue(detail["legacy"])
        self.assertEqual(detail["business"], {})
        self.assertEqual(detail["customer"]["name"], customer["name"])
        self.assertEqual(detail["lines"][0]["name"], c["name"])
        self.assertEqual(detail["lines"][0]["amount"], "100.00")
        pdf = self.client.get(f"/api/sales/{sid}/pdf")
        self.assertIn(pdf.status_code, (200, 503))
        if pdf.status_code == 200:
            self.assertTrue(pdf.data.startswith(b"%PDF-"))

    def test_return_empties_endpoint_is_gone(self):
        customer = self.customer()
        response = self.client.post(f"/api/customers/{customer['id']}/return-empties", json={"items": []})
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json()["error"],
                         "Record returns from Sales → New sale so deposits stay correct.")

    def test_states_endpoint_is_sorted_and_uses_existing_reference(self):
        response = self.client.get("/api/states")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        names = [row["name"] for row in rows]
        self.assertEqual(names, sorted(names, key=str.casefold))
        self.assertIn({"code": "22", "name": "Chhattisgarh"}, rows)

    def test_holdings_adds_legacy_ledger_only_cylinders_as_unassigned_zero_deposit(self):
        c = self.cylinder()
        customer = self.customer()
        self.conn.execute(
            "INSERT INTO cylinder_ledger(customer_id,cylinder_type_id,delta,ref_type,entry_date,note) "
            "VALUES(?,?,2,'legacy',?,'Legacy held cylinders')",
            (customer["id"], c["id"], date.today().isoformat()),
        )
        self.conn.execute("UPDATE cylinder_types SET with_customers_qty=with_customers_qty+2 WHERE id=?", (c["id"],))
        self.conn.commit()
        holdings = self.client.get(f"/api/customers/{customer['id']}/holdings").get_json()
        self.assertEqual(holdings, [{
            "cylinder_type_id": c["id"], "name": c["name"],
            "supplier_id": None, "supplier_name": None,
            "qty": 2, "deposit_each": "0.00", "deposit_total": "0.00",
        }])

    def test_cancelling_a_paid_back_invoice_reports_amount_to_collect(self):
        c = self.cylinder()
        customer = self.customer(held=[{
            "cylinder_type_id": c["id"], "qty": 1, "supplier_id": None, "deposit_each": "5.00",
        }])
        sale = self.sale(customer, [self.row(c, empty_in=1, deposit_back=True)])
        self.assertEqual(sale.status_code, 201, sale.get_json())
        sid = sale.get_json()["id"]
        detail = self.client.get(f"/api/sales/{sid}").get_json()
        self.assertEqual(detail["total"], "-5.00")
        cancelled = self.client.post(f"/api/sales/{sid}/cancel", json={"reason": "Wrong customer return"})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()["refund"], "5.00")
        self.assertEqual(cancelled.get_json()["refund_direction"], "collect")



if __name__ == "__main__":
    unittest.main()
