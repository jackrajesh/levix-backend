import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import Shop
from app.auth import hash_password

def reset_users():
    db = SessionLocal()
    try:
        shops = db.query(Shop).all()
        print(f"Resetting {len(shops)} users to default password 'levix123' (BCRYPT)...")
        for shop in shops:
            # We hash with bcrypt because that's our now-primary scheme
            shop.password_hash = hash_password("levix123")
            print(f"Reset user: {shop.email}")
        db.commit()
        print("Success! All users reset to 'levix123' using bcrypt.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    confirm = input("Are you sure you want to reset ALL shop passwords to 'levix123'? (y/n): ")
    if confirm.lower() == 'y':
        reset_users()
    else:
        print("Aborted.")
