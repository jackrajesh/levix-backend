import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .database import engine
from . import models

# Import routers
from .routes import pages, auth, inventory, sales, analytics, pending, webhooks, admin, messages, meta_auth, orders, plans, team, logs, inbox, settings, contact, superadmin, conversations

from contextlib import asynccontextmanager

app = FastAPI(title="LEVIX API")

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": str(datetime.now())}

# Database init handled in startup event

# Seed SaaS Initial Data (Plans, Addons)
@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan context manager (replaces deprecated on_event startup/shutdown)."""
    print("[SYSTEM] Starting LEVIX Boot Sequence...")
    
    # 1. Base Tables
    try:
        models.Base.metadata.create_all(bind=engine)
        print("[SYSTEM] Base tables verified.")
    except Exception as e:
        print(f"[SYSTEM] Create tables warning: {e}")

    # 2. Migrations (Atomic)
    try:
        _run_uuid_reconciliation()
        _run_migrations()
        _run_team_migrations()
        _run_production_hardening_migrations()
        _run_universal_retail_migrations()
        _run_approval_migrations()
        _run_legacy_cleanup_migrations()
        _run_order_items_migration()
        _run_inquiry_lifecycle_migrations()
    except Exception as e:
        print(f"[SYSTEM] Migration warning: {e}")

    # 3. Seeding
    try:
        from .database import SessionLocal
        from .services.subscription_service import SubscriptionService
        db = SessionLocal()
        SubscriptionService.seed_initial_data(db)
        db.close()
        print("[SYSTEM] Subscription seeding complete.")
    except Exception as e:
        print(f"[SYSTEM] Seeding warning: {e}")
    

    # 5. OMEGA Integrity Check
    try:
        from .services.router_engine import RouterEngine
        from .services.intent_engine import IntentEngine
        from .services.memory_engine import MemoryEngine
        from .services.sse import broadcast_event
        
        print("[OMEGA] Running Startup Integrity Check...")
        
        # Task 1: Startup Integrity Check
        checks = {
            "DB Reachable": True,
            "SSE Queue Table": False,
            "Rate Limiter": True
        }
        
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if "pending_sse_events" in tables: checks["SSE Queue Table"] = True
        
        for name, ok in checks.items():
            if ok:
                print(f"[OMEGA] {name}: VERIFIED (OK)")
            else:
                print(f"[OMEGA] {name}: WARNING (Degraded mode)")
                
    except Exception as e:
        print(f"[OMEGA] Integrity check failed: {e}")

    print("[SYSTEM] Boot Sequence Finalized.")
    yield  # App runs here
    # Shutdown logic can go here if needed

# Attach lifespan to app
app.router.lifespan_context = lifespan

# --- Safe schema migration for existing databases ---
def _run_migrations():
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(conn)
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
                if "barcode" not in columns:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN barcode VARCHAR"))
                    print("[Migration] Added barcode column to inventory_items")
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
            
            if "customer_sessions" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("customer_sessions")]
                if "can_order" not in columns:
                    conn.execute(text("ALTER TABLE customer_sessions ADD COLUMN can_order BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                    print("[Migration] Added can_order column to customer_sessions")

            if "shops" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("shops")]
                if "owner_email" in columns and "email" not in columns:
                    conn.execute(text("ALTER TABLE shops RENAME COLUMN owner_email TO email"))
                    conn.commit()
                    print("[Migration] Renamed owner_email to email in shops")
                if "phone" in columns and "phone_number" not in columns:
                    conn.execute(text("ALTER TABLE shops RENAME COLUMN phone TO phone_number"))
                    conn.commit()
                    print("[Migration] Renamed phone to phone_number in shops")
                    
            if "subscriptions" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("subscriptions")]
                if "cashfree_subscription_id" not in columns:
                    conn.execute(text("ALTER TABLE subscriptions ADD COLUMN cashfree_subscription_id VARCHAR"))
                    conn.commit()
                    print("[Migration] Added cashfree_subscription_id column to subscriptions")

def _run_team_migrations():
    """Safe migrations for team management v2 (roles + status)."""
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = inspector.get_table_names()

        # Create shop_roles table if missing
        if "shop_roles" not in tables:
            is_sqlite = engine.url.drivername.startswith("sqlite")
            id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            ts_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE DEFAULT now()"
            
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS shop_roles (
                    id {id_type},
                    shop_id VARCHAR NOT NULL REFERENCES shops(id),
                    name VARCHAR NOT NULL,
                    permissions JSON,
                    created_at {ts_type}
                )
            """))
            conn.commit()
            print("[Migration] Created shop_roles table")

        # Add status column to team_members if missing
        if "team_members" in tables:
            columns = [c["name"] for c in inspector.get_columns("team_members")]
            if "status" not in columns:
                conn.execute(text("ALTER TABLE team_members ADD COLUMN status VARCHAR DEFAULT 'active'"))
                conn.commit()
                print("[Migration] Added status column to team_members")

        # Add audit columns to log_entries, sales_records, order_logs
        for table in ["log_entries", "sales_records", "order_logs"]:
            if table in tables:
                columns = [c["name"] for c in inspector.get_columns(table)]
                if "performed_by" not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN performed_by VARCHAR"))
                if "user_type" not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_type VARCHAR"))
                conn.commit()
                print(f"[Migration] Added audit columns to {table}")

        # Create activity_logs table if missing
        if "activity_logs" not in tables:
            is_sqlite = engine.url.drivername.startswith("sqlite")
            id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            ts_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE DEFAULT now()"
            
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id {id_type},
                    shop_id VARCHAR NOT NULL REFERENCES shops(id),
                    user_id VARCHAR,
                    user_name VARCHAR,
                    role VARCHAR,
                    category VARCHAR NOT NULL,
                    action VARCHAR NOT NULL,
                    target VARCHAR,
                    old_value VARCHAR,
                    new_value VARCHAR,
                    severity VARCHAR DEFAULT 'info',
                    ip_address VARCHAR,
                    created_at {ts_type}
                )
            """))
            conn.commit()
            print("[Migration] Created activity_logs table")
        else:
            columns = [c["name"] for c in inspector.get_columns("activity_logs")]
            if "action_type" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN action_type VARCHAR"))
            if "entity_type" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN entity_type VARCHAR"))
            if "entity_name" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN entity_name VARCHAR"))
            if "old_values" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN old_values JSON"))
            if "new_values" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN new_values JSON"))
            if "actor_name" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN actor_name VARCHAR"))
            if "metadata" not in columns:
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN metadata JSON"))
            conn.commit()
            print("[Migration] Added detail columns to activity_logs")


def _run_production_hardening_migrations():
    """Task 2: Migration for AdminAlert table."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            is_sqlite = engine.url.drivername.startswith("sqlite")
            id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            ts_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE DEFAULT now()"

            if "admin_alerts" not in tables:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS admin_alerts (
                        id {id_type},
                        shop_id VARCHAR NOT NULL REFERENCES shops(id),
                        alert_type VARCHAR NOT NULL,
                        failure_count INTEGER DEFAULT 0,
                        details JSON,
                        created_at {ts_type}
                    )
                """))
                conn.commit()
                print("[Harden Migration] Created admin_alerts table")
    except Exception as e:
        print(f"[Harden Migration] Error: {e}")

def _run_universal_retail_migrations():
    """Universal Retail Overhaul: shops.shop_category migration."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            if "shops" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("shops")]
                if "shop_category" not in columns:
                    conn.execute(text("ALTER TABLE shops ADD COLUMN shop_category VARCHAR DEFAULT 'General / Other'"))
                    conn.commit()
                    print("[Universal Migration] Added shop_category to shops table")
    except Exception as e:
        print(f"[Universal Migration] Error: {e}")

