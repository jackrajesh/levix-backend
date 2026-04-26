import sys
import json
import random
from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.router_engine import RouterEngine

def run_tests():
    db = SessionLocal()
    try:
        # A. Restaurant mode
        shop_rest = db.query(Shop).filter_by(email='restaurant@example.com').first()
        if not shop_rest:
            shop_rest = Shop(shop_name="Test Restaurant", owner_name="Owner", email="restaurant@example.com", password_hash="hash", business_category="Restaurant", business_mode="product")
            db.add(shop_rest)
            db.commit()
            db.refresh(shop_rest)
        
        # B. Mobile Shop mode
        shop_mob = db.query(Shop).filter_by(email='mobileshop@example.com').first()
        if not shop_mob:
            shop_mob = Shop(shop_name="Test Mobile Shop", owner_name="Owner", email="mobileshop@example.com", password_hash="hash", business_category="Mobile Shop", business_mode="product")
            db.add(shop_mob)
            db.commit()
            db.refresh(shop_mob)

        # C. Salon mode
        shop_salon = db.query(Shop).filter_by(email='salon@example.com').first()
        if not shop_salon:
            shop_salon = Shop(shop_name="Test Salon", owner_name="Owner", email="salon@example.com", password_hash="hash", business_category="Salon", business_mode="service")
            db.add(shop_salon)
            db.commit()
            db.refresh(shop_salon)

        items = ['Biryani', 'Fried Rice', 'Coke']
        for name in items:
            if not db.query(InventoryItem).filter_by(shop_id=shop_rest.id, name=name).first():
                db.add(InventoryItem(shop_id=shop_rest.id, name=name, price=100.0, quantity=100, type="product"))
        db.commit()

        tests = [
            ("TEST_A (Restaurant - Unrelated)", shop_rest, f'99000{random.randint(1000,9999)}', ["iphone"]),
            ("TEST_B (Mobile Shop - Valid)", shop_mob, f'99000{random.randint(1000,9999)}', ["iphone", "charger", "biryani"]),
            ("TEST_C (Food Shop - Cart & Checkout)", shop_rest, f'99000{random.randint(1000,9999)}', ["2 fried rice, 1 coke", "checkout", "pickup", "yes"]),
            ("TEST_D (Salon - Service Booking)", shop_salon, f'99000{random.randint(1000,9999)}', ["haircut tomorrow 5pm", "yes"]),
            ("TEST_E (Address Merging)", shop_rest, f'99000{random.randint(1000,9999)}', ["coke", "checkout", "delivery", "Arasu Colony", "Karuppana Samy Street", "Near Church", "yes"]),
            ("TEST_F (Missing Request)", shop_rest, f'99000{random.randint(1000,9999)}', ["water packet", "yes"]),
        ]

        # Add Track Order tests for C and D
        tests.append(("TEST_G (Track Order)", shop_rest, tests[2][2], ["track my order"]))
        tests.append(("TEST_H (Track Booking)", shop_salon, tests[3][2], ["track my order"]))

        results = {}
        for test_name, shop, phone, messages in tests:
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
