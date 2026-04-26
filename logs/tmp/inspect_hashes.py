import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import Shop
import re

def inspect_hashes():
    db = SessionLocal()
    try:
        shops = db.query(Shop).all()
        print(f"Found {len(shops)} shops.")
        for shop in shops:
            h = shop.password_hash
            is_bcrypt = bool(re.match(r"^\$2[aby]\$.{53}$", h)) if h else False
            status = "VALID BCRYPT" if is_bcrypt else "INVALID / PLAIN TEXT"
            # Masking part of the hash for security but showing prefix
            display_hash = h[:10] + "..." if h else "None"
            print(f"ID: {shop.id}, Email: {shop.email}, Hash: {display_hash}, Status: {status}")
    finally:
        db.close()

if __name__ == "__main__":
    inspect_hashes()
