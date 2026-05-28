import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from app.database import SessionLocal
from app.models import Shop, ConversationSession, ConversationMessage
from app.services.guided_conversation_engine import GuidedConversationEngine

def test_conversation_pipeline():
    print("\n=== LEVIX CONVERSATION PIPELINE TEST ===\n")
    db = SessionLocal()
    
    # Setup shops
    shop_id = "conv_test_shop"
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        shop = Shop(id=shop_id, owner_name="Conv Test Shop")
        db.add(shop); db.commit()

    phone = f"91987{str(int(time.time()))[-6:]}"
    print(f"[TEST] Using phone: {phone}")

    # --- Scenario 1: Inquiry creates a ConversationSession ---
    print("\n[S1] Inquiry creates ConversationSession")
    GuidedConversationEngine.process_message(db, shop.id, phone, "hi")
    GuidedConversationEngine.process_message(db, shop.id, phone, "btn_inquiry")
    GuidedConversationEngine.process_message(db, shop.id, phone, "Do you have bulk orders for rice?")
    GuidedConversationEngine.process_message(db, shop.id, phone, "Ravi Kumar")

    session = db.query(ConversationSession).filter(
        ConversationSession.shop_id == shop.id,
        ConversationSession.customer_phone == phone,
        ConversationSession.status == "NEW"
    ).first()

    if session and session.customer_name == "Ravi Kumar":
        print("PASS S1: ConversationSession created with correct customer name.")
    else:
        print(f"FAIL S1: Session not found or wrong name. Got: {session}")
        db.close(); return

    # Check initial message was stored
    msgs = db.query(ConversationMessage).filter(ConversationMessage.session_id == session.id).all()
    if msgs and any("rice" in m.message.lower() for m in msgs):
        print("PASS S1b: Initial inquiry message stored in ConversationMessage.")
    else:
        print(f"FAIL S1b: Initial message missing. Messages: {[m.message for m in msgs]}")

    # --- Scenario 2: Follow-up message auto-appended to existing session ---
    print("\n[S2] Follow-up message appended to ACTIVE session")
    GuidedConversationEngine.process_message(db, shop.id, phone, "I need 50 bags minimum.")
    GuidedConversationEngine.process_message(db, shop.id, phone, "Can you deliver by Friday?")

    db.refresh(session)
    msgs_after = db.query(ConversationMessage).filter(ConversationMessage.session_id == session.id).all()
    follow_ups = [m for m in msgs_after if "50 bags" in m.message or "Friday" in m.message]
    if len(follow_ups) == 2:
        print("PASS S2: Both follow-up messages appended to same session.")
    else:
        print(f"FAIL S2: Expected 2 follow-ups, found {len(follow_ups)}")

    # --- Scenario 3: Rapid duplicate webhook - no duplicate sessions ---
    print("\n[S3] Rapid duplicate webhook - no duplicate sessions")
    GuidedConversationEngine.process_message(db, shop.id, phone, "hi")
    GuidedConversationEngine.process_message(db, shop.id, phone, "btn_inquiry")
    GuidedConversationEngine.process_message(db, shop.id, phone, "Same question again")
    GuidedConversationEngine.process_message(db, shop.id, phone, "Ravi Kumar")

    session_count = db.query(ConversationSession).filter(
        ConversationSession.shop_id == shop.id,
        ConversationSession.customer_phone == phone
    ).count()
    if session_count == 1:
        print("PASS S3: Only one ACTIVE session for this phone. Duplicate blocked.")
    else:
        print(f"FAIL S3: Expected 1 session, found {session_count}")

    # --- Scenario 4: Multi-shop isolation ---
    print("\n[S4] Multi-shop isolation")
    shop2_id = "conv_test_shop_2"
    shop2 = db.query(Shop).filter(Shop.id == shop2_id).first()
    if not shop2:
        shop2 = Shop(id=shop2_id, owner_name="Conv Test Shop 2")
        db.add(shop2); db.commit()

    phone2 = phone + "2"
    GuidedConversationEngine.process_message(db, shop2.id, phone2, "hi")
    GuidedConversationEngine.process_message(db, shop2.id, phone2, "btn_inquiry")
    GuidedConversationEngine.process_message(db, shop2.id, phone2, "Sugar availability?")
    GuidedConversationEngine.process_message(db, shop2.id, phone2, "Meera")

    s1_count = db.query(ConversationSession).filter(ConversationSession.shop_id == shop.id, ConversationSession.customer_phone == phone).count()
    s2_count = db.query(ConversationSession).filter(ConversationSession.shop_id == shop2.id, ConversationSession.customer_phone == phone2).count()
    if s1_count >= 1 and s2_count == 1:
        print("PASS S4: Sessions isolated per shop correctly.")
    else:
        print(f"FAIL S4: shop1 sessions={s1_count}, shop2 sessions={s2_count}")

    # --- Scenario 5: Complete conversation, new inquiry creates new session ---
    print("\n[S5] Complete session, new inquiry creates new session")
    session.status = "COMPLETED"
    db.commit()

    phone3 = phone + "3"
    GuidedConversationEngine.process_message(db, shop.id, phone3, "hi")
    GuidedConversationEngine.process_message(db, shop.id, phone3, "btn_inquiry")
    GuidedConversationEngine.process_message(db, shop.id, phone3, "New inquiry after completion")
    GuidedConversationEngine.process_message(db, shop.id, phone3, "New Customer")

    new_session = db.query(ConversationSession).filter(
        ConversationSession.shop_id == shop.id,
        ConversationSession.customer_phone == phone3,
        ConversationSession.status == "NEW"
    ).first()
    if new_session:
        print("PASS S5: New ACTIVE session created after completion.")
    else:
        print("FAIL S5: No new session found.")

    # --- CLEANUP ---
    print("\n[CLEANUP] Removing test data...")
    from sqlalchemy import text
    with db.bind.connect() as conn:
        shop_ids_sql = "('conv_test_shop', 'conv_test_shop_2')"
        cleanup_tables = [
            "conversation_messages WHERE session_id IN (SELECT id FROM conversation_sessions WHERE shop_id IN " + shop_ids_sql + ")",
            f"conversation_sessions WHERE shop_id IN {shop_ids_sql}",
            f"customer_sessions WHERE shop_id IN {shop_ids_sql}",
            f"ai_conversation_sessions WHERE shop_id IN {shop_ids_sql}",
            f"pending_sse_events WHERE shop_id IN {shop_ids_sql}",
            f"pending_requests WHERE shop_id IN {shop_ids_sql}",
            f"customer_profiles WHERE shop_id IN {shop_ids_sql}",
        ]
        for clause in cleanup_tables:
            try:
                conn.execute(text(f"DELETE FROM {clause}"))
            except Exception:
                conn.rollback()
        try:
            conn.execute(text(f"DELETE FROM shops WHERE id IN {shop_ids_sql}"))
        except Exception as e:
            print(f"[CLEANUP WARNING] {e}")
        conn.commit()
    db.close()
    print("\n=== ALL CONVERSATION TESTS DONE ===\n")

if __name__ == "__main__":
    test_conversation_pipeline()
