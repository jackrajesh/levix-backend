import os
import sys

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

def migrate():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE shops ADD COLUMN phone_number VARCHAR(15) UNIQUE;"))
            print("Successfully added phone_number column to database.")
    except Exception as e:
        print(f"Migration error (already exists or DB error): {e}")

if __name__ == "__main__":
    migrate()
