import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.services.guided_conversation_engine import GuidedConversationEngine

def test_guided_flows():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass # Python versions or environments without reconfigure
    
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS category VARCHAR(255);"))
        db.commit()
    except Exception as dberr:
        print(f"Migration warning: {dberr}")
        db.rollback()
    try:
        # 1. Create or fetch a test shop
        shop = db.query(models.Shop).filter_by(email="guidedtest@example.com").first()
        if not shop:
            shop = models.Shop(
                shop_name="Levix Premium Retail",
                owner_name="Jack Rajesh",
                email="guidedtest@example.com",
                phone_number="9876543210",
                password_hash="hashedpassword"
            )
            db.add(shop)
            db.commit()
            db.refresh(shop)

        # 2. Add some test inventory items and matching products
        # Delete in correct order to avoid FK violations
        order_ids = [o.id for o in db.query(models.Order).filter_by(shop_id=shop.id).all()]
        if order_ids:
            db.query(models.OrderItem).filter(models.OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
            db.query(models.Order).filter_by(shop_id=shop.id).delete(synchronize_session=False)
            
        db.query(models.InventoryItem).filter_by(shop_id=shop.id).delete(synchronize_session=False)
        db.query(models.Product).filter_by(shop_id=shop.id).delete(synchronize_session=False)
        
        db.query(models.AIConversationSession).filter(
            models.AIConversationSession.customer_phone.in_(["9000111222", "9000333444"])
        ).delete(synchronize_session=False)
        
        db.query(models.PendingRequest).filter(
            models.PendingRequest.customer_phone.in_(["9000111222", "9000333444"])
        ).delete(synchronize_session=False)

        # Clean up ConversationSession and ConversationMessage for test phone numbers
        db.query(models.ConversationMessage).filter(
            models.ConversationMessage.session_id.in_(
                db.query(models.ConversationSession.id).filter(
                    models.ConversationSession.customer_phone.in_(["9000111222", "9000333444"])
                )
            )
        ).delete(synchronize_session=False)
        db.query(models.ConversationSession).filter(
            models.ConversationSession.customer_phone.in_(["9000111222", "9000333444"])
        ).delete(synchronize_session=False)
        
        db.commit()

        items = [
            models.InventoryItem(
                id="tea-prod-123",
                shop_id=shop.id,
                name="Premium Tea",
                quantity=10,
                price=30.00,
                category="Drinks"
            ),
            models.InventoryItem(
                id="coke-prod-456",
                shop_id=shop.id,
                name="Coca Cola 250ml",
                quantity=3, # Low stock! Should show "Only few left"
                price=40.00,
                category="Drinks"
            ),
            models.InventoryItem(
                id="biscuit-prod-789",
                shop_id=shop.id,
                name="Butter Biscuit",
                quantity=20,
                price=20.00,
                category="Snacks"
            )
        ]
        db.add_all(items)
        db.commit()

        # Seed matching product rows to satisfy order_items -> products FK constraint
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

        print("--- TEST CASE 1: Greeting & Main Menu Menu ---")
        phone_1 = "9000111222"
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_1, "Hi there")
        print(f"User: 'Hi there'\nReply:\n{reply}\n")
        assert "Levix Premium Retail" in str(reply)
        assert "btn_order" in str(reply)
        assert "btn_inquiry" in str(reply)
        print("PASS: Greeting & Main Menu")

        print("\n--- TEST CASE 2: Inquiry Flow ---")
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_1, "btn_inquiry")
        print(f"User: 'btn_inquiry'\nReply:\n{reply}\n")
        assert "Inquiry Section" in str(reply)
        assert "Please type your inquiry" in str(reply)

        reply = GuidedConversationEngine.process_message(db, shop.id, phone_1, "Do you deliver to T. Nagar?")
        print(f"User: 'Do you deliver to T. Nagar?'\nReply:\n{reply}\n")
        assert "Please enter your name" in str(reply)

        reply = GuidedConversationEngine.process_message(db, shop.id, phone_1, "Rajesh Kumar")
        print(f"User: 'Rajesh Kumar'\nReply:\n{reply}\n")
        assert "inquiry has been received" in str(reply)

        # Check DB
        inq = db.query(models.ConversationSession).filter_by(customer_phone=phone_1).first()
        assert inq is not None
        assert inq.customer_name == "Rajesh Kumar"
        msg = db.query(models.ConversationMessage).filter_by(session_id=inq.id).first()
        assert msg is not None
        assert msg.message == "Do you deliver to T. Nagar?"
        print("PASS: Inquiry flow saved successfully!")

        print("\n--- TEST CASE 3: Full Order Flow ---")
        phone_2 = "9000333444"
        # Greeting
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "Hello")
        # Select Order
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "btn_order")
        print(f"User: 'btn_order'\nReply:\n{reply}\n")
        assert "Select Category" in str(reply)
        assert "Drinks" in str(reply)
        assert "Snacks" in str(reply)

        # Select Drinks category (id: category_0)
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "category_0")
        print(f"User: 'category_0' (Drinks)\nReply:\n{reply}\n")
        assert "Products in Drinks" in str(reply)
        assert "Premium Tea" in str(reply)
        assert "Coca Cola 250ml" in str(reply)

        # Select Coca Cola (id: product_coke-prod-456)
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "product_coke-prod-456")
        print(f"User: 'product_coke-prod-456' (Coca Cola)\nReply:\n{reply}\n")
        assert "Coca Cola 250ml" in str(reply)
        assert "quantity" in str(reply)

        # Enter quantity button option: qty_2
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "qty_2")
        print(f"User: 'qty_2' (Qty)\nReply:\n{reply}\n")
        assert "Your Cart" in str(reply)
        assert "2x Coca Cola 250ml" in str(reply)
        assert "Subtotal: *₹80*" in str(reply)
        assert "btn_checkout" in str(reply)

        # Select Confirm Order (Checkout): btn_checkout
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "btn_checkout")
        print(f"User: 'btn_checkout' (Checkout)\nReply:\n{reply}\n")
        assert "Choose Delivery Method" in str(reply)
        assert "btn_pickup" in str(reply)
        assert "btn_delivery" in str(reply)

        # Select Pickup: btn_pickup
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "btn_pickup")
        print(f"User: 'btn_pickup' (Pickup)\nReply:\n{reply}\n")
        assert "Please enter your name" in str(reply)

        # Enter name
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "Kumar")
        print(f"User: 'Kumar'\nReply:\n{reply}\n")
        assert "FINAL ORDER REVIEW" in str(reply)
        assert "Kumar" in str(reply)
        assert "Pickup" in str(reply)
        assert "80" in str(reply)

        # Confirm order: btn_confirm_order
        reply = GuidedConversationEngine.process_message(db, shop.id, phone_2, "btn_confirm_order")
        print(f"User: 'btn_confirm_order' (Confirm)\nReply:\n{reply}\n")
        assert reply == "" # Sent asynchronously

        # Check DB Order
        ord_db = db.query(models.Order).filter_by(phone=phone_2).first()
        assert ord_db is not None
        assert ord_db.customer_name == "Kumar"
        assert ord_db.total_amount == 80.00
        assert ord_db.delivery_type == "PICKUP"
        
        print("PASS: Full Order Flow completed and stored in database!")
        print("\nALL GUIDED FLOW TESTS PASSED SUCCESSFULLY! 🎉")

    except Exception as e:
        import traceback
        print(f"TEST FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.rollback()
        db.close()

def test_webhook_guard():
    from app.core.webhook_guard import WebhookGuard
    print("\n--- TEST CASE: Webhook Guard Deduplication ---")
    msg_id = "test_msg_123"
    
    # First time should not be duplicate
    is_dup1 = WebhookGuard.is_duplicate(msg_id)
    print(f"First call for {msg_id}: is_duplicate={is_dup1}")
    assert is_dup1 == False
    
    # Second time should be duplicate
    is_dup2 = WebhookGuard.is_duplicate(msg_id)
    print(f"Second call for {msg_id}: is_duplicate={is_dup2}")
    assert is_dup2 == True
    
    print("PASS: Webhook Guard deduplicated successfully!")

if __name__ == "__main__":
    test_guided_flows()
    test_webhook_guard()
