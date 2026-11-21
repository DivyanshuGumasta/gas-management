-- Agni Gas Agency schema (SQLite). Safe to run repeatedly.
-- All money columns are *_paise INTEGER (see money.py).
-- When this moves to a server database, the table/column names stay the same.

CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS cylinder_types (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,
    kg                    REAL,
    sale_price_paise      INTEGER NOT NULL DEFAULT 0,
    wholesale_price_paise INTEGER NOT NULL DEFAULT 0,
    purchase_price_paise  INTEGER NOT NULL DEFAULT 0,
    security_paise        INTEGER NOT NULL DEFAULT 0,
    full_qty              INTEGER NOT NULL DEFAULT 0,
    empty_qty             INTEGER NOT NULL DEFAULT 0,
    damaged_qty           INTEGER NOT NULL DEFAULT 0,
    with_customers_qty    INTEGER NOT NULL DEFAULT 0,
    sort_order            INTEGER NOT NULL DEFAULT 0,
    active                INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL,
    phone                  TEXT,
    address                TEXT,
    type                   TEXT NOT NULL DEFAULT 'retail' CHECK (type IN ('retail', 'wholesale')),
    opening_balance_paise  INTEGER NOT NULL DEFAULT 0,
    note                   TEXT,
    active                 INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL,
    gstin                  TEXT NOT NULL,
    phone                  TEXT,
    address                TEXT,
    opening_balance_paise  INTEGER NOT NULL DEFAULT 0,
    note                   TEXT,
    active                 INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY,
    number          TEXT NOT NULL UNIQUE,
    customer_id     INTEGER REFERENCES customers(id),
    sale_date       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    subtotal_paise  INTEGER NOT NULL DEFAULT 0,
    discount_paise  INTEGER NOT NULL DEFAULT 0,
    gst_percent     REAL    NOT NULL DEFAULT 0,
    gst_paise       INTEGER NOT NULL DEFAULT 0,
    total_paise     INTEGER NOT NULL DEFAULT 0,
    paid_paise      INTEGER NOT NULL DEFAULT 0,
    received_in     TEXT NOT NULL DEFAULT 'cash',
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    cancelled_at    TEXT,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);

CREATE TABLE IF NOT EXISTS sale_items (
    id               INTEGER PRIMARY KEY,
    sale_id          INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    mode             TEXT NOT NULL DEFAULT 'refill',
    qty_out          INTEGER NOT NULL DEFAULT 0,
    qty_empty_in     INTEGER NOT NULL DEFAULT 0,
    rate_paise       INTEGER NOT NULL DEFAULT 0,
    amount_paise     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id            INTEGER PRIMARY KEY,
    number        TEXT NOT NULL UNIQUE,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    amount_paise  INTEGER NOT NULL,
    payment_date  TEXT NOT NULL,
    received_in   TEXT NOT NULL DEFAULT 'cash',
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id);

