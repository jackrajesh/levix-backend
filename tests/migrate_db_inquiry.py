import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, text
from app.database import DATABASE_URL

def migrate():
    print(f"Migrating database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    
    columns = [
        ("inquiry_status", "VARCHAR DEFAULT 'ACTIVE'"),
        ("inquiry_context_id", "VARCHAR"),
        ("paused_at", "TIMESTAMP WITH TIME ZONE"),
        ("resumed_at", "TIMESTAMP WITH TIME ZONE"),
        ("cancelled_at", "TIMESTAMP WITH TIME ZONE")
    ]
    
    is_sqlite = DATABASE_URL.startswith("sqlite")
    
    with engine.begin() as conn:
        for col_name, col_type in columns:
            actual_type = col_type
            if is_sqlite:
                if "TIMESTAMP" in col_type:
                    actual_type = "DATETIME"
            
            try:
                # Check if column exists
                if is_sqlite:
                    # SQLite check
                    res = conn.execute(text("PRAGMA table_info(conversation_sessions)"))
                    existing_cols = [row[1] for row in res.fetchall()]
                    if col_name in existing_cols:
                        print(f"Column {col_name} already exists in SQLite table.")
                        continue
                else:
                    # Postgres check
                    res = conn.execute(text(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name='conversation_sessions' AND column_name='{col_name}'"
                    ))
                    if res.fetchone():
                        print(f"Column {col_name} already exists in Postgres table.")
                        continue
                
                conn.execute(text(f"ALTER TABLE conversation_sessions ADD COLUMN {col_name} {actual_type}"))
                print(f"Added column {col_name} to conversation_sessions successfully.")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")

if __name__ == "__main__":
    migrate()
