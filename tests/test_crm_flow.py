import os
import sys
import uuid
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from app.database import SessionLocal
from app import models
from app.services.guided_conversation_engine import GuidedConversationEngine

def test_crm_flow():
    print("\n--- RUNNING CRM FLOW TEST ---\n")
    db = SessionLocal()
    
    # Setup test shop
    shop_id = "crm_test_shop"
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        shop = models.Shop(id=shop_id, shop_name="CRM Test Shop", owner_name="Owner", email="crm@test.com", password_hash="hash")
        db.add(shop)
        db.commit()

    phone = f"9198765{str(int(time.time()))[-4:]}"
    print(f"[TEST] Using test phone: {phone}")

    # Process inquiry flow
    res1 = GuidedConversationEngine.process_message(db, shop.id, phone, "hi")
    print(f"Reply 1: {res1}")
    res2 = GuidedConversationEngine.process_message(db, shop.id, phone, "btn_inquiry")
    print(f"Reply 2: {res2}")
    res3 = GuidedConversationEngine.process_message(db, shop.id, phone, "I am looking for a red shirt.")
    print(f"Reply 3: {res3}")
    res4 = GuidedConversationEngine.process_message(db, shop.id, phone, "John Doe")
    print(f"Reply 4: {res4}")
    
    # Check ConversationSession
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.shop_id == shop.id,
        models.ConversationSession.customer_phone == phone
    ).first()
    
    if session:
        print(f"✅ Success: ConversationSession created! ID: {session.id}, Name: {session.customer_name}, Status: {session.status}")
        messages = db.query(models.ConversationMessage).filter(
            models.ConversationMessage.session_id == session.id
        ).all()
        print(f"Messages found in session:")
        for m in messages:
            print(f"  [{m.sender_type}] {m.message}")
    else:
        print("❌ Error: ConversationSession was not created!")
        
    db.close()

if __name__ == "__main__":
    test_crm_flow()
