import os
# Force AI to fail
os.environ["GEMINI_API_KEY"] = "fake"
os.environ["OPENROUTER_API_KEY"] = "fake"

from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.ai_router import AIRouter
from app.services.session_engine import SessionEngine
import logging
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.INFO)

db = SessionLocal()
try:
    shop = db.query(Shop).first()
    if shop:
        existing = db.query(InventoryItem).filter_by(shop_id=shop.id).all()
        if not any("biryani" in e.name.lower() for e in existing):
            db.add(InventoryItem(shop_id=shop.id, name="Chicken Biryani", price=120, quantity=10, status="available"))
            db.add(InventoryItem(shop_id=shop.id, name="Rose Milk", price=40, quantity=10, status="available"))
            db.add(InventoryItem(shop_id=shop.id, name="Mushroom Biryani", price=100, quantity=10, status="available"))
            db.commit()

        # Ensure Coke exists
        if not any("coca cola" in e.name.lower() for e in existing):
            db.add(InventoryItem(shop_id=shop.id, name="Coca Cola", price=40, quantity=2, status="low_stock"))
            db.commit()

        phone = "1234567890"
        
        # Reset session
        sess = SessionEngine.get_session(db, shop.id, phone)
        sess.collected_fields = {}
        sess.matched_product_id = None
        db.commit()

        queries = [
            "Chicken biryani iruka",
            "Coke iruka",
            "Need dinner for 5 under 700",
            "Less spicy",
            "Add coke",
        ]
        
        for q in queries:
            print(f"\n--- Testing: {q} ---")
            reply = AIRouter.process_message(db, shop.id, phone, q)
            print(f"Reply: {reply}")
            
        # Test ORDER token
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
