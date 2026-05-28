import sqlite3
import os

db_path = "app/data/levix.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Detailed table schemas for recreation
table_schemas = {
    "shops": "(id VARCHAR PRIMARY KEY, shop_name VARCHAR, owner_name VARCHAR, email VARCHAR UNIQUE, phone_number VARCHAR, password_hash VARCHAR, created_at DATETIME, settings JSON, business_category VARCHAR, business_mode VARCHAR, business_subnote TEXT, whatsapp_phone_number_id VARCHAR, whatsapp_access_token VARCHAR, whatsapp_business_account_id VARCHAR, shop_category VARCHAR)",
    "inventory_items": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, name VARCHAR, quantity INTEGER, price NUMERIC, status VARCHAR, stock_warning_active BOOLEAN, product_details TEXT, category VARCHAR, type VARCHAR, aliases_text TEXT, created_at DATETIME)",
    "orders": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, booking_id VARCHAR, order_id VARCHAR, customer_name VARCHAR, phone VARCHAR, address VARCHAR, product VARCHAR, quantity INTEGER, unit_price NUMERIC, total_amount NUMERIC, status VARCHAR, created_at DATETIME, updated_at DATETIME, customer_id VARCHAR)",
    "sales_records": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_id VARCHAR, product_name VARCHAR, date DATE, quantity INTEGER, price NUMERIC, performed_by VARCHAR, user_type VARCHAR)",
    "ai_leads": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, session_id VARCHAR, customer_name VARCHAR, phone VARCHAR, product_id VARCHAR, product_name VARCHAR, category VARCHAR, intent VARCHAR, collected_data JSON, summary TEXT, status VARCHAR DEFAULT 'new', source VARCHAR DEFAULT 'AI Assistant', confidence NUMERIC, created_at DATETIME, updated_at DATETIME)",
    "log_entries": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_name VARCHAR, product_id VARCHAR, status VARCHAR, is_matched BOOLEAN, match_source VARCHAR, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, performed_by VARCHAR, user_type VARCHAR)",
    "inventory_aliases": "(id VARCHAR PRIMARY KEY, inventory_id VARCHAR, alias VARCHAR)",
    "customer_sessions": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_phone VARCHAR, is_ordering BOOLEAN, can_order BOOLEAN, step VARCHAR, session_data TEXT, booking_id VARCHAR, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "customer_profiles": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_phone VARCHAR, customer_name VARCHAR, first_seen_at DATETIME, last_seen_at DATETIME, visit_count INTEGER, message_count INTEGER, total_orders INTEGER, total_leads INTEGER, favorite_products JSON, favorite_categories JSON, avg_budget FLOAT, max_budget FLOAT, preferred_spice_level VARCHAR, veg_preference VARCHAR, usual_people_count INTEGER, last_order_summary TEXT, last_order_at DATETIME, last_5_orders JSON, conversion_score INTEGER, vip_tier VARCHAR, notes JSON, created_at DATETIME, updated_at DATETIME)",
    "shop_roles": "(id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id VARCHAR, name VARCHAR, permissions JSON, created_at DATETIME)",
    "team_members": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, name VARCHAR, phone_number VARCHAR, email VARCHAR, role VARCHAR, password_hash VARCHAR, permissions JSON, is_active BOOLEAN, status VARCHAR, last_login DATETIME, created_at DATETIME)",
    "activated_addons": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, addon_id INTEGER, is_active BOOLEAN, activated_at DATETIME, expiry_date DATETIME)",
    "ai_analytics_events": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, event_type VARCHAR, metadata JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "missing_product_requests": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_name VARCHAR, count INTEGER, last_requested DATETIME DEFAULT CURRENT_TIMESTAMP, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "pending_requests": "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_name VARCHAR, phone VARCHAR, product_id VARCHAR, product_name VARCHAR, quantity INTEGER, status VARCHAR, created_at DATETIME, updated_at DATETIME)"
}

for table, schema in table_schemas.items():
    print(f"Checking {table}...")
    try:
        info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        if not info: 
            print(f"Table {table} does not exist. Skipping.")
            continue
        
        # Check if ANY of the ID/FK columns are INTEGER but should be VARCHAR
        cols_to_check = ["id", "shop_id", "product_id", "inventory_id", "customer_id"]
        needs_migration = False
        for col in info:
            if col[1] in cols_to_check and "INT" in col[2].upper():
                needs_migration = True
                break
        
        if needs_migration:
            print(f"Migrating {table} to UUID schema...")
            cursor.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            cursor.execute(f"CREATE TABLE {table} {schema}")
            
            # Get columns that exist in BOTH old and new
            old_cols = [c[1] for c in info]
            # We'll just try to copy what matches
            new_info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            new_cols = [c[1] for c in new_info]
            
            common_cols = [c for c in old_cols if c in new_cols]
            cols_str = ", ".join(common_cols)
            
            cursor.execute(f"INSERT INTO {table} ({cols_str}) SELECT {cols_str} FROM {table}_old")
            cursor.execute(f"DROP TABLE {table}_old")
            print(f"Table {table} migrated successfully.")
        else:
            print(f"Table {table} is already UUID-compatible.")
    except Exception as e:
        print(f"Error migrating {table}: {e}")

conn.commit()
conn.close()
print("Migration v2 complete!")
