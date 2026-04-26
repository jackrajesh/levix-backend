from app.database import engine
from sqlalchemy import text

def check():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'ai_leads'"))
        for r in res:
            print(f"{r[0]}: {r[1]}")

if __name__ == "__main__":
    import os
    import sys
    sys.path.append(os.getcwd())
    check()
