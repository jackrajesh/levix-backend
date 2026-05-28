import os
import re
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

# Load config
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / "config" / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL not found!")
    exit(1)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)
tables = inspector.get_table_names()

targets = [
    ("shops", "id"),
    ("inventory_items", "id"),
    ("inventory_items", "shop_id"),
    ("orders", "id"),
    ("orders", "shop_id"),
    ("orders", "customer_id"),
    ("sales_records", "id"),
    ("sales_records", "shop_id"),
    ("sales_records", "product_id"),
    ("ai_leads", "id"),
    ("ai_leads", "shop_id"),
    ("ai_leads", "product_id"),
    ("log_entries", "id"),
    ("log_entries", "shop_id"),
    ("log_entries", "product_id"),
    ("inventory_aliases", "id"),
    ("inventory_aliases", "inventory_id"),
    ("customer_sessions", "id"),
    ("customer_sessions", "shop_id"),
    ("customer_profiles", "id"),
    ("customer_profiles", "shop_id"),
    ("shop_roles", "shop_id"),
    ("team_members", "id"),
    ("team_members", "shop_id"),
    ("ai_analytics_events", "id"),
    ("ai_analytics_events", "shop_id"),
    ("missing_product_requests", "id"),
    ("missing_product_requests", "shop_id"),
    ("pending_requests", "id"),
    ("pending_requests", "shop_id"),
    ("pending_requests", "product_id"),
]

with engine.connect() as conn:
    for table, col in targets:
        if table not in tables:
            print(f"Table {table} not found. Skipping.")
            continue
            
        columns = inspector.get_columns(table)
        column_info = next((c for c in columns if c["name"] == col), None)
        
        if not column_info:
            print(f"Column {col} in table {table} not found. Skipping.")
            continue
            
        type_name = str(column_info["type"]).upper()
        if "INT" in type_name:
            print(f"Converting {table}.{col} from {type_name} to VARCHAR...")
            try:
                # Use USING to cast existing data
                conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" TYPE VARCHAR USING "{col}"::VARCHAR'))
                conn.commit()
                print(f"Successfully converted {table}.{col}")
            except Exception as e:
                print(f"Failed to convert {table}.{col}: {e}")
        else:
            print(f"{table}.{col} is already {type_name}. Skipping.")

print("Postgres Migration Complete!")
