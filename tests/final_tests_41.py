import os
import sys
import re
import traceback
import io

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal, Base, engine
from app.models import Shop, CustomerProfile, Order, PendingInquiry, InventoryItem, InventoryAlias, AIConversationSession
from app.services.router_engine import RouterEngine
from app.services.memory_engine import MemoryEngine

Base.metadata.create_all(bind=engine)

db = SessionLocal()

def reset_db():
    test_shop = db.query(Shop).filter_by(shop_name="Levix Test Shop").first()
    if test_shop:
        db.delete(test_shop)
        db.commit()

import time
def create_shop():
    uid = str(int(time.time()))
    shop = Shop(shop_name=f"Levix Test Shop {uid}", owner_name="Owner", email=f"test{uid}@test.com", password_hash="123", phone_number=uid[-10:], shop_category="Food & Restaurant")
    db.add(shop)
    db.commit()
    db.refresh(shop)
    
    # Add inventory
    items = [
        InventoryItem(shop_id=shop.id, name="Coco Cola", aliases=[InventoryAlias(alias="coke"), InventoryAlias(alias="soda")], price=20, quantity=100, status="in_stock", product_details="Refreshing cold drink. Size: 500ml"),
        InventoryItem(shop_id=shop.id, name="Mushroom Biryani", aliases=[InventoryAlias(alias="mushrom briyani")], price=120, quantity=50, status="in_stock", product_details="Spicy biryani with fresh mushrooms"),
        InventoryItem(shop_id=shop.id, name="Chicken Fried Rice", aliases=[InventoryAlias(alias="chicken rice")], price=150, quantity=50, status="in_stock", product_details="Chinese style chicken fried rice"),
        InventoryItem(shop_id=shop.id, name="Chicken Biryani", price=180, quantity=50, status="in_stock", product_details="Dum biryani"),
        InventoryItem(shop_id=shop.id, name="Mutton Biryani", price=250, quantity=50, status="in_stock", product_details="Rich mutton biryani"),
        InventoryItem(shop_id=shop.id, name="Ice Cream", price=60, quantity=50, status="in_stock", product_details="Vanilla flavor. Great dessert."),
        InventoryItem(shop_id=shop.id, name="Rose Milk", price=40, quantity=50, status="in_stock")
    ]
    db.add_all(items)
    db.commit()
    return shop.id

def test_step(description, result_bool, expected="", actual=""):
    status = "PASS" if result_bool else "FAIL"
    print(f"{status} | {description}")
    if not result_bool:
        print(f"   Expected: {expected}")
        print(f"   Actual:   {actual}")
    return result_bool

class SimBot:
    def __init__(self, phone, shop_id):
        self.phone = phone
        self.shop_id = shop_id
        
    def send(self, msg):
        return RouterEngine.process_message(db, self.shop_id, self.phone, msg)

