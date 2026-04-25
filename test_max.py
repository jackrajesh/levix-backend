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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.ERROR)

db = SessionLocal()
try:
    shop = db.query(Shop).first()
    if shop:
        phone = "8888888888"
        
        # Setup stock
        coke = db.query(InventoryItem).filter_by(name="Coca Cola").first()
        if coke:
            coke.quantity = 0  # Make it OOS
        pepsi = db.query(InventoryItem).filter_by(name="Pepsi").first()
        if not pepsi:
            pepsi = InventoryItem(shop_id=shop.id, name="Pepsi", price=40, quantity=10, category="drinks", status="available")
            db.add(pepsi)
        db.commit()

        # Reset session
        sess = SessionEngine.get_session(db, shop.id, phone)
        sess.collected_fields = {}
        db.commit()

        queries = [
            "Add 1 chicken biryani",
            "make biryani 3",
            "Add 1 rose milk",
            "change rose milk to 4",
            "add coke", # Should trigger auto-replace
            "ORDER",
            "delivery",
            "123 Fake Street"
        ]
        
        for q in queries:
            print(f"\n--- Testing: {q} ---")
            reply = AIRouter.process_message(db, shop.id, phone, q)
            print(f"Reply: {reply}")
            
        print("\n--- Dashboard Metrics ---")
        metrics = SalesEngine.get_dashboard_metrics(db, shop.id)
        print("Daily Revenue:", metrics["daily_revenue"])
        print("Abandoned Carts:", metrics["abandoned_carts"])
finally:
    db.close()
