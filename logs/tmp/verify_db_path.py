import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import DATABASE_URL, DATA_DIR, SQLITE_DB_PATH

print(f"Resolved DATABASE_URL: {DATABASE_URL}")
print(f"DATA_DIR exists: {DATA_DIR.exists()}")
print(f"SQLITE_DB_PATH: {SQLITE_DB_PATH}")
print(f"Database file exists at stable path: {SQLITE_DB_PATH.exists()}")

if "sqlite" in DATABASE_URL:
    if os.path.isabs(DATABASE_URL.replace("sqlite:///", "")):
        print("SUCCESS: Database path is absolute.")
    else:
        print("FAILED: Database path is NOT absolute.")
else:
    print("Remote database detected, skipping absolute path check.")
