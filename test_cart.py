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
        phone = "1234567890"
        
        # Reset session
        sess = SessionEngine.get_session(db, shop.id, phone)
        sess.collected_fields = {}
        db.commit()

        queries = [
            "Add 2 chicken biryani",
            "less spicy",
            "Add coke",
            "less spicy",
            "remove coke",
            "Add 1 Rose Milk",
            "ORDER"
        ]
        
        for q in queries:
            print(f"\n--- Testing: {q} ---")
            reply = AIRouter.process_message(db, shop.id, phone, q)
            print(f"Reply: {reply}")
finally:
    db.close()
