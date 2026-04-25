import sys
import json
from app.database import SessionLocal
from app.models import Shop, InventoryItem, PendingRequest
from app.services.router_engine import RouterEngine

def run_tests():
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter_by(email='testretail@example.com').first()
        if not shop:
            shop = Shop(
                shop_name="Test Retail",
                owner_name="Test Owner",
                email="testretail@example.com",
                phone_number="9999999998",
                password_hash="hash"
            )
            db.add(shop)
            db.commit()
            db.refresh(shop)

        tests = [
            ("A", "Restaurant", "iphone", "menu"),
            ("B", "Mobile Shop", "iphone", "send your request to the shop owner"),
            ("C", "Mobile Shop", "charger", "send your request to the shop owner"),
            ("D", "Salon", "haircut tomorrow 5 pm", "booking request"),
            ("E", "Mixed General Store", "water bottle", "send your request to the shop owner")
        ]

        results = []
        for case, cat, msg, expected in tests:
            shop.business_category = cat
            db.commit()
            
            # Use distinct customer phones to reset session
            reply = RouterEngine.process_message(db, shop.id, f"123000{case}", msg)
            passed = expected.lower() in reply.lower()
            
            results.append({
                "case": case,
                "category": cat,
                "msg": msg,
                "reply": reply,
                "passed": passed
            })

        with open("retail_results.json", "w") as f:
            json.dump(results, f, indent=2)
            
        print("Test completed successfully.")

    finally:
        db.rollback()
        db.close()

if __name__ == "__main__":
    run_tests()
