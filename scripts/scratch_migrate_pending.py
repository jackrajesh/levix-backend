import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import text
from app.database import engine

def migrate_pending():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE pending_requests ADD COLUMN customer_name VARCHAR;"))
            print("Added customer_name to pending_requests")
        except Exception as e:
            print(f"Skipped customer_name: {e}")
            
        try:
            conn.execute(text("ALTER TABLE pending_requests ADD COLUMN customer_phone VARCHAR(20);"))
            print("Added customer_phone to pending_requests")
        except Exception as e:
            print(f"Skipped customer_phone: {e}")

if __name__ == "__main__":
    migrate_pending()
