import sys
import os
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.database import Base, DATABASE_URL
from app import models
from app.services.guided_conversation_engine import GuidedConversationEngine
from datetime import datetime, timezone

def test_non_blocking_lifecycle():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    # Run dynamic schema migrations on test DB
    from app.main import _run_inquiry_lifecycle_migrations
    _run_inquiry_lifecycle_migrations()
    
    # 1. Setup Test Shop
    shop_id = "lifecycle_test_shop"
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        shop = models.Shop(id=shop_id, shop_name="Lifecycle Test Shop", shop_category="restaurant")
        db.add(shop)
        db.commit()
        
    phone = "919999999999"
    
    # Clean up any existing records
    sessions = db.query(models.ConversationSession).filter(models.ConversationSession.shop_id == shop_id).all()
    session_ids = [s.id for s in sessions]
    if session_ids:
        db.query(models.ConversationMessage).filter(models.ConversationMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(models.ConversationSession).filter(models.ConversationSession.shop_id == shop_id).delete()
    db.query(models.AIConversationSession).filter(models.AIConversationSession.shop_id == shop_id).delete()
    db.execute(text(f"DELETE FROM pending_sse_events WHERE shop_id = '{shop_id}'"))
    db.commit()
    
    # 2. Start a fresh conversation and inquiry
    # Message "hi" triggers menu or onboarding
    def get_text(r):
        if isinstance(r, dict):
            return r.get("body", "")
        return str(r)
        
    reply1 = GuidedConversationEngine.process_message(db, shop_id, phone, "hi")
    print(f"[TEST DEBUG] reply1: {reply1}")
    
    # Complete onboarding if it asks for name/phone
    r1_text = get_text(reply1).lower()
    if "what's your name" in r1_text or "your name" in r1_text:
        reply_name = GuidedConversationEngine.process_message(db, shop_id, phone, "John Doe")
        print(f"[TEST DEBUG] reply_name: {reply_name}")
        reply_phone = GuidedConversationEngine.process_message(db, shop_id, phone, "9999999999")
        print(f"[TEST DEBUG] reply_phone: {reply_phone}")
        # Now send "hi" again to get main menu
        reply1 = GuidedConversationEngine.process_message(db, shop_id, phone, "hi")
        print(f"[TEST DEBUG] reply1 after onboarding: {reply1}")

    # User clicks Inquiry button
    reply2 = GuidedConversationEngine.process_message(db, shop_id, phone, "btn_inquiry")
    print(f"[TEST DEBUG] reply2: {reply2}")
    assert "inquiry" in get_text(reply2).lower() or "type" in get_text(reply2).lower()
    
    # User sends inquiry message
    reply3 = GuidedConversationEngine.process_message(db, shop_id, phone, "Do you have wholesale prices?")
    print(f"[TEST DEBUG] reply3: {reply3}")
    r3_text = get_text(reply3).lower()
    assert "name" in r3_text or "sent!" in r3_text or "details" in r3_text or "please" in r3_text
    
    # Complete onboarding if it collects name
    ai_sess = db.query(models.AIConversationSession).filter(
        models.AIConversationSession.shop_id == shop_id,
        models.AIConversationSession.customer_phone == phone
    ).first()
    
    if ai_sess.collected_fields.get("guided_state") == "inquiry_collect_name":
        reply_name = GuidedConversationEngine.process_message(db, shop_id, phone, "John Doe")
        print(f"[TEST DEBUG] reply_name: {reply_name}")
        
    # Re-fetch state
    db.refresh(ai_sess)
    if ai_sess.collected_fields.get("guided_state") == "inquiry_collect_phone":
        reply_phone = GuidedConversationEngine.process_message(db, shop_id, phone, "9999999999")
        print(f"[TEST DEBUG] reply_phone: {reply_phone}")
        
    # Verify ConversationSession has been created
    inq = db.query(models.ConversationSession).filter(
        models.ConversationSession.shop_id == shop_id,
        models.ConversationSession.customer_phone == phone
    ).first()
    
    assert inq is not None
    assert inq.inquiry_number is not None
    assert inq.inquiry_status == "ACTIVE" or inq.status in ["NEW", "ONGOING"]
    
    inq_num = inq.inquiry_number
    
    # 3. Test PAUSE Command
    reply_pause = GuidedConversationEngine.process_message(db, shop_id, phone, f"Pause {inq_num}")
    db.refresh(inq)
    assert inq.inquiry_status == "PAUSED"
    assert inq.paused_at is not None
    assert "paused successfully" in reply_pause
    
    # Verify that since inquiry is paused, sending a message does NOT route to owner
    # But instead triggers the AI main menu or ordering flow!
    reply_multitask = GuidedConversationEngine.process_message(db, shop_id, phone, "order")
    print(f"[TEST DEBUG] reply_multitask: {reply_multitask}")
    reply_multitask_text = get_text(reply_multitask).lower()
    assert any(w in reply_multitask_text for w in ["order", "menu", "choose", "welcome", "select", "category"])
    
    # 4. Test RESUME Command
    reply_resume = GuidedConversationEngine.process_message(db, shop_id, phone, f"Resume {inq_num}")
    db.refresh(inq)
    assert inq.inquiry_status == "ACTIVE"
    assert inq.resumed_at is not None
    assert "resumed" in reply_resume
    
    # 5. Test STATUS Command
    reply_status = GuidedConversationEngine.process_message(db, shop_id, phone, f"Status {inq_num}")
    assert "Status:" in reply_status
    
    # 6. Test CANCEL Command
    reply_cancel = GuidedConversationEngine.process_message(db, shop_id, phone, f"Cancel {inq_num}")
    db.refresh(inq)
    assert inq.inquiry_status == "CANCELLED"
    assert inq.cancelled_at is not None
    assert "cancelled" in reply_cancel
    
    # 7. Test COMPLETE Command
    # Let's set it active first
    inq.inquiry_status = "ACTIVE"
    db.commit()
    reply_complete = GuidedConversationEngine.process_message(db, shop_id, phone, f"Complete {inq_num}")
    db.refresh(inq)
    assert inq.inquiry_status == "RESOLVED"
    assert inq.completed_at is not None
    assert "completed" in reply_complete
    
    # Clean up
    sessions = db.query(models.ConversationSession).filter(models.ConversationSession.shop_id == shop_id).all()
    session_ids = [s.id for s in sessions]
    if session_ids:
        db.query(models.ConversationMessage).filter(models.ConversationMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(models.ConversationSession).filter(models.ConversationSession.shop_id == shop_id).delete()
    db.query(models.AIConversationSession).filter(models.AIConversationSession.shop_id == shop_id).delete()
    db.execute(text(f"DELETE FROM pending_sse_events WHERE shop_id = '{shop_id}'"))
    db.query(models.ConversationCategory).filter(models.ConversationCategory.shop_id == shop_id).delete()
    db.query(models.Shop).filter(models.Shop.id == shop_id).delete()
    db.commit()
    db.close()
    print("\n=== LIFECYCLE TEST PASSED SUCCESFULLY ===")

if __name__ == "__main__":
    test_non_blocking_lifecycle()
