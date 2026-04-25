from app.database import engine
from sqlalchemy import text

def check():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'ai_leads'"))
        cols = [r[0] for r in res]
        print(f"Columns: {cols}")

if __name__ == "__main__":
    import os
    import sys
    sys.path.append(os.getcwd())
    check()
