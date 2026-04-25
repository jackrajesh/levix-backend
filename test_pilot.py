import os
os.environ["GEMINI_API_KEY"] = "fake"
os.environ["OPENROUTER_API_KEY"] = "fake"

from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.ai_router import AIRouter
from app.services.session_engine import SessionEngine
from app.services.sales_engine import SalesEngine
import logging
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.ERROR)

db = SessionLocal()
try:
    shop = db.query(Shop).first()
    if shop:
        shop.settings = {
            "delivery_enabled": True,
            "free_delivery_threshold": 500,
            "delivery_fee": 50
        }
        db.commit()
        phone = "5555555555"
        
        # Reset session
        sess = SessionEngine.get_session(db, shop.id, phone)
        sess.collected_fields = {}
        db.commit()

        queries = [
            "Add 1 chicken biryani",
            "ORDER",
            "delivery",
            "456 Test Ave"
        ]
        
        print("--- Testing Delivery Pricing (Under 500) ---")
        for q in queries:
            reply = AIRouter.process_message(db, shop.id, phone, q)
            print(f"Q: {q} -> A: {reply}")
            
        # Reset session
        sess.collected_fields = {}
        db.commit()

        queries_free = [
            "Add 5 chicken biryani",
            "ORDER",
            "delivery",
            "456 Test Ave"
        ]
        
        print("\n--- Testing Delivery Pricing (Over 500) ---")
        for q in queries_free:
            reply = AIRouter.process_message(db, shop.id, phone, q)
            print(f"Q: {q} -> A: {reply}")
            
        print("\n--- Admin Reports ---")
        reports = SalesEngine.get_admin_reports(db, shop.id)
        print(json.dumps(reports, indent=2))
finally:
    db.close()
