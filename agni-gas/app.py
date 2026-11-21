"""Agni Gas Agency - Flask entry point.

Architecture rule: Flask only (1) serves HTML shells and static files and
(2) exposes a JSON API under /api. Pages never contain data; the JavaScript
fetches everything from /api. That is what lets us move the API to a server
later without touching the frontend (see static/js/config.js).
"""
import os

from flask import Flask, redirect, render_template

from paths import resource_path

# url -> (template, nav key, page title, what will be built here)
PAGES = {
    "/": ("dashboard.html", "home", "Home", ""),
    "/sales": ("placeholder.html", "sales", "Sales", "Sales list, filters and export"),
    "/sales/new": ("placeholder.html", "sales", "New Sale", "Cylinder sale form, payment and GST"),
    "/customers": ("customers.html", "customers", "Customers", "Customer list, add customer, ledger along with Udhaar list, receive payment, payment history"),
    "/suppliers-purchases": ("suppliers_purchases.html", "suppliers_purchases", "Suppliers & Purchases", ""),
    "/purchases/new": ("placeholder.html", "purchases", "New purchase",
                       "Purchase record with the supplier's bill attached"),
    "/stock": ("placeholder.html", "stock", "Stock & Price", "Cylinder stock, prices, damaged stock, history"),
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

    app.add_url_rule(
        "/suppliers", "page_suppliers_legacy",
        lambda: redirect("/suppliers-purchases?tab=suppliers"),
    )
    app.add_url_rule(
        "/purchases", "page_purchases_legacy",
        lambda: redirect("/suppliers-purchases?tab=purchases"),
    )

    app.add_url_rule("/customers/<int:cid>", "page_customer_detail",
                     make_view("customer_detail.html", "customers", "Customer", ""))
    app.add_url_rule("/udhaar", "page_udhaar", lambda: redirect("/customers"))

    # Sale detail / receipt (recent-sales rows link here)
    app.add_url_rule(
        "/sales/<int:sale_id>", "page_sale_detail",
        make_view("placeholder.html", "sales", "Sale receipt", "Tax invoice, print / WhatsApp, cancel bill"),
    )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("AGNI_DEBUG") == "1")
