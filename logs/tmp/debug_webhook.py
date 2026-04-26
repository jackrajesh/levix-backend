import sys
import os
from sqlalchemy.orm import Session
from fastapi import Request
import unittest
from unittest.mock import MagicMock

# Add the project root to sys.path
sys.path.append(os.getcwd())

from app.database import Base, engine, SessionLocal
from app import models
from app.routes.webhooks import webhook_endpoint, WebhookRequest

def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Clear existing data
    try:
        db.query(models.PasswordResetToken).delete()
        db.query(models.SalesRecord).delete()
        db.query(models.PendingRequest).delete()
        db.query(models.LogEntry).delete()
        db.query(models.InventoryAlias).delete()
        db.query(models.InventoryItem).delete()
        db.query(models.Shop).delete()
        db.commit()
    except:
        db.rollback()
    
    # Check if shop exists
    shop = db.query(models.Shop).filter(models.Shop.email == "test@shop.com").first()
    if not shop:
        shop = models.Shop(shop_name="Test Shop", email="test@shop.com", password_hash="hash", owner_name="Owner")
        db.add(shop)
        db.commit()
        db.refresh(shop)
    
    # Create an item
    item = models.InventoryItem(
        shop_id=shop.id,
        name="Almond 50g",
        quantity=10,
        price=50.0,
        status="available"
    )
    db.add(item)
    db.flush()
    
    db.add(models.InventoryAlias(inventory_id=item.id, alias="almond"))
    db.commit()
    return db, shop.id

async def debug_webhook():
    db, shop_id = setup_db()
    
    request_data = WebhookRequest(customer_message="Do you have almond?", shop_id=shop_id)
    
    print("Calling webhook_endpoint...")
    response = await webhook_endpoint(request_data, db)
    
    print(f"Response: {response}")
    
    if "...." in response["reply"]:
        print("FAILED: Found '....' in reply!")
    else:
        print("SUCCESS: No '....' found in reply.")
    
    if "Price: ₹50" in response["reply"]:
        print("SUCCESS: Found price in reply.")
    else:
        print("FAILED: Price not found in reply!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(debug_webhook())
