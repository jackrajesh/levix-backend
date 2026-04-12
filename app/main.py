import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine
from . import models

# Import routers
from .routes import pages, auth, inventory, sales, analytics, pending, webhooks, admin, messages, meta_auth

app = FastAPI(title="Levix API")

# Create tables for local development
models.Base.metadata.create_all(bind=engine)

# --- Safe schema migration for existing databases ---
def _run_migrations():
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(engine)
        if "sales_records" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("sales_records")]
            if "product_name" not in columns:
                conn.execute(text("ALTER TABLE sales_records ADD COLUMN product_name VARCHAR"))
                conn.commit()
                print("[Migration] Added product_name column to sales_records")
            
            try:
                conn.execute(text("ALTER TABLE sales_records ALTER COLUMN product_id DROP NOT NULL"))
                conn.commit()
            except Exception:
                conn.rollback()

            if "price" not in columns:
                conn.execute(text("ALTER TABLE sales_records ADD COLUMN price NUMERIC(10,2) NOT NULL DEFAULT 0"))
                conn.commit()
                print("[Migration] Added price column to sales_records")

            if "pending_requests" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("pending_requests")]
                if "customer_message" not in columns:
                    conn.execute(text("ALTER TABLE pending_requests ADD COLUMN customer_message VARCHAR"))
                if "request_type" not in columns:
                    conn.execute(text("ALTER TABLE pending_requests ADD COLUMN request_type VARCHAR DEFAULT 'customer'"))
                if "product_id" not in columns:
                    conn.execute(text("ALTER TABLE pending_requests ADD COLUMN product_id INTEGER"))
                conn.commit()

            if "inventory_items" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("inventory_items")]
                if "quantity" not in columns:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN quantity INTEGER NOT NULL DEFAULT 0"))
                if "stock_warning_active" not in columns:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN stock_warning_active BOOLEAN NOT NULL DEFAULT FALSE"))
                if "price" not in columns:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN price NUMERIC(10,2) NOT NULL DEFAULT 0"))
                    print("[Migration] Added price column to inventory_items")
                conn.commit()

            if "log_entries" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("log_entries")]
                if "is_matched" not in columns:
                    conn.execute(text("ALTER TABLE log_entries ADD COLUMN is_matched BOOLEAN DEFAULT TRUE"))
                    print("[Migration] Added is_matched column to log_entries")
                if "match_source" not in columns:
                    conn.execute(text("ALTER TABLE log_entries ADD COLUMN match_source VARCHAR"))
                    print("[Migration] Added match_source column to log_entries")
                conn.commit()

try:
    _run_migrations()
except Exception as e:
    print(f"[Migration] Warning: {e}")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Register Routers ---
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(sales.router)
app.include_router(analytics.router)
app.include_router(pending.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(messages.router)

# 🔥 ADD THIS (IMPORTANT)
app.include_router(meta_auth.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)