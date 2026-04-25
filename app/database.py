import os
import re
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Define BASE_DIR at the top
BASE_DIR = Path(__file__).resolve().parent.parent

# Explicitly load .env from project root
load_dotenv(BASE_DIR / "config" / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
SQLITE_DB_PATH = DATA_DIR / "levix.db"

# Prioritize environment variable, fallback to SQLite
DATABASE_URL = os.getenv("DATABASE_URL")

# Render compatibility: postgres:// must be postgresql:// for SQLAlchemy
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    print("[LEVIX WARNING] DATABASE_URL not found, falling back to local SQLite.")
    DATABASE_URL = f"sqlite:///{SQLITE_DB_PATH}"

# Security Logging: Mask password in DATABASE_URL
def mask_db_url(url: str) -> str:
    try:
        return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1***\3", url)
    except:
        return "DATABASE_URL_MASK_FAILED"

print(f"[LEVIX] Booting with Database: {mask_db_url(DATABASE_URL)}")

# Configure engine arguments
connect_args: dict[str, Any] = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30
elif DATABASE_URL and ("render.com" in DATABASE_URL or "neon.tech" in DATABASE_URL or "supabase" in DATABASE_URL):
    connect_args["sslmode"] = "require"

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300
)

# SQLite performance and concurrency tuning
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