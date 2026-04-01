import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine
from . import models

# Import routers
from .routes import pages, auth, inventory, sales, analytics, pending, webhooks, admin

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
                print("[Migration] Made product_id nullable in sales_records")
            except Exception:
                conn.rollback()

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

# --- Register Routers ---
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(sales.router)
app.include_router(analytics.router)
app.include_router(pending.router)
app.include_router(webhooks.router)
app.include_router(admin.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
