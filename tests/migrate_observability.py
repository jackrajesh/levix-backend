"""
migrate_observability.py — DB Migration for Observability Layer
================================================================
Safely adds conversation_event_log and webhook_audit_log tables.
Idempotent: safe to re-run — uses IF NOT EXISTS for all columns/tables.

Run: python tests/migrate_observability.py
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import DATABASE_URL, engine
from app import models
from app.database import Base
import sqlalchemy as sa

def migrate():
    print(f"[MIGRATE] Target DB: {DATABASE_URL[:50]}...")
    is_pg = "postgresql" in DATABASE_URL

    with engine.connect() as conn:
        # ── conversation_event_log ──────────────────────────────────────────
        if is_pg:
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS conversation_event_log (
                    id SERIAL PRIMARY KEY,
                    event_id VARCHAR UNIQUE NOT NULL,
                    session_id VARCHAR,
                    flow_id VARCHAR,
                    shop_id VARCHAR,
                    customer_phone VARCHAR(20),
                    event_type VARCHAR NOT NULL,
                    previous_state VARCHAR,
                    next_state VARCHAR,
                    trigger_source VARCHAR,
                    trigger_reason VARCHAR,
                    message_id VARCHAR,
                    webhook_id VARCHAR,
                    actor_type VARCHAR,
                    actor_id VARCHAR,
                    recovery_type VARCHAR,
                    checkpoint_id VARCHAR,
                    metadata_json JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_cel_session_id ON conversation_event_log (session_id)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_cel_shop_id ON conversation_event_log (shop_id)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_cel_event_type ON conversation_event_log (event_type)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_cel_customer_phone ON conversation_event_log (customer_phone)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_cel_created_at ON conversation_event_log (created_at)"))
            print("[MIGRATE] conversation_event_log: OK")

            # ── webhook_audit_log ───────────────────────────────────────────
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS webhook_audit_log (
                    id SERIAL PRIMARY KEY,
                    webhook_event_id VARCHAR UNIQUE NOT NULL,
                    shop_id VARCHAR,
                    wa_message_id VARCHAR,
                    sender_phone VARCHAR(20),
                    phone_number_id VARCHAR,
                    payload_hash VARCHAR,
                    message_type VARCHAR,
                    raw_message_text VARCHAR,
                    is_duplicate BOOLEAN DEFAULT FALSE,
                    processing_result VARCHAR,
                    route_target VARCHAR,
                    response_status VARCHAR,
                    outbound_wa_id VARCHAR,
                    retry_count INTEGER DEFAULT 0,
                    processing_latency_ms INTEGER,
                    error_summary VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_wal_wa_message_id ON webhook_audit_log (wa_message_id)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_wal_shop_id ON webhook_audit_log (shop_id)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_wal_is_duplicate ON webhook_audit_log (is_duplicate)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_wal_created_at ON webhook_audit_log (created_at)"))
            print("[MIGRATE] webhook_audit_log: OK")
        else:
            # SQLite (test environments)
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS conversation_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    session_id TEXT,
                    flow_id TEXT,
                    shop_id TEXT,
                    customer_phone TEXT,
                    event_type TEXT NOT NULL,
                    previous_state TEXT,
                    next_state TEXT,
                    trigger_source TEXT,
                    trigger_reason TEXT,
                    message_id TEXT,
                    webhook_id TEXT,
                    actor_type TEXT,
                    actor_id TEXT,
                    recovery_type TEXT,
                    checkpoint_id TEXT,
                    metadata_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS webhook_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_event_id TEXT UNIQUE NOT NULL,
                    shop_id TEXT,
                    wa_message_id TEXT,
                    sender_phone TEXT,
                    phone_number_id TEXT,
                    payload_hash TEXT,
                    message_type TEXT,
                    raw_message_text TEXT,
                    is_duplicate INTEGER DEFAULT 0,
                    processing_result TEXT,
                    route_target TEXT,
                    response_status TEXT,
                    outbound_wa_id TEXT,
                    retry_count INTEGER DEFAULT 0,
                    processing_latency_ms INTEGER,
                    error_summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("[MIGRATE] SQLite tables: OK")

        conn.commit()

    print("[MIGRATE] Observability migration complete.")

if __name__ == "__main__":
    migrate()