CREATE TABLE IF NOT EXISTS stock_movements (
    id               INTEGER PRIMARY KEY,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    moved_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ref_type         TEXT,
    ref_id           INTEGER,
    full_delta       INTEGER NOT NULL DEFAULT 0,
    empty_delta      INTEGER NOT NULL DEFAULT 0,
    damaged_delta    INTEGER NOT NULL DEFAULT 0,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS cylinder_ledger (
    id               INTEGER PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    delta            INTEGER NOT NULL,
    ref_type         TEXT,
    ref_id           INTEGER,
    entry_date       TEXT NOT NULL,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_cyl_ledger_customer ON cylinder_ledger(customer_id);

CREATE TABLE IF NOT EXISTS customer_prices (
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    price_paise      INTEGER NOT NULL,
    PRIMARY KEY (customer_id, cylinder_type_id)
);

-- One supplier can supply many cylinder sizes; a size can have multiple suppliers.
-- The supplier-specific price is the default for new purchases from that supplier.
CREATE TABLE IF NOT EXISTS supplier_items (
    supplier_id          INTEGER NOT NULL REFERENCES suppliers(id),
    cylinder_type_id     INTEGER NOT NULL REFERENCES cylinder_types(id),
    purchase_price_paise INTEGER NOT NULL,
    PRIMARY KEY (supplier_id, cylinder_type_id)
);
CREATE INDEX IF NOT EXISTS idx_supplier_items_cylinder ON supplier_items(cylinder_type_id);

-- A purchase stores the supplier's invoice as a record. The original supplier bill
-- is optionally stored as a BLOB so it remains included in the normal DB backup.
-- This app does not issue a purchase bill to the supplier.
CREATE TABLE IF NOT EXISTS purchases (
    id                    INTEGER PRIMARY KEY,
    number                TEXT NOT NULL UNIQUE,
    supplier_id           INTEGER NOT NULL REFERENCES suppliers(id),
    purchase_date         TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    subtotal_paise        INTEGER NOT NULL DEFAULT 0,
    gst_percent           REAL NOT NULL DEFAULT 0,
    gst_paise             INTEGER NOT NULL DEFAULT 0,
    total_paise           INTEGER NOT NULL DEFAULT 0,
    note                  TEXT,
    supplier_bill_name    TEXT,
    supplier_bill_mime    TEXT,
    supplier_bill_data    BLOB,
    status                TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(purchase_date);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON purchases(supplier_id);

CREATE TABLE IF NOT EXISTS purchase_items (
    id                    INTEGER PRIMARY KEY,
    purchase_id           INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    cylinder_type_id      INTEGER NOT NULL REFERENCES cylinder_types(id),
    full_in_qty           INTEGER NOT NULL DEFAULT 0,
    empty_out_qty         INTEGER NOT NULL DEFAULT 0,
    new_empty_qty         INTEGER NOT NULL DEFAULT 0,
    rate_paise            INTEGER NOT NULL DEFAULT 0,
    security_rate_paise   INTEGER NOT NULL DEFAULT 0,
    amount_paise          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id);

-- Payments to suppliers are independent ledger entries. purchase_id is optional:
-- a payment can settle a particular purchase or be a general supplier payment/advance.
CREATE TABLE IF NOT EXISTS supplier_payments (
    id            INTEGER PRIMARY KEY,
    number        TEXT NOT NULL UNIQUE,
    supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    purchase_id   INTEGER REFERENCES purchases(id),
    amount_paise  INTEGER NOT NULL,
    payment_date  TEXT NOT NULL,
    paid_from     TEXT NOT NULL DEFAULT 'cash' CHECK (paid_from IN ('cash', 'bank')),
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_supplier ON supplier_payments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_purchase ON supplier_payments(purchase_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_date ON supplier_payments(payment_date);


-- General stock items (accessories, stoves, regulators, hoses, etc.).
-- Cylinder types remain in cylinder_types because they have full/empty/damaged
-- stock states; catalog_items are ordinary quantity-based goods.
CREATE TABLE IF NOT EXISTS catalog_items (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL COLLATE NOCASE UNIQUE,
    unit                  TEXT NOT NULL DEFAULT 'pcs',
    purchase_price_paise  INTEGER NOT NULL DEFAULT 0,
    sale_price_paise      INTEGER NOT NULL DEFAULT 0,
    stock_qty_milli       INTEGER NOT NULL DEFAULT 0,
    active                INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_catalog_items_active_name ON catalog_items(active, name);

-- A supplier can offer many general items; the price is supplier-specific.
-- Deactivating an association does not delete the item or historical purchase rows.
CREATE TABLE IF NOT EXISTS supplier_catalog_items (
    supplier_id          INTEGER NOT NULL REFERENCES suppliers(id),
    item_id              INTEGER NOT NULL REFERENCES catalog_items(id),
    purchase_price_paise INTEGER NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (supplier_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_supplier_catalog_items_item ON supplier_catalog_items(item_id);

-- Purchase line snapshots preserve the item name, unit and price as they were
-- on the supplier's invoice, even if the catalogue item is edited later.
CREATE TABLE IF NOT EXISTS purchase_catalog_items (
    id              INTEGER PRIMARY KEY,
    purchase_id     INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES catalog_items(id),
    item_name       TEXT NOT NULL,
    unit            TEXT NOT NULL,
    quantity_milli  INTEGER NOT NULL,
    rate_paise      INTEGER NOT NULL,
    amount_paise    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchase_catalog_items_purchase ON purchase_catalog_items(purchase_id);
CREATE INDEX IF NOT EXISTS idx_purchase_catalog_items_item ON purchase_catalog_items(item_id);

CREATE TABLE IF NOT EXISTS catalog_stock_movements (
    id                  INTEGER PRIMARY KEY,
    item_id             INTEGER NOT NULL REFERENCES catalog_items(id),
    purchase_id         INTEGER NOT NULL REFERENCES purchases(id),
    moved_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    quantity_delta_milli INTEGER NOT NULL,
    note                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_catalog_stock_item ON catalog_stock_movements(item_id, moved_at);
