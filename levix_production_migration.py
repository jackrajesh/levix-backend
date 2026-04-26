"""
levix_production_migration.py
=============================
Safe ALTER TABLE migrations for the Levix production Neon DB.
All statements use IF NOT EXISTS / ON CONFLICT DO NOTHING so they are
safe to re-run without side effects.

Run:
    python levix_production_migration.py

Or via psql:
    psql $DATABASE_URL -f levix_production_migration.sql
"""

import os
import sys

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SQL = """
-- ─────────────────────────────────────────────────────────────────────────────
-- Step 5: shop_category column on shops table
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE shops
    ADD COLUMN IF NOT EXISTS shop_category VARCHAR(50) DEFAULT 'General';

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 7: booking_id on orders (already in models — ensure it exists in DB)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS booking_id VARCHAR(12);

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 8: missing_product_requests (was previously PendingInquiry - now correct)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS missing_product_requests (
    id              SERIAL PRIMARY KEY,
    shop_id         INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    product_name    VARCHAR(200) NOT NULL,
    customer_phone  VARCHAR(20),
    count           INTEGER DEFAULT 1,
    last_requested_at TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mpr_shop_product
    ON missing_product_requests(shop_id, product_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- AdminAlert table (referenced in router_engine.py confirm_order error path)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_alerts (
    id            SERIAL PRIMARY KEY,
    shop_id       INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    alert_type    VARCHAR(100) NOT NULL,
    failure_count INTEGER DEFAULT 1,
    details       JSONB,
    resolved      BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_alerts_shop_type
    ON admin_alerts(shop_id, alert_type, created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Seed InventoryAlias typo corrections (idempotent via ON CONFLICT DO NOTHING)
-- These aliases point to no specific inventory_id and are used as global hints.
-- NOTE: The actual alias matching in order_engine.py goes by product name fuzzy
-- match too — these seeds help the alias lookup step.
-- ─────────────────────────────────────────────────────────────────────────────
-- (No global alias seeding needed — aliases are per inventory_item.
--  Typo corrections are handled in _apply_typo_corrections() in order_engine.py)

SELECT 'Migration complete' AS status;
"""

def run():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed. Install it with: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print("Running Levix production migration...")
    try:
        cur.execute(SQL)
        print("✅ Migration completed successfully.")
    except Exception as e:
        print(f"❌ Migration failed: {e}", file=sys.stderr)
        conn.rollback()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
