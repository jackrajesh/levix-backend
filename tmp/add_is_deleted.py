import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import engine
from sqlalchemy import text

def run_migration():
    with engine.begin() as conn:
        print("Running ALTER TABLE...")
        conn.execute(text("ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;"))
        print("Done!")

if __name__ == "__main__":
    run_migration()
