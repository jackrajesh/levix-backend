import os
import re
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Define PROJECT_ROOT at the top (from app/core/database.py -> parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 1. Load Environment Variables
ENV_PATH = PROJECT_ROOT / "config" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    # Fallback to project root .env if config/.env is missing
    load_dotenv(PROJECT_ROOT / ".env")

# 2. Extract and Normalize DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

if DATABASE_URL:
    # Support multiple postgres variants and normalize for SQLAlchemy
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        pass
    elif DATABASE_URL.startswith("postgresql+psycopg2://"):
        pass
    
    IS_CLOUD_DB = any(x in DATABASE_URL for x in ["neon.tech", "render.com", "supabase", "rds.amazonaws.com"])
    PROVIDER_NAME = "Neon PostgreSQL" if "neon.tech" in DATABASE_URL else "Cloud PostgreSQL" if IS_CLOUD_DB else "Remote PostgreSQL"
    
elif DEV_MODE:
    DATA_DIR = PROJECT_ROOT / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DATABASE_URL = f"sqlite:///{DATA_DIR / 'levix.db'}"
    PROVIDER_NAME = "SQLite (Local Dev)"
else:
    print("\n" + "!"*60)
    print("[LEVIX CRITICAL ERROR] DATABASE_URL missing. Cloud DB required.")
    print("If you are a developer, set DEV_MODE=true in your .env for local SQLite.")
    print("!"*60 + "\n")
    raise ConnectionError("DATABASE_URL not found in environment.")

# 3. Security Masking for Logs
def mask_db_url(url: str) -> str:
    try:
        # Mask user:password part
        return re.sub(r"(://)([^@]+)(@)", r"\1***\3", url)
    except:
        return "DATABASE_URL_MASK_FAILED"

print(f"[LEVIX] Database Provider: {PROVIDER_NAME}")
print(f"[LEVIX] Connection Target: {mask_db_url(DATABASE_URL)}")

# 4. Configure Engine
connect_args: dict[str, Any] = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30
elif "postgresql" in DATABASE_URL:
    # Most cloud providers (Neon, Render) require SSL
    if any(x in DATABASE_URL for x in ["neon.tech", "render.com", "supabase"]):
        connect_args["sslmode"] = "require"

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10 if not DATABASE_URL.startswith("sqlite") else None,
        max_overflow=20 if not DATABASE_URL.startswith("sqlite") else None
    )
    # Test connection immediately
    with engine.connect() as conn:
        print("[LEVIX] Connection: SUCCESS [OK]")
except Exception as e:
    print(f"[LEVIX ERROR] Database Connection Failed: {e}")
    if not DEV_MODE:
        raise

# 5. SQLite performance tuning
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()