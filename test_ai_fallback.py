import os
# Force AI to fail
os.environ["GEMINI_API_KEY"] = "fake"
os.environ["OPENROUTER_API_KEY"] = "fake"

from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.ai_router import AIRouter
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

        queries = [
            "Chicken biryani iruka?",
            "Coke",
            "Need dinner for 5 under 700"
        ]
        for q in queries:
            print(f"\n--- Testing: {q} ---")
            reply = AIRouter.process_message(db, shop.id, "1234567890", q)
            print(f"Reply: {reply}")
finally:
    db.close()
