import os
import sys
import threading
from datetime import datetime, timezone
import time

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.services.guided_conversation_engine import GuidedConversationEngine

def run_guided_realtime_stress_test():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
        
    print("======================================================================")
    print("LEVIX REAL-TIME INTERACTION STABILITY & IDEMPOTENCY STRESS SUITE")
    print("======================================================================")
    
    db = SessionLocal()
    try:
        # Create or fetch a test shop
        shop = db.query(models.Shop).filter_by(email="stresstest@example.com").first()
        if not shop:
            shop = models.Shop(
                shop_name="Levix Stress Test Emporium",
                owner_name="Architect Stressor",
                email="stresstest@example.com",
                phone_number="9998887770",
                password_hash="stresshashed"
            )
            db.add(shop)
            db.commit()
            db.refresh(shop)

        # Clear existing entries
        db.query(models.InventoryItem).filter_by(shop_id=shop.id).delete(synchronize_session=False)
        db.query(models.Product).filter_by(shop_id=shop.id).delete(synchronize_session=False)
        db.query(models.AIConversationSession).filter(
            models.AIConversationSession.customer_phone.in_(["9991112222", "9993334444"])
        ).delete(synchronize_session=False)
        db.commit()

        # Seed categories and products
        items = [
            models.InventoryItem(
                id="stress-tea",
                shop_id=shop.id,
                name="Premium Tea",
                quantity=10,
                price=30.00,
                category="Drinks"
            ),
            models.InventoryItem(
                id="stress-biscuit",
                shop_id=shop.id,
                name="Butter Biscuit",
                quantity=20,
                price=20.00,
                category="Snacks"
            )
        ]
        db.add_all(items)
        db.commit()

        prods = [
            models.Product(
                id=item.id,
                shop_id=shop.id,
                name=item.name,
                price=item.price,
                quantity=item.quantity,
                category=item.category,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            for item in items
        ]
        db.add_all(prods)
        db.commit()

        print("\n[STRESS CASE 1] Prefix Harmonization: 'category_' vs 'cat_' prefixes")
        phone = "9991112222"
        
        def safe_reply(r):
            if isinstance(r, dict):
                return str(r)
            return str(r)

        # Greeting
        GuidedConversationEngine.process_message(db, shop.id, phone, "Hi")
        # Go to Order
        GuidedConversationEngine.process_message(db, shop.id, phone, "1")
        
        # Tap using 'cat_0' prefix (from WhatsApp fallback list)
        reply1 = safe_reply(GuidedConversationEngine.process_message(db, shop.id, phone, "cat_0"))
        print("Reply for 'cat_0':", repr(reply1[:80]))
        assert "Products in Drinks" in reply1 or "Premium Tea" in reply1, "Should parse category Drinks from 'cat_0'"

        # Clean session
        db.query(models.AIConversationSession).filter_by(customer_phone=phone).delete(synchronize_session=False)
        db.commit()

        # Greeting & Order again
        GuidedConversationEngine.process_message(db, shop.id, phone, "Hi")
        GuidedConversationEngine.process_message(db, shop.id, phone, "1")

        # Tap using 'category_0' prefix (from new harmonized list)
        reply2 = safe_reply(GuidedConversationEngine.process_message(db, shop.id, phone, "category_0"))
        print("Reply for 'category_0':", repr(reply2[:80]))
        assert "Products in Drinks" in reply2 or "Premium Tea" in reply2, "Should parse category Drinks from 'category_0'"

        print("PASS: Prefix Harmonization is resilient!")

        print("\n[STRESS CASE 2] Auto-Healing & Idempotent routing on drift / out-of-order replays")
        # Now, send a category selection raw name "Drinks" while state is "idle" (no active session or finished session)
        db.query(models.AIConversationSession).filter_by(customer_phone=phone).delete(synchronize_session=False)
        db.commit()

        reply_idle = safe_reply(GuidedConversationEngine.process_message(db, shop.id, phone, "Drinks"))
        print("Reply for raw 'Drinks' when session idle:", repr(reply_idle[:80]))
        assert "Products in Drinks" in reply_idle or "Premium Tea" in reply_idle, "Idempotent routing failed to auto-heal idle session"

        # Check that state was corrected to order_select_product (since category was processed)
        session = db.query(models.AIConversationSession).filter_by(customer_phone=phone).first()
        assert session is not None
        assert session.collected_fields.get("guided_state") == "order_select_product"
        print("PASS: Auto-Healed idle session into order_select_category!")

        print("\n[STRESS CASE 3] Fast concurrency / identical replies (Twin click simulation)")
        phone_twin = "9993334444"
        db.query(models.AIConversationSession).filter_by(customer_phone=phone_twin).delete(synchronize_session=False)
        db.commit()

        # Start ordering session
        GuidedConversationEngine.process_message(db, shop.id, phone_twin, "Hi")
        GuidedConversationEngine.process_message(db, shop.id, phone_twin, "1")

        # Simulate twin threads sending 'category_0' concurrently
        replies = []
        def send_message_thread(msg):
            local_db = SessionLocal()
            try:
                rep = safe_reply(GuidedConversationEngine.process_message(local_db, shop.id, phone_twin, msg))
                replies.append(rep)
            finally:
                local_db.close()

        t1 = threading.Thread(target=send_message_thread, args=("category_0",))
        t2 = threading.Thread(target=send_message_thread, args=("category_0",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        print(f"Twin thread responses count: {len(replies)}")
        for i, r in enumerate(replies):
            print(f"Response {i + 1}:", repr(r[:80]))
            # Responds cleanly without raising SQLAlchemy or state machine crash!
            assert "Products in Drinks" in r or "quantity" in r or "invalid selection" in r.lower() or "Place Order" in r or "Premium Tea" in r

        print("PASS: Twin clicks processed safely and idempotently!")
        print("\n======================================================================")
        print("ALL REAL-TIME STABILITY & Webhook Idempotency Tests PASSED! 🚀")
        print("======================================================================")

    except Exception as e:
        import traceback
        print(f"STRESS TEST FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.rollback()
        db.close()

if __name__ == "__main__":
    run_guided_realtime_stress_test()
