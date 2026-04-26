"""
Migration: Add per-shop WhatsApp credentials to the shops table.
Run once: python tmp/migrate_whatsapp_fields.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import engine
from sqlalchemy import text

COLUMNS = [
    ("whatsapp_phone_number_id", "TEXT UNIQUE"),
    ("whatsapp_access_token",    "TEXT"),
    ("whatsapp_business_account_id", "TEXT"),
]

with engine.connect() as conn:
    for col, col_type in COLUMNS:
        try:
            conn.execute(text(f"ALTER TABLE shops ADD COLUMN {col} {col_type}"))
            conn.commit()
            print(f"  ✓ Added column: {col}")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print(f"  – Column already exists (skipped): {col}")
            else:
                print(f"  ✗ Error adding {col}: {e}")

print("Migration complete.")
