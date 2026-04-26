from app.database import engine
from sqlalchemy import text

def check():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT current_schema()"))
        print(f"Schema: {res.fetchone()[0]}")

if __name__ == "__main__":
    import os
    import sys
    sys.path.append(os.getcwd())
    check()
