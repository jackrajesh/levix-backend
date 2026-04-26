from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app import models
from app.services.product_service import fuzzy_match_product, normalize_product
from app.routes.messages import generate_controlled_reply

def test_final_flow():
    db = SessionLocal()
    shop_id = 1 # Update with a valid shop_id from your DB
    
    print("--- Testing Normalization ---")
    print(f"2 milk packets -> {normalize_product('2 milk packets')}")
    print(f"paal 1kg -> {normalize_product('paal 1kg')}")
    
    print("\n--- Testing Response Variations ---")
    data_friendly = {"intent": "low_stock", "tone": "friendly", "product": "Milk", "price": 50, "quantity": 3}
    data_casual = {"intent": "low_stock", "tone": "casual", "product": "Milk", "price": 50, "quantity": 3}
    
    print(f"Friendly: {generate_controlled_reply(data_friendly)}")
    print(f"Casual: {generate_controlled_reply(data_casual)}")
    
    print("\n--- Testing Stock States ---")
    # Fetch a product
    item = db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == shop_id).first()
    if item:
        print(f"Product: {item.name}, Qty: {item.quantity}")
        from app.services.product_service import get_product_status
        print(f"Status: {get_product_status(item)}")
    
    db.close()

if __name__ == "__main__":
    test_final_flow()