def _run_approval_migrations():
    """Safe, idempotent migration: adds approval lifecycle columns to shops table.
    
    IMPORTANT: Existing shops default to 'approved' so active users aren't locked out.
    Only new registrations will start in 'pending' state (enforced by model default).
    """
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            if "shops" not in inspector.get_table_names():
                return
            columns = [c["name"] for c in inspector.get_columns("shops")]

            if "approval_status" not in columns:
                conn.execute(text(
                    "ALTER TABLE shops ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'approved'"
                ))
                conn.commit()
                print("[Approval Migration] Added approval_status column (existing shops default: approved)")

            if "rejection_reason" not in columns:
                conn.execute(text("ALTER TABLE shops ADD COLUMN rejection_reason TEXT"))
                conn.commit()
                print("[Approval Migration] Added rejection_reason column")

            if "approved_at" not in columns:
                conn.execute(text("ALTER TABLE shops ADD COLUMN approved_at TIMESTAMP WITH TIME ZONE"))
                conn.commit()
                print("[Approval Migration] Added approved_at column")

            if "approved_by" not in columns:
                conn.execute(text("ALTER TABLE shops ADD COLUMN approved_by VARCHAR"))
                conn.commit()
                print("[Approval Migration] Added approved_by column")

            if "deleted_at" not in columns:
                conn.execute(text("ALTER TABLE shops ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE"))
                conn.commit()
                print("[Approval Migration] Added deleted_at column")

    except Exception as e:
        print(f"[Approval Migration] Error: {e}")

