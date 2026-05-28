import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.services.guided_conversation_engine import GuidedConversationEngine

def test_session_lifecycle():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
        
    db = SessionLocal()
    try:
        # 1. Create or fetch a test shop
        shop = db.query(models.Shop).filter_by(email="lifecyctest@example.com").first()
        if not shop:
            shop = models.Shop(
                shop_name="Levix Lifecycle Shop",
                owner_name="Jack Rajesh",
                email="lifecyctest@example.com",
                phone_number="9876543000",
                password_hash="hashedpassword"
            )
            db.add(shop)
            db.commit()
            db.refresh(shop)

        # Cleanup existing test sessions
        db.query(models.AIConversationSession).filter(
            models.AIConversationSession.customer_phone.in_(["9555111222", "9555222333", "9555333444", "9555444555"])
        ).delete(synchronize_session=False)
        db.commit()

        print("\n============================================================")
        print("STARTING LEVIX CONVERSATIONAL STATE RESTORATION TESTS")
        print("============================================================\n")

        # ------------------------------------------------------------
        # TEST CASE 1: Fresh Greeting Override Stale Booking State (Rule 1 & Rule 5)
        # ------------------------------------------------------------
        print("--- TEST CASE 1: Fresh Greeting Resets Awaiting Booking Lookup ---")
        phone_1 = "9555111222"
        
        # Create a stale awaiting booking lookup session in database
        sess_1 = models.AIConversationSession(
            shop_id=shop.id,
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            customer_phone=phone_1,
            conversation_history=[],
            collected_fields={"guided_state": "awaiting_booking_lookup", "session_data": {}},
            category="awaiting_booking_lookup",
            turn_count=1,
            is_active=True,
            source="whatsapp",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(sess_1)
        db.commit()
        
        # Send fresh greeting ("Hi")
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_1, "Hi")
        print(f"User: 'Hi' (while in awaiting_booking_lookup)\nReply:\n{reply}\n")
        
        # Verify that it reset to main menu and did NOT return "Invalid Booking ID"
        assert "Welcome to *Levix Lifecycle Shop*" in str(reply)
        assert "btn_order" in str(reply)
        
        # Verify state in DB is now awaiting_main_menu
        db.refresh(sess_1)
        assert sess_1.category == "awaiting_main_menu"
        print("✅ PASS: Fresh Greeting Override")

        # ------------------------------------------------------------
        # TEST CASE 2: Dynamic Inactivity Timeout (Rule 2)
        # ------------------------------------------------------------
        print("\n--- TEST CASE 2: Dynamic Stale Session Timeout (Booking 5 mins) ---")
        phone_2 = "9555222333"
        
        # Create a session updated 6 minutes ago (exceeding the 5 min limit)
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=6)
        sess_2 = models.AIConversationSession(
            shop_id=shop.id,
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            customer_phone=phone_2,
            conversation_history=[],
            collected_fields={"guided_state": "awaiting_booking_lookup", "session_data": {}},
            category="awaiting_booking_lookup",
            turn_count=1,
            is_active=True,
            source="whatsapp",
            created_at=stale_time,
            updated_at=stale_time
        )
        db.add(sess_2)
        db.commit()
        
        # Send a non-greeting message (e.g. "LEV-1234")
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "LEV-1234")
        print(f"User: 'LEV-1234' (on 6-minute expired track session)\nReply:\n{reply}\n")
        
        # Verify that it triggered timeout expiration
        assert "timed out" in str(reply).lower() or "welcome" in str(reply).lower()
        
        # Verify DB session category was reset to idle or menu
        db.refresh(sess_2)
        assert sess_2.category in ("idle", "awaiting_main_menu")
        print("✅ PASS: Dynamic Inactivity Timeout")

        # ------------------------------------------------------------
        # TEST CASE 3: Session Corruption Safety Recovery (Rule 3)
        # ------------------------------------------------------------
        print("\n--- TEST CASE 3: Recovery from Corrupted Session State ---")
        phone_3 = "9555333444"
        
        # Create a corrupted session state (missing selected_product in select_quantity state)
        sess_3 = models.AIConversationSession(
            shop_id=shop.id,
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            customer_phone=phone_3,
            conversation_history=[],
            collected_fields={"guided_state": "order_select_quantity", "session_data": {}}, # Missing selected_product!
            category="order_select_quantity",
            turn_count=1,
            is_active=True,
            source="whatsapp",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(sess_3)
        db.commit()
        
        # Send a message
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_3, "qty_2")
        print(f"User: 'qty_2' (on corrupted select_quantity state)\nReply:\n{reply}\n")
        
        # Verify that it safely recovered and reset instead of throwing Internal Error
        assert "Welcome to *Levix Lifecycle Shop*" in str(reply)
        
        # Verify DB session was corrected
        db.refresh(sess_3)
        assert sess_3.category == "awaiting_main_menu"
        print("✅ PASS: Safety Recovery from Corruption")

        # ------------------------------------------------------------
        # TEST CASE 4: Single Active Flow Deactivation (Rule 4)
        # ------------------------------------------------------------
        print("\n--- TEST CASE 4: Single Active Flow Ownership Enforcement ---")
        phone_4 = "9555444555"
        
        # Create two active sessions for the same customer
        sess_4a = models.AIConversationSession(
            shop_id=shop.id,
            session_id="sess_first_active",
            customer_phone=phone_4,
            conversation_history=[],
            collected_fields={"guided_state": "order_select_category", "session_data": {}},
            category="order_select_category",
            turn_count=1,
            is_active=True,
            source="whatsapp",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        sess_4b = models.AIConversationSession(
            shop_id=shop.id,
            session_id="sess_second_active",
            customer_phone=phone_4,
            conversation_history=[],
            collected_fields={"guided_state": "order_select_product", "session_data": {}},
            category="order_select_product",
            turn_count=1,
            is_active=True,
            source="whatsapp",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add_all([sess_4a, sess_4b])
        db.commit()
        
        # Send a message
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_4, "Hello")
        
        # Verify that only the newest one is active and the older one is deactivated
        db.refresh(sess_4a)
        db.refresh(sess_4b)
        
        assert sess_4a.is_active == False
        assert sess_4b.is_active == True
        print(f"Old Session (sess_first_active) active status: {sess_4a.is_active}")
        print(f"New Session (sess_second_active) active status: {sess_4b.is_active}")
        print("✅ PASS: Single Active Session Ownership")

        print("\n============================================================")
        print("ALL LEVIX STATE RESTORATION TESTS PASSED SUCCESSFULLY! 🚀")
        print("============================================================\n")

    except Exception as e:
        import traceback
        print(f"TEST LIFECYCLE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.rollback()
        db.close()

if __name__ == "__main__":
    test_session_lifecycle()
