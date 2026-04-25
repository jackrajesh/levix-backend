from sqlalchemy import text
from app.database import engine

def run_migration():
    with engine.connect() as conn:
        for col in ["urgency", "priority"]:
            try:
                conn.execute(text(f"ALTER TABLE ai_leads ADD COLUMN {col} VARCHAR"))
                conn.commit()
                print(f"Migration: Added {col} column to ai_leads")
            except Exception as e:
                print(f"Migration ({col}): {e}")

if __name__ == "__main__":
    import os
    import sys
    sys.path.append(os.getcwd())
    run_migration()
