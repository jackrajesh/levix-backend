from app.database import SessionLocal
from app.models import Shop, InventoryItem
from app.services.product_service import fuzzy_match_product
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
            "Chicken biryani",
            "Chicken briyani",
            "Briyani",
            "Rose milk",
            "Mushroom biryani",
            "ckn biryani"
        ]
        for q in queries:
            print(f"\n--- Testing: {q} ---")
            item = fuzzy_match_product(q, db, shop.id)
            if item:
                print(f"Matched: {item.name}")
            else:
                print("No match")
finally:
    db.close()
