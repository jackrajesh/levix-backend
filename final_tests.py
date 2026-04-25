import sys
import json
import random
from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.router_engine import RouterEngine

def run_tests():
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter_by(email='testretail@example.com').first()
        
        items = ['Biryani', 'Fried Rice', 'Coke']
        for name in items:
            if not db.query(InventoryItem).filter_by(shop_id=shop.id, name=name).first():
                db.add(InventoryItem(shop_id=shop.id, name=name, price=100.0, quantity=100))
        db.commit()

        # Generate a consistent phone number for A and B
        phone_ab = f'99000{random.randint(1000,9999)}'

        tests = [
            ("TEST_A (Full Delivery Checkout)", phone_ab, ["hello", "menu", "2 fried rice, 1 coke", "cart", "checkout", "delivery", "Flat 4B, Central Avenue, near the metro station", "yes"]),
            ("TEST_B (Order Tracking Same Number)", phone_ab, ["track my order"]),
            ("TEST_C (Unknown Request YES)", f'99000{random.randint(1000,9999)}', ["water packet", "yes"]),
            ("TEST_D (Clear Cart Empty Yes)", f'99000{random.randint(1000,9999)}', ["clear cart", "yes"]),
            ("TEST_E (Change Quantity & Reduce)", f'99000{random.randint(1000,9999)}', ["2 biryani", "change to 3", "remove 1", "total"]),
            ("TEST_F (Stray No)", f'99000{random.randint(1000,9999)}', ["no"])
        ]

        results = {}
        for test_name, phone, messages in tests:
            results[test_name] = []
            
            for msg in messages:
                reply = RouterEngine.process_message(db, shop.id, phone, msg)
                results[test_name].append({
                    'user': msg,
                    'bot': reply
                })

        with open('final_tests.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    finally:
        db.close()

run_tests()
