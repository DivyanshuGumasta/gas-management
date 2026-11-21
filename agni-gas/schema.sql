-- Agni Gas Agency schema (SQLite). Safe to run repeatedly.
-- All money columns are *_paise INTEGER (see money.py).
-- When this moves to a server database, the table/column names stay the same.

CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,          -- 'sale', 'payment', 'purchase' ...
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS cylinder_types (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,          -- '15 kg'
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
    opening_balance_paise  INTEGER NOT NULL DEFAULT 0,   -- + they owe us (udhaar), - advance
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
    opening_balance_paise  INTEGER NOT NULL DEFAULT 0,   -- + we owe them, - advance
    note                   TEXT,
    active                 INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY,
    number          TEXT NOT NULL UNIQUE,                -- S-00001
    customer_id     INTEGER REFERENCES customers(id),    -- NULL = walk-in customer
    sale_date       TEXT NOT NULL,                       -- YYYY-MM-DD
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
CREATE INDEX IF NOT EXISTS idx_sales_date     ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);

CREATE TABLE IF NOT EXISTS sale_items (
    id               INTEGER PRIMARY KEY,
    sale_id          INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    mode             TEXT NOT NULL DEFAULT 'refill',     -- refill | with_cylinder
    qty_out          INTEGER NOT NULL DEFAULT 0,         -- full cylinders given
    qty_empty_in     INTEGER NOT NULL DEFAULT 0,         -- empties taken back
    rate_paise       INTEGER NOT NULL DEFAULT 0,
    amount_paise     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (                    -- money received from customers
    id            INTEGER PRIMARY KEY,
    number        TEXT NOT NULL UNIQUE,                  -- R-00001
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    amount_paise  INTEGER NOT NULL,
    payment_date  TEXT NOT NULL,
    received_in   TEXT NOT NULL DEFAULT 'cash',
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_date     ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id);

CREATE TABLE IF NOT EXISTS stock_movements (             -- append-only stock history
    id               INTEGER PRIMARY KEY,
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    moved_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ref_type         TEXT,                               -- sale | purchase | adjust | damaged
    ref_id           INTEGER,
    full_delta       INTEGER NOT NULL DEFAULT 0,
    empty_delta      INTEGER NOT NULL DEFAULT 0,
    damaged_delta    INTEGER NOT NULL DEFAULT 0,
    note             TEXT
);

-- Still to add when those screens are built: purchases, purchase_items
-- (+ attached supplier bill file), supplier_payments.

-- Cylinders currently with each customer: append-only ledger (+ given, - returned).
CREATE TABLE IF NOT EXISTS cylinder_ledger (
    id               INTEGER PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    delta            INTEGER NOT NULL,
    ref_type         TEXT,                               -- sale | return | opening
    ref_id           INTEGER,
    entry_date       TEXT NOT NULL,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_cyl_ledger_customer ON cylinder_ledger(customer_id);

-- Per-customer special price (overrides the retail / wholesale price in a sale).
CREATE TABLE IF NOT EXISTS customer_prices (
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    cylinder_type_id INTEGER NOT NULL REFERENCES cylinder_types(id),
    price_paise      INTEGER NOT NULL,
    PRIMARY KEY (customer_id, cylinder_type_id)
);

-- Planned (Stock & Price / Purchase + Supplier merge): supplier_items table linking
-- each cylinder size to the supplier(s) who sell it, with that supplier's price.
