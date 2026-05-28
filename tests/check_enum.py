from sqlalchemy import create_engine, text
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path('config/.env'))
db_url = os.getenv('DATABASE_URL').replace('postgres://', 'postgresql://')
engine = create_engine(db_url)

with engine.connect() as conn:
    try:
        res = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = 'OrderStatus'")).fetchall()
        print(f"OrderStatus Enum: {[r[0] for r in res]}")
    except Exception as e:
        print(f"Error: {e}")
