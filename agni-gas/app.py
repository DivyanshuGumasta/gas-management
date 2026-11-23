"""Agni Gas Agency - Flask entry point.

Flask serves page shells/static assets and exposes JSON APIs under /api.
Pages remain data-free; JavaScript talks to the API through static/js/api.js.
"""
import os

from flask import Flask, redirect, render_template, request

from paths import resource_path

PAGES = {
    "/": ("dashboard.html", "home", "Home", ""),
    "/sales": ("sales.html", "sales", "Sales", ""),
    "/business": ("business.html", "sales", "Invoice settings", "Agency details printed on customer invoices"),
    "/customers": ("customers.html", "customers", "Customers", "Customer list, ledger, receive payment and payment history"),
    "/suppliers-purchases": ("suppliers_purchases.html", "suppliers_purchases", "Suppliers & Purchases", ""),
    "/purchases/new": ("purchase_new.html", "suppliers_purchases", "New purchase", "Record supplier invoice and incoming stock"),
    "/stock": ("stock.html", "stock", "Stock & Price", "Cylinder stock, prices, damaged stock, history"),
    "/reports": ("placeholder.html", "reports", "Reports", "The five business reports, PDF and Excel export"),
    "/data": ("placeholder.html", "data", "Data & Backup", "Backup, restore, export and import"),
    "/help": ("placeholder.html", "help", "Help & support", "Support contacts"),
}


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=resource_path("templates"),
        static_folder=resource_path("static"),
    )

    from api import api_bp
    from backup import daily_backup
    from db import close_db, init_db

    init_db()
    try:
        daily_backup()
    except Exception as exc:  # a failed backup must never stop the app opening
        app.logger.warning("Daily backup failed: %s", exc)

    app.teardown_appcontext(close_db)
    app.register_blueprint(api_bp, url_prefix="/api")

    def make_view(template, nav, title, note):
        def view(**_kwargs):
            return render_template(template, nav=nav, title=title, note=note)
        return view

    for url, (template, nav, title, note) in PAGES.items():
        endpoint = "page_" + (url.strip("/").replace("/", "_") or "home")
        app.add_url_rule(url, endpoint, make_view(template, nav, title, note))

    # New supplier detail page and purchase record page.
    def supplier_detail(supplier_id):
        return render_template("supplier_detail.html", nav="suppliers_purchases",
                               title="Supplier", note="", supplier_id=supplier_id)

    app.add_url_rule("/suppliers-purchases/supplier/<int:supplier_id>",
                     "page_supplier_detail", supplier_detail)
    app.add_url_rule("/purchases/<int:purchase_id>", "page_purchase_detail",
                     make_view("purchase_detail.html", "suppliers_purchases", "Purchase record", ""))

    # Backwards-compatible URLs from the earlier separate sidebar entries.
    app.add_url_rule("/suppliers", "page_suppliers_legacy",
                     lambda: redirect("/suppliers-purchases?tab=suppliers"))
    app.add_url_rule("/purchases", "page_purchases_legacy",
                     lambda: redirect("/suppliers-purchases?tab=purchases"))

    app.add_url_rule("/customers/<int:cid>", "page_customer_detail",
                     make_view("customer_detail.html", "customers", "Customer", ""))
    app.add_url_rule("/udhaar", "page_udhaar", lambda: redirect("/customers"))
    # "New sale" is the second tab on the Sales page; old links to /sales/new still work.
    app.add_url_rule("/sales/new", "page_sales_new", lambda: redirect(
        "/sales?tab=new" + ("&" + request.query_string.decode() if request.query_string else "")))
    app.add_url_rule("/sales/<int:sale_id>", "page_sale_detail",
                     make_view("sale_detail.html", "sales", "Sale receipt", ""))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("AGNI_DEBUG") == "1")
