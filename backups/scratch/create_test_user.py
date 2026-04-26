from app.database import SessionLocal
from app import models, auth
import sys

def create_test_user():
    db = SessionLocal()
    try:
        email = "test@levix.com"
        password = "password123"
        
        existing = db.query(models.Shop).filter(models.Shop.email == email).first()
        if existing:
            print(f"Test user {email} already exists.")
            return
            
        hashed_password = auth.hash_password(password)
        new_shop = models.Shop(
            shop_name="Levix Test Store",
            owner_name="Test Owner",
            email=email,
            phone_number="1234567890",
            password_hash=hashed_password
        )
        db.add(new_shop)
        db.commit()
        print(f"Created test user: {email} / {password}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    create_test_user()
