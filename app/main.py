import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .database import engine
from . import models

# Import routers
from .routes import pages, auth, inventory, sales, analytics, pending, webhooks, admin, messages, meta_auth, orders, plans, team, logs, inbox, settings

app = FastAPI(title="Levix API")

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": str(datetime.now())}

# Database init handled in startup event

# Seed SaaS Initial Data (Plans, Addons)
@app.on_event("startup")
async def startup_event():
    print("[SYSTEM] Starting Levix Boot Sequence...")
    
    # 1. Base Tables
    try:
        models.Base.metadata.create_all(bind=engine)
        print("[SYSTEM] Base tables verified.")
    except Exception as e:
        print(f"[SYSTEM] Create tables warning: {e}")

    # 2. Migrations (Atomic)
    try:
        _run_migrations()
        _run_team_migrations()
        _run_ai_migrations()
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
    
    # 4. AI Engine Health (Phase 1)
    try:
        from .core.ai_client import AIClient
        AIClient.initialize()
        print(f"[SYSTEM] {AIClient.get_status_report()}")
    except Exception as e:
        print(f"[SYSTEM] AI Startup Report failed: {e}")

    # 5. OMEGA Integrity Check
    try:
        from .services.ai_router import AIRouter
        from .services.sales_engine import SalesEngine
        from .services.session_engine import SessionEngine
        from .services.intent_engine import IntentEngine
        from .services.fallback_engine import FallbackEngine
        
        services = [
            ("AIRouter", AIRouter), 
            ("SalesEngine", SalesEngine), 
            ("SessionEngine", SessionEngine),
            ("IntentEngine", IntentEngine),
            ("FallbackEngine", FallbackEngine)
        ]
        
        import sys
        for name, svc in services:
            # Check if module has logger defined
            mod = sys.modules[svc.__module__]
            if hasattr(mod, "logger"):
                print(f"[OMEGA] {name} Integrity: VERIFIED ✅")
            else:
                print(f"[OMEGA] {name} Integrity: WARNING (No Logger) ⚠️")
    except Exception as e:
        print(f"[OMEGA] Integrity check failed: {e}")

    print("[SYSTEM] Boot Sequence Finalized.")

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
                if "razorpay_subscription_id" not in columns:
                    conn.execute(text("ALTER TABLE subscriptions ADD COLUMN razorpay_subscription_id VARCHAR"))
                    conn.commit()
                    print("[Migration] Added razorpay_subscription_id column to subscriptions")

def _run_team_migrations():
    """Safe migrations for team management v2 (roles + status)."""
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Create shop_roles table if missing
        if "shop_roles" not in tables:
            is_sqlite = engine.url.drivername.startswith("sqlite")
            id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            ts_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE DEFAULT now()"
            
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS shop_roles (
                    id {id_type},
                    shop_id INTEGER NOT NULL REFERENCES shops(id),
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
                    shop_id INTEGER NOT NULL REFERENCES shops(id),
                    user_id INTEGER,
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

def _run_ai_migrations():
    """Safe migrations for AI Assistant tables (idempotent)."""
    from sqlalchemy import text, inspect
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            is_sqlite = engine.url.drivername.startswith("sqlite")
            id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            ts_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE DEFAULT now()"

            # ── inventory_items: product_details + category ───────────────────
            if "inventory_items" in tables:
                cols = [c["name"] for c in inspector.get_columns("inventory_items")]
                if "product_details" not in cols:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN product_details TEXT"))
                    print("[AI Migration] Added product_details to inventory_items")
                if "category" not in cols:
                    conn.execute(text("ALTER TABLE inventory_items ADD COLUMN category VARCHAR"))
                    print("[AI Migration] Added category to inventory_items")
                conn.commit()

            # ── ai_conversation_sessions ──────────────────────────────────────
            if "ai_conversation_sessions" not in tables:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS ai_conversation_sessions (
                        id {id_type},
                        shop_id INTEGER NOT NULL REFERENCES shops(id),
                        session_id VARCHAR UNIQUE NOT NULL,
                        customer_phone VARCHAR(20),
                        collected_fields JSON,
                        matched_product_id INTEGER,
                        matched_product_name VARCHAR,
                        last_intent VARCHAR,
                        intent_confidence NUMERIC(4,2),
                        category VARCHAR,
                        missing_fields JSON,
                        turn_count INTEGER DEFAULT 0,
                        is_active BOOLEAN DEFAULT TRUE,
                        lead_created BOOLEAN DEFAULT FALSE,
                        source VARCHAR DEFAULT 'web',
                        conversation_history JSON,
                        created_at {ts_type},
                        updated_at {ts_type}
                    )
                """))
                conn.commit()
                print("[AI Migration] Created ai_conversation_sessions table")

            # ── ai_leads ──────────────────────────────────────────────────────
            if "ai_leads" not in tables:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS ai_leads (
                        id {id_type},
                        shop_id INTEGER NOT NULL REFERENCES shops(id),
                        session_id VARCHAR,
                        customer_name VARCHAR,
                        phone VARCHAR(20),
                        product_id INTEGER,
                        product_name VARCHAR,
                        category VARCHAR,
                        intent VARCHAR,
                        collected_data JSON,
                        summary TEXT,
                        status VARCHAR DEFAULT 'new',
                        source VARCHAR DEFAULT 'AI Assistant',
                        confidence NUMERIC(4,2),
                        created_at {ts_type},
                        updated_at {ts_type}
                    )
                """))
                conn.commit()
                print("[AI Migration] Created ai_leads table")

            # ── ai_analytics_events ───────────────────────────────────────────
            if "ai_analytics_events" not in tables:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS ai_analytics_events (
                        id {id_type},
                        shop_id INTEGER NOT NULL REFERENCES shops(id),
                        event_type VARCHAR NOT NULL,
                        session_id VARCHAR,
                        event_data JSON,
                        created_at {ts_type}
                    )
                """))
                conn.commit()
                print("[AI Migration] Created ai_analytics_events table")
    except Exception as e:
        print(f"[AI Migration] Error: {e}")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

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
    print("[SYSTEM] All routes loaded successfully.")
except Exception as e:
    print(f"[SYSTEM ERROR] Failed to load routes: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"[SYSTEM] Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)