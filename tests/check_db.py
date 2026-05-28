import sqlite3
import os

db_path = "app/data/levix.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    print("Tables:", [t[0] for t in tables])
    
    for table in [t[0] for t in tables]:
        print(f"\nSchema for {table}:")
        info = cursor.execute(f"PRAGMA table_info({table});").fetchall()
        for col in info:
            print(col)
    conn.close()
else:
    print(f"File {db_path} not found")
