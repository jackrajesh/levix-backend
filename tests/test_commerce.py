import os
# Force AI to fail
os.environ["GEMINI_API_KEY"] = "fake"
os.environ["OPENROUTER_API_KEY"] = "fake"

from app.database import SessionLocal
from app.models import Shop, InventoryItem, Product
from app.services.ai_router import AIRouter
from app.services.session_engine import SessionEngine
import logging
import sys
import io
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.INFO)

db = SessionLocal()
try:
    # 1. Setup Test Store
    shop = db.query(Shop).filter_by(email="test@example.com").first()
    if not shop:
        shop = Shop(shop_name="Test Store", owner_name="Tester", email="test@example.com", password_hash="hash")
        db.add(shop)
        db.commit()
        db.refresh(shop)

    # 2. Setup Inventory & Products
    items = [
        {"name": "Chicken Biryani", "price": 120, "qty": 10},
        {"name": "Mushroom Biryani", "price": 100, "qty": 5},
        {"name": "Coca Cola", "price": 40, "qty": 20}
    ]
    
    from sqlalchemy.sql import func
    for item in items:
        existing = db.query(InventoryItem).filter_by(shop_id=shop.id, name=item["name"]).first()
        if not existing:
            item_id = str(uuid.uuid4())
            db.add(InventoryItem(id=item_id, shop_id=shop.id, name=item["name"], price=item["price"], quantity=item["qty"], status="available"))
            db.add(Product(id=item_id, shop_id=shop.id, name=item["name"], price=item["price"], quantity=item["qty"], status="available", created_at=func.now(), updated_at=func.now()))
    db.commit()

    phone = "1234567890"
    
    # 3. Reset Session
    sess = SessionEngine.get_session(db, shop.id, phone)
    sess.collected_fields = {}
    sess.matched_product_id = None
    db.commit()

    # 4. Test Queries
    queries = [
        "Chicken biryani iruka",
        "Coke iruka",
        "Need dinner for 5 under 700",
        "Less spicy",
        "Add coke",
        "yes",
    ]
    
    for q in queries:
        print(f"\n--- Testing: {q} ---")
        reply = AIRouter.process_message(db, shop.id, phone, q)
        try:
            print(f"Reply: {reply}")
        except UnicodeEncodeError:
            print(f"Reply: {reply.encode('ascii', 'ignore').decode('ascii')} (Unicode suppressed)")
        
    # 5. Test ORDER token
    sess = SessionEngine.get_session(db, shop.id, phone)
    token = sess.collected_fields.get("last_order_token")
    if token:
        print(f"\n--- Testing: ORDER {token} ---")
        reply = AIRouter.process_message(db, shop.id, phone, f"ORDER {token}")
        print(f"Reply: {reply}")
    else:
        print("No token found to test.")

finally:
    db.close()