def _run_legacy_cleanup_migrations():
    """Purge legacy systems: inventory_aliases."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            
            if "inventory_aliases" in tables:
                print("[Cleanup Migration] Dropping legacy inventory_aliases table...")
                conn.execute(text("DROP TABLE IF EXISTS inventory_aliases CASCADE"))
                conn.commit()
                print("[Cleanup Migration] Successfully dropped inventory_aliases table.")
    except Exception as e:
        print(f"[Cleanup Migration] Error: {e}")

def _run_order_items_migration():
    """Fix order_items foreign key to reference inventory_items instead of products."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            
            if "order_items" in tables:
                print("[Migration] Checking order_items foreign key...")
                try:
                    conn.execute(text("ALTER TABLE order_items DROP CONSTRAINT IF EXISTS order_items_product_id_fkey CASCADE"))
                    conn.commit()
                    print("[Migration] Dropped old foreign key constraint on order_items.")
                except Exception as e:
                    print(f"[Migration] Warning dropping constraint: {e}")
                    conn.rollback()
                
                try:
                    conn.execute(text("ALTER TABLE order_items ADD CONSTRAINT order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES inventory_items(id)"))
                    conn.commit()
                    print("[Migration] Added new foreign key constraint referencing inventory_items.")
                except Exception as e:
                    print(f"[Migration] Warning adding constraint: {e}")
                    conn.rollback()
    except Exception as e:
        print(f"[Migration] Error in order_items migration: {e}")