print("\n--- RUNNING TESTS ---")
try:
    reset_db()
    
    # Also clean up any lingering profiles/sessions for test phones
    test_phones = ["919999999999", "918888888888"]
    db.query(CustomerProfile).filter(CustomerProfile.customer_phone.in_(test_phones)).delete(synchronize_session=False)
    db.query(AIConversationSession).filter(AIConversationSession.customer_phone.in_(test_phones)).delete(synchronize_session=False)
    db.commit()

    shop_id = create_shop()
    
    bot = SimBot("9000000001", shop_id)
    
    # TEST 1: ONBOARDING
    print("\nVERIFICATION TEST 1 — ONBOARDING")
    r1 = bot.send("hi")
    s1 = test_step("Step 1: Fresh session, asks for name", "welcome" in r1.lower() and "name" in r1.lower(), "welcome + ask name", r1)
    
    r2 = bot.send("hi")
    s2 = test_step("Step 2: Reject greeting as name", "name" in r2.lower(), "ask name", r2)
    
    r3 = bot.send("VIP")
    s3 = test_step("Step 3: Reject placeholder", "name" in r3.lower() and "welcome" not in r3.lower(), "ask name", r3)
    
    r4 = bot.send("Rajesh")
    s4 = test_step("Step 4: Stores Rajesh, asks for phone", "phone number" in r4.lower() or "10 digits" in r4.lower(), "ask phone", r4)
    
    r5 = bot.send("63698")
    s5 = test_step("Step 5: Reject 5 digit phone", "10-digit" in r5.lower() or "doesn't look right" in r5.lower(), "ask phone again", r5)
    
    r6 = bot.send("6369812535")
    prof = db.query(CustomerProfile).filter_by(customer_phone="9000000001").first()
    s6 = test_step("Step 6: Phone accepted, profile saved", ("what would you like" in r6.lower() or "what can i get you" in r6.lower() or "here's what we have" in r6.lower()) and prof and prof.customer_name == "Rajesh", "success message", r6)
    
    # Returning customer
    bot_ret = SimBot("918888888888", shop_id)
    prof_ret = CustomerProfile(shop_id=shop_id, customer_phone="918888888888", customer_name="Arjun")
    db.add(prof_ret)
    db.commit()
    r7 = bot_ret.send("hi")
    # FAIL 1.7: Ensure name is matched
    s7 = test_step("Step 7: Returning customer skips onboarding", "welcome back" in r7.lower() and "arjun" in r7.lower(), "welcome back arjun", r7)

    # TEST 2: "NO" HANDLING
    print("\nVERIFICATION TEST 2 — \"NO\" HANDLING")
    bot.send("add 1 coke")
    r2_1 = bot.send("no")
    s2_1 = test_step("Step 1: 'no' keeps cart unchanged", "let me know" in r2_1.lower() or "sure" in r2_1.lower() or "unclear" in r2_1.lower() or "what else" in r2_1.lower(), "No problem!", r2_1)
    
    # Simulate upsell offer
    # ... Wait, I'll need to force state.
    session = db.query(AIConversationSession).filter_by(customer_phone=bot.phone).first()
    fields = session.collected_fields or {}
    fields["pending_action_type"] = "upsell"
    session.collected_fields = fields
    session.category = "awaiting_yes_no"
    db.commit()
    r2_2 = bot.send("no")
    s2_2 = test_step("Step 2: Reject upsell", "cart" in r2_2.lower() or "total" in r2_2.lower() or "what else" in r2_2.lower(), "cart summary", r2_2)

    r2_3 = bot.send("no i need to send an inquiry for lemon rice")
    s2_3 = test_step("Step 3: Strip NO, handle inquiry", "send your request" in r2_3.lower() or "lemon rice" in r2_3.lower(), "inquiry flow", r2_3)

    r2_4 = bot.send("nooo")
    s2_4 = test_step("Step 4: Frustration detected", "sorry" in r2_4.lower() or "menu" in r2_4.lower(), "apologetic or menu", r2_4)

    session = db.query(AIConversationSession).filter_by(customer_phone=bot.phone).first()
    fields = session.collected_fields or {}
    fields["pending_action_type"] = "clear_cart_confirm"
    session.collected_fields = fields
    session.category = "awaiting_yes_no"
    db.commit()
    r2_5 = bot.send("no")
    s2_5 = test_step("Step 5: clear_cart_confirm -> no", "safe" in r2_5.lower(), "cart is safe", r2_5)

    session.collected_fields = {"pending_action_type": "clear_cart_confirm"}
    session.category = "awaiting_yes_no"
    db.commit()
    r2_6 = bot.send("yes")
    s2_6 = test_step("Step 6: clear_cart_confirm -> yes", "cleared" in r2_6.lower(), "cart cleared", r2_6)

    # TEST 3: PRODUCT MATCHING
    print("\nVERIFICATION TEST 3 — PRODUCT MATCHING")
    bot.send("clear") # Clear cart explicitly
    r3_1 = bot.send("curd rice")
    s3_1 = test_step("Step 1: curd rice -> 0 score -> prompt", "isn't on our menu" in r3_1.lower(), "not found prompt", r3_1)

    r3_2 = bot.send("lemon rice")
    s3_2 = test_step("Step 2: lemon rice -> 0 score -> prompt", "isn't on our menu" in r3_2.lower(), "not found prompt", r3_2)

    r3_3 = bot.send("coke")
    s3_3 = test_step("Step 3: coke -> added", "added" in r3_3.lower() and "coco cola" in r3_3.lower(), "added coco cola", r3_3)

    r3_4 = bot.send("mashroom briyani")
    s3_4 = test_step("Step 4: mashroom briyani -> added", "added" in r3_4.lower() and "mushroom biryani" in r3_4.lower(), "added mushroom", r3_4)

    r3_5 = bot.send("chicken rice")
    s3_5 = test_step("Step 5: chicken rice -> added", "added" in r3_5.lower() and "chicken fried rice" in r3_5.lower(), "added chicken rice", r3_5)

    r3_6 = bot.send("2 parotta")
    s3_6 = test_step("Step 6: parotta -> not found (no quantity)", "2" not in r3_6.lower() and "parotta" in r3_6.lower() and "isn't on our menu" in r3_6.lower(), "no quantity in not found", r3_6)

    r3_7 = bot.send("biryani")
    s3_7 = test_step("Step 7: biryani -> ambiguous", "multiple" in r3_7.lower() or "which one" in r3_7.lower() or "1." in r3_7, "ask which one", r3_7)

    # TEST 4: PRODUCT DETAILS
    print("\nVERIFICATION TEST 4 — PRODUCT DETAILS")
    r4_1 = bot.send("tell me about coco cola")
    s4_1 = test_step("Step 1: coco cola details format", "•" in r4_1 and "a quality item" not in r4_1.lower() and "per unit" not in r4_1.lower() and "_" not in r4_1, "bullets, no raw text", r4_1)

    r4_2 = bot.send("tell me about ice cream")
    s4_2 = test_step("Step 2: ice cream details format", "•" in r4_2 and "_" not in r4_2, "bullets, no raw text", r4_2)

    r4_3 = bot.send("which size coke do you have")
    # should show details or just act like info
    s4_3 = test_step("Step 3: coke size query", "500ml" in r4_3.lower() and "_" not in r4_3, "shows 500ml", r4_3)

    # TEST 5: INQUIRY SYSTEM
    print("\nVERIFICATION TEST 5 — INQUIRY SYSTEM")
    r5_1 = bot.send("do you have lemon rice")
    s5_1 = test_step("Step 1: ask lemon rice -> 2 options", "1" in r5_1 and "2" in r5_1 and "inquire" in r5_1.lower(), "2 options", r5_1)
    
    r5_2 = bot.send("1")
    pi1 = db.query(PendingInquiry).filter_by(product_requested="Lemon Rice").first()
    s5_2 = test_step("Step 2: select 1 (inquire) -> db record", "send your request" in r5_2.lower() and pi1 is not None, "inquiry saved", r5_2)

    r5_3 = bot.send("2")
    # Wait, the state might have cleared, but let's test sending "menu" manually
    r5_3 = bot.send("menu")
    s5_3 = test_step("Step 3: menu -> shows menu", "₹" in r5_3 and "menu" in r5_3.lower() or "here" in r5_3.lower(), "menu shown", r5_3)

    r5_4 = bot.send("i need to send an inquiry for dosa")
    pi2 = db.query(PendingInquiry).filter_by(product_requested="Dosa").first()
    s5_4 = test_step("Step 4: explicit inquiry -> db record", pi2 is not None, "dosa in db", r5_4)

    # TEST 6: ORDER FLOW
    print("\nVERIFICATION TEST 6 — ORDER FLOW")
    bot.send("clear")
    r6_1 = bot.send("1 coke and 2 rose milk")
    s6_1 = test_step("Step 1: Add items", "added" in r6_1.lower() and "100" in r6_1.lower(), "total 100", r6_1)
    
    r6_2 = bot.send("place order")
    s6_2 = test_step("Step 2: place order -> ask delivery", "delivery" in r6_2.lower() or "pickup" in r6_2.lower() or "address" in r6_2.lower(), "delivery prompt", r6_2)
    
    r6_3 = bot.send("delivery")
    s6_3 = test_step("Step 3: delivery -> ask address", "address" in r6_3.lower(), "ask address", r6_3)
    
    r6_4 = bot.send("karuppana samy street karur")
    s6_4 = test_step("Step 4: provide address -> confirm", "karuppana" in r6_4.lower() and "total" in r6_4.lower(), "confirm prompt", r6_4)
    
    r6_5 = bot.send("yes")
    order = db.query(Order).order_by(Order.id.desc()).first()
    s6_5 = test_step("Step 5: order saved", "lev-" in r6_5.lower() and "booking" in r6_5.lower() and order.customer_name == "Rajesh", "booking id and name", r6_5)
    
    r6_6 = bot.send("order status")
    s6_6 = test_step("Step 6: order status", "booking" in r6_6.lower() and "pending" in r6_6.lower(), "status with booking", r6_6)

    # TEST 7: SHOP CATEGORY
    print("\nVERIFICATION TEST 7 — SHOP CATEGORY")
    # 1 and 2 are UI steps, we test via DB mutation
    shop = db.query(Shop).first()
    shop.shop_category = "Clothing & Fashion"
    shop.business_category = "Clothing & Fashion"
    db.commit()
    r7_3 = bot.send("show menu")
    s7_3 = test_step("Step 3: clothing category", "catalogue" in r7_3.lower() or "collection" in r7_3.lower(), "catalogue", r7_3)
    
    shop.shop_category = "General"
    shop.business_category = "General"
    db.commit()
    r7_4 = bot.send("show menu")
    s7_4 = test_step("Step 4: general category", "catalogue" in r7_4.lower() or "items" in r7_4.lower() or "products" in r7_4.lower(), "items", r7_4)

    # TEST 8: THINKING LAYER
    print("\nVERIFICATION TEST 8 — THINKING LAYER")
    session = db.query(AIConversationSession).filter_by(customer_phone=bot.phone).first()
    session.category = "awaiting_delivery_address"
    db.commit()
    r8_1 = bot.send("12 main street karur")
    s8_1 = test_step("Step 1: identify address", "confirm" in r8_1.lower() or "yes" in r8_1.lower(), "address confirm", r8_1)
    
    session = db.query(AIConversationSession).filter_by(customer_phone=bot.phone).first()
    fields = session.collected_fields or {}
    fields["pending_action_type"] = "upsell"
    session.collected_fields = fields
    session.category = "awaiting_yes_no"
    db.commit()
    r8_2 = bot.send("no thanks")
    s8_2 = test_step("Step 2: reject upsell via TL", "cart" in r8_2.lower() or "total" in r8_2.lower() or "what else" in r8_2.lower(), "cart unchanged", r8_2)
    
    bot.send("clear")
    r8_3 = bot.send("why?")
    s8_3 = test_step("Step 3: frustration why", "menu" in r8_3.lower() or "help" in r8_3.lower(), "help or menu", r8_3)
    
    r8_4 = bot.send("which size coke do you have")
    s8_4 = test_step("Step 4: variant query", "500ml" in r8_4.lower(), "size info", r8_4)
    
except Exception as e:
    print(f"ERROR RUNNING TESTS: {e}")
    traceback.print_exc()

