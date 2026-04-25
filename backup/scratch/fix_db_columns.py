from app.database import engine
from sqlalchemy import text

def add_columns():
    with engine.connect() as conn:
        print("Adding columns to 'orders' table...")
        try:
            conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;"))
            conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS unit_price NUMERIC(10, 2) DEFAULT 0;"))
            conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS total_amount NUMERIC(10, 2) DEFAULT 0;"))
            conn.commit()
            print("Successfully added columns to 'orders' table.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    add_columns()
