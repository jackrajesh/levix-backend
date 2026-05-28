import os
import sys
import json
import logging
from unittest.mock import patch
import asyncio

# Setup path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.database import SessionLocal, Base, engine
from app import models
from app.routes.webhooks import webhook_endpoint
from fastapi import Request

# Setup dummy testing db and shop
db = SessionLocal()

# We want to catch the whatsapp messages
sent_messages = []
def fake_send_whatsapp_message(shop, sender, message):
    sent_messages.append(message)

async def simulate_webhook(phone, message_text):
    global sent_messages
    sent_messages = []
    
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": f"test_msg_{os.urandom(4).hex()}",
                                    "from": phone,
                                    "type": "text",
                                    "text": {"body": message_text}
                                }
                            ],
                            "metadata": {
                                "phone_number_id": "test_phone_id"
                            }
                        }
                    }
                ]
            }
        ]
    }
    
    class DummyRequest:
        async def json(self):
            return payload
    
    req = DummyRequest()
    with patch('app.routes.webhooks.send_whatsapp_message', side_effect=fake_send_whatsapp_message):
        res = await webhook_endpoint(req, db=db)
    
    # Read session state
    session = db.query(models.AIConversationSession).filter_by(customer_phone=phone).first()
    state = session.collected_fields if session else {}
    
    return {
        "webhook_response": res,
        "bot_replies": list(sent_messages),
        "session_state": state
    }

async def run_tests():
    # Setup Data
    # Find or create shop
    shop = db.query(models.Shop).filter_by(whatsapp_phone_number_id="test_phone_id").first()
    if not shop:
        shop = models.Shop(
            shop_name="Test Shop", 
            owner_name="Owner", 
            email="test@shop.com", 
            password_hash="hash",
            whatsapp_phone_number_id="test_phone_id"
        )
        db.add(shop)
        db.commit()
        db.refresh(shop)
        
        # Add products
        p1 = models.InventoryItem(shop_id=shop.id, name="Chicken Biryani", quantity=50, price=200, status="available", category="food")
        p2 = models.InventoryItem(shop_id=shop.id, name="Coke", quantity=50, price=50, status="available", category="drinks")
        db.add(p1)
        db.add(p2)
        db.commit()

    phone = "1234567890"
    
    # Reset Session
    db.query(models.AIConversationSession).filter_by(customer_phone=phone).delete()
    db.query(models.CustomerProfile).filter_by(customer_phone=phone).delete()
    db.commit()

    results = []
    
    scenarios = [
        ("S1: Multi-line and Alias", ["Add 2 coca cola\\nno ice", "what's in cart"]),
        ("S2: Confirmation Guard", ["add 2 chicken biryani", "pickup", "change"]),
        ("S3: Combo Priority", ["Need dinner for 5 under 700"]),
        ("S4: Multi-line modifiers", ["Add biryani\\nless spicy\\nno onion\\nextra gravy"])
    ]

    for name, msgs in scenarios:
        print(f"Running {name}...")
        # Reset Session per scenario
        db.query(models.AIConversationSession).filter_by(customer_phone=phone).delete()
        db.commit()
        
        scenario_results = []
        for m in msgs:
            # We must fix newline so simulate_webhook gets multiline
            m_unscaped = m.replace("\\n", "\n")
            res = await simulate_webhook(phone, m_unscaped)
            scenario_results.append({
                "message": m,
                "replies": res['bot_replies'],
                "state": res['session_state']
            })
        results.append({"scenario": name, "steps": scenario_results})
    
    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_tests())