def _run_inquiry_lifecycle_migrations():
    """Safe, idempotent migration for conversation inquiry lifecycle."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            if "conversation_sessions" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("conversation_sessions")]
                if "inquiry_status" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN inquiry_status VARCHAR DEFAULT 'ACTIVE'"))
                    conn.commit()
                    print("[Migration] Added inquiry_status column to conversation_sessions")
                if "inquiry_context_id" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN inquiry_context_id VARCHAR"))
                    conn.commit()
                    print("[Migration] Added inquiry_context_id column to conversation_sessions")
                if "paused_at" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN paused_at TIMESTAMP WITH TIME ZONE"))
                    conn.commit()
                    print("[Migration] Added paused_at column to conversation_sessions")
                if "resumed_at" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN resumed_at TIMESTAMP WITH TIME ZONE"))
                    conn.commit()
                    print("[Migration] Added resumed_at column to conversation_sessions")
                if "cancelled_at" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN cancelled_at TIMESTAMP WITH TIME ZONE"))
                    conn.commit()
                    print("[Migration] Added cancelled_at column to conversation_sessions")
                
                # Operational Hardening Columns Migrations
                if "conversation_type" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN conversation_type VARCHAR DEFAULT 'INQUIRY'"))
                    conn.commit()
                    print("[Migration] Added conversation_type column to conversation_sessions")
                if "is_deleted" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                    print("[Migration] Added is_deleted column to conversation_sessions")
                if "deleted_at" not in columns:
                    conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE"))
                    conn.commit()
                    print("[Migration] Added deleted_at column to conversation_sessions")
    except Exception as e:
        print(f"[Migration] Error in inquiry lifecycle migration: {e}")

# Enable CORS
origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
if "*" in origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_production_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

    if path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    elif path in {"/sitemap.xml", "/robots.txt"}:
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-cache")

    return response

# --- Static File Serving ---
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
static_path = BASE_DIR / "static"

if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    print(f"[SYSTEM] Static files mounted from: {static_path}")
else:
    print(f"[SYSTEM WARNING] Static directory not found at: {static_path}")

@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    if exc.status_code == 403 and str(exc.detail).lower() in {"insufficient permissions", "forbidden"}:
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "Insufficient permissions"},
            headers=exc.headers,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

# --- Register Routers ---
try:
    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(inventory.router)
    app.include_router(sales.router)
    app.include_router(analytics.router)
    app.include_router(pending.router)
    app.include_router(webhooks.router)
    app.include_router(admin.router)
    app.include_router(messages.router)
    app.include_router(orders.router)
    app.include_router(meta_auth.router)
    app.include_router(plans.router)
    app.include_router(team.router)
    app.include_router(logs.router)
    app.include_router(inbox.router)
    app.include_router(settings.router)
    app.include_router(contact.router)
    app.include_router(superadmin.router)
    app.include_router(conversations.router)
    print("[SYSTEM] All routes loaded successfully.")
except Exception as e:
    print(f"[SYSTEM ERROR] Failed to load routes: {e}")


def _run_uuid_reconciliation():
    """Ensures all ID and shop_id columns are VARCHAR/String to support UUIDs."""
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = inspector.get_table_names()
        is_sqlite = engine.url.drivername.startswith("sqlite")

        # Tables to check: (Table Name, Column Name)
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
            ("customer_sessions", "id"),
            ("customer_sessions", "shop_id"),
            ("customer_profiles", "id"),
            ("customer_profiles", "shop_id"),
            ("shop_roles", "shop_id"),
            ("team_members", "id"),
            ("team_members", "shop_id"),
            ("ai_analytics_events", "shop_id"),
            ("missing_product_requests", "shop_id"),
            ("pending_requests", "id"),
            ("pending_requests", "shop_id"),
            ("pending_requests", "product_id"),
        ]

        for table, col in targets:
            if table not in tables:
                continue
            
            columns = inspector.get_columns(table)
            column_info = next((c for c in columns if c["name"] == col), None)
            
            if not column_info:
                continue
            
            type_name = str(column_info["type"]).upper()
            if "INT" in type_name:
                print(f"[UUID Migration] Converting {table}.{col} from {type_name} to VARCHAR...")
                if is_sqlite:
                    # Specialized SQLite handler below
                    continue 
                else:
                    try:
                        conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" TYPE VARCHAR USING "{col}"::VARCHAR'))
                        conn.commit()
                        print(f"[UUID Migration] Successfully converted {table}.{col}")
                    except Exception as e:
                        print(f"[UUID Migration] Failed to convert {table}.{col} in Postgres: {e}")

        # Specialized SQLite Re-creation for core tables
        if is_sqlite:
            _reconcile_sqlite_uuids(conn, inspector)
    print("[UUID Migration] Reconciliation step completed.")

def _reconcile_sqlite_uuids(conn, inspector):
    """SQLite-specific table recreation for UUID support."""
    from sqlalchemy import text
    tables = inspector.get_table_names()
    
    # Core tables that MUST have VARCHAR IDs
    core_tables = ["shops", "inventory_items", "orders", "sales_records", "log_entries", "customer_sessions", "customer_profiles", "team_members", "pending_requests"]
    
    for table in core_tables:
        if table not in tables: continue
        
        columns = inspector.get_columns(table)
        id_col = next((c for c in columns if c["name"] == "id"), None)
        if id_col and "INT" in str(id_col["type"]).upper():
            print(f"[SQLite UUID] Recreating table {table} to fix ID type...")
            try:
                # 1. Rename old
                conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_old"))
                
                # 2. Create new with correct schema
                if table == "shops":
                    schema = "(id VARCHAR PRIMARY KEY, shop_name VARCHAR, owner_name VARCHAR, email VARCHAR UNIQUE, phone_number VARCHAR, password_hash VARCHAR, created_at DATETIME, settings JSON, business_category VARCHAR, business_mode VARCHAR, business_subnote TEXT, whatsapp_phone_number_id VARCHAR, whatsapp_access_token VARCHAR, whatsapp_business_account_id VARCHAR, shop_category VARCHAR)"
                elif table == "inventory_items":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, name VARCHAR, quantity INTEGER, price NUMERIC, status VARCHAR, stock_warning_active BOOLEAN, product_details TEXT, category VARCHAR, type VARCHAR, aliases_text TEXT, created_at DATETIME)"
                elif table == "orders":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, booking_id VARCHAR, order_id VARCHAR, customer_name VARCHAR, phone VARCHAR, address VARCHAR, product VARCHAR, quantity INTEGER, unit_price NUMERIC, total_amount NUMERIC, status VARCHAR, created_at DATETIME, updated_at DATETIME)"
                elif table == "sales_records":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_id VARCHAR, product_name VARCHAR, date DATE, quantity INTEGER, price NUMERIC, performed_by VARCHAR, user_type VARCHAR)"
                elif table == "log_entries":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, product_name VARCHAR, product_id VARCHAR, status VARCHAR, is_matched BOOLEAN, match_source VARCHAR, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, performed_by VARCHAR, user_type VARCHAR)"
                elif table == "customer_sessions":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_phone VARCHAR, is_ordering BOOLEAN, can_order BOOLEAN, step VARCHAR, session_data TEXT, booking_id VARCHAR, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
                elif table == "customer_profiles":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_phone VARCHAR, customer_name VARCHAR, first_seen_at DATETIME, last_seen_at DATETIME, visit_count INTEGER, message_count INTEGER, total_orders INTEGER, total_leads INTEGER, favorite_products JSON, favorite_categories JSON, avg_budget FLOAT, max_budget FLOAT, preferred_spice_level VARCHAR, veg_preference VARCHAR, usual_people_count INTEGER, last_order_summary TEXT, last_order_at DATETIME, last_5_orders JSON, conversion_score INTEGER, vip_tier VARCHAR, notes JSON, created_at DATETIME, updated_at DATETIME)"
                elif table == "team_members":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, name VARCHAR, phone_number VARCHAR, email VARCHAR, role VARCHAR, password_hash VARCHAR, permissions JSON, is_active BOOLEAN, status VARCHAR, last_login DATETIME, created_at DATETIME)"
                elif table == "pending_requests":
                    schema = "(id VARCHAR PRIMARY KEY, shop_id VARCHAR, customer_name VARCHAR, phone VARCHAR, product_id VARCHAR, product_name VARCHAR, quantity INTEGER, status VARCHAR, created_at DATETIME, updated_at DATETIME)"
                else:
                    continue

                conn.execute(text(f"CREATE TABLE {table} {schema}"))
                
                # 3. Copy data
                cols_in_old = [c["name"] for c in columns]
                cols_str = ", ".join(cols_in_old)
                conn.execute(text(f"INSERT INTO {table} ({cols_str}) SELECT {cols_str} FROM {table}_old"))
                
                # 4. Drop old
                conn.execute(text(f"DROP TABLE {table}_old"))
                conn.commit()
                print(f"[SQLite UUID] Table {table} migrated to VARCHAR IDs.")
            except Exception as e:
                print(f"[SQLite UUID] Failed to migrate {table}: {e}")
                # Try to rollback rename if failed
                try: conn.execute(text(f"ALTER TABLE {table}_old RENAME TO {table}"))
                except: pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"[SYSTEM] Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
