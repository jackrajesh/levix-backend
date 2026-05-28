from sqlalchemy import create_engine, text
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path('config/.env'))
db_url = os.getenv('DATABASE_URL').replace('postgres://', 'postgresql://')
engine = create_engine(db_url)

with engine.connect() as conn:
    try:
        enums = conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'")).fetchall()
        for enum in enums:
            name = enum[0]
            labels = conn.execute(text(f"SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = '{name}'")).fetchall()
            print(f"{name} Enum: {[r[0] for r in labels]}")
    except Exception as e:
        print(f"Error: {e}")
