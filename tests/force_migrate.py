import sqlite3
import os

db_path = "app/data/levix.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

core_tables = {
    "shops": "(id VARCHAR PRIMARY KEY, shop_name VARCHAR, owner_name VARCHAR, email VARCHAR UNIQUE, phone_number VARCHAR, password_hash VARCHAR, created_at DATETIME, settings JSON, business_category VARCHAR, business_mode VARCHAR, business_subnote TEXT, whatsapp_phone_number_id VARCHAR, whatsapp_access_token VARCHAR, whatsapp_business_account_id VARCHAR, shop_category VARCHAR)",
    "inventory_items": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, name VARCHAR, quantity INTEGER, price NUMERIC, status VARCHAR, stock_warning_active BOOLEAN, product_details TEXT, category VARCHAR, type VARCHAR, aliases_text TEXT, created_at DATETIME)",
    "orders": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, booking_id VARCHAR, order_id VARCHAR, customer_name VARCHAR, phone VARCHAR, address VARCHAR, product VARCHAR, quantity INTEGER, unit_price NUMERIC, total_amount NUMERIC, status VARCHAR, created_at DATETIME, updated_at DATETIME)",
    "sales_records": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_id VARCHAR, product_name VARCHAR, date DATE, quantity INTEGER, price NUMERIC, performed_by VARCHAR, user_type VARCHAR)",
    "ai_leads": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, session_id VARCHAR, customer_name VARCHAR, phone VARCHAR, product_id VARCHAR, product_name VARCHAR, category VARCHAR, intent VARCHAR, collected_data JSON, summary TEXT, status VARCHAR DEFAULT 'new', source VARCHAR DEFAULT 'AI Assistant', confidence NUMERIC, created_at DATETIME, updated_at DATETIME)"
}

for table, schema in core_tables.items():
    print(f"Checking {table}...")
    info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    if not info: continue
    
    id_col = next((c for c in info if c[1] == "id"), None)
    if id_col and "INT" in id_col[2].upper():
        print(f"Migrating {table} to UUID schema...")
        cursor.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
        cursor.execute(f"CREATE TABLE {table} {schema}")
        
        cols = [c[1] for c in info]
        cols_str = ", ".join(cols)
        cursor.execute(f"INSERT INTO {table} ({cols_str}) SELECT {cols_str} FROM {table}_old")
        cursor.execute(f"DROP TABLE {table}_old")
        print(f"Table {table} migrated.")

conn.commit()
conn.close()
print("All done!")
