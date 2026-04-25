import logging
import traceback
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional
import random

from .intent_engine import IntentEngine
from .order_engine import OrderEngine
from .session_engine import SessionEngine
from .customer_memory import CustomerMemoryEngine
from .sales_engine import SalesEngine
from .. import models
from ..core.ai_client import AIClient

logger = logging.getLogger("levix.ai_router")

def _pick(*variants: str) -> str:
    return random.choice(variants)

GREET_REPLIES = ["Hey there! \ud83d\udc4b Welcome to *LEVIX*! What would you like to order today?", "Hi! Great to see you \ud83d\ude0a What are you craving?"]
ITEM_NOT_FOUND = ["Hmm, I couldn't find *{hint}* \ud83e\udd14 Could you be more specific?", "Sorry, *{hint}* isn't available."]
ITEM_ADDED = ["\u2705 Added *{qty}x {item}* to your cart! (₹{unit_price} each)\nCart total: *₹{total}*\n\nAnything else?"]
ITEM_REMOVED = ["Removed *{item}* from your cart \ud83d\udc4d Updated total: *₹{total}*"]
QTY_CHANGED = ["Updated! *{item}* is now *{new_qty}x* in your cart. Subtotal: *₹{subtotal}*"]
EMPTY_CART = ["Your cart is empty! Tell me what you'd like \u2014 e.g. _2 chicken biryani_ \ud83c\udf57"]
DELIVERY_PROMPT = "Perfect! \ud83d\ude97 Please share your delivery address.\n\n_(Street / flat no / area)_"
PICKUP_CONFIRM = "Great, you'll pick it up! \ud83c\udfea\nHere's your order:\n{summary}\n\nTotal: *₹{total}*\n\nShall I confirm this order? _(yes / no)_"
ADDRESS_RECEIVED = "Got it! Delivering to:\n_{address}_\n\nHere's your order:\n{summary}\n\nTotal: *₹{total}*\n\nConfirm order? _(yes / no)_"
ORDER_CONFIRMED = "\ud83c\udf89 Order placed successfully!\n{delivery_line}\nTotal: *₹{total}*\n\nWe'll notify you once it's ready!"
UNCLEAR_MESSAGE = ["Hmm, didn't quite catch that! Try saying something like:\n_'2 chicken biryani'_ or _'delivery'_ \ud83d\ude0a"]

class AIRouter:
    @classmethod
    def process_message(cls, db: Session, shop_id: int, customer_phone: str, message: str) -> str:
        try:
            session = SessionEngine.get_session(db, shop_id, customer_phone)
            shop = db.query(models.Shop).get(shop_id)
            profile = CustomerMemoryEngine.get_or_create_profile(db, shop_id, customer_phone)
            
            state = session.category or "idle"
            cart = session.collected_fields.get("cart", [])
            
            # 4. Alias Everywhere & 3. Multi-line Parser
            message = message.replace("coca cola", "coke").replace("coca-cola", "coke")
            lines = [m.strip() for m in message.split('\n') if m.strip()]
            if not lines: lines = [message]
            
            reply = ""
            updates = {}
            final_intent = ""
            
            for line in lines:
                intent_obj = IntentEngine().classify(line, session_state=state)
                intent = intent_obj.name
                entities = intent_obj.entities
                final_intent = intent
                
                # 8. Context Intent Aliases
                if line.lower() in ["add it", "same one", "repeat last combo"]:
                    intent = "repeat_last_order"
                
                # 2. Confirmation State Machine Guard
                if state == "awaiting_confirmation":
                    lower_line = line.lower()
                    if lower_line in ["no", "cancel"]:
                        updates["cart"] = []
                        updates["category"] = "shopping"
                        reply = "Cart cancelled. What else can I get you?"
                        continue
                    elif lower_line in ["change", "edit", "wait"]:
                        updates["category"] = "cart_active"
                        reply = "Sure, what would you like to change?"
                        continue
                    elif lower_line not in ["yes", "y", "confirm", "ok"]:
                        reply = "Please say *yes* to confirm your order, or *no* to cancel."
                        continue
                    else:
                        intent = "confirm_order"

                # 5. Cart Summary Intent
                if intent == "show_cart" or line.lower() in ["show cart", "cart details", "what's in cart"]:
                    summary = OrderEngine.cart_summary(cart)
                    if summary["is_empty"]: reply = _pick(*EMPTY_CART)
                    else:
                        line_strs = "\\n".join([f"• {i['qty']}x {i['name']}" for i in summary["items"]])
                        reply = f"Your cart:\\n{line_strs}\\nTotal: *₹{summary['total']}*"
                    continue

                if intent == "greet":
                    updates["category"] = "shopping"
                    reply = _pick(*GREET_REPLIES)

                elif intent == "add_item":
                    hint = entities.get("item_hint", line)
                    tokens = IntentEngine().extract_item_hint_tokens(hint)
                    qty = entities.get("quantity", 1)
                    spice = entities.get("spice_level")
                    
                    products = OrderEngine.find_products(db, shop_id, tokens, limit=1)
                    if not products:
                        reply = _pick(*ITEM_NOT_FOUND).format(hint=hint)
                    else:
                        cart, ctx = OrderEngine.cart_add(cart, products[0], qty, spice)
                        updates["cart"] = cart
                        updates["category"] = "cart_active"
                        summary = OrderEngine.cart_summary(cart)
                        reply = _pick(*ITEM_ADDED).format(qty=qty, item=products[0]["name"], unit_price=products[0]["price"], total=summary["total"])

                elif intent == "remove_item":
                    hint = entities.get("item_hint", line)
                    tokens = IntentEngine().extract_item_hint_tokens(hint)
                    cart, ctx = OrderEngine.cart_remove(cart, tokens)
                    updates["cart"] = cart
                    if not cart: updates["category"] = "shopping"
                    if ctx["action"] == "not_found":
                        reply = "Couldn't find that in your cart."
                    else:
                        summary = OrderEngine.cart_summary(cart)
                        reply = _pick(*ITEM_REMOVED).format(item=ctx["item"], total=summary["total"])

                elif intent == "change_quantity":
                    qty = entities.get("quantity", 1)
                    hint = entities.get("item_hint", "")
                    tokens = IntentEngine().extract_item_hint_tokens(hint) if hint else []
                    cart, ctx = OrderEngine.cart_change_quantity(cart, tokens, qty)
                    updates["cart"] = cart
                    if ctx["action"] == "not_found": reply = "Couldn't find that item."
                    elif ctx["action"] == "cart_empty": reply = _pick(*EMPTY_CART)
                    else: reply = _pick(*QTY_CHANGED).format(item=ctx["item"], new_qty=ctx["new_qty"], subtotal=ctx["subtotal"])

                elif intent == "spice_preference" or any(mod in line.lower() for mod in ["less spicy", "extra spicy", "no onion", "extra gravy"]):
                    modifier = line.lower()
                    if intent == "spice_preference": modifier = entities.get("spice_level", modifier)
                    
                    found = False
                    for item in reversed(cart):
                        name_lower = item["name"].lower()
                        if "coke" not in name_lower and "pepsi" not in name_lower and "water" not in name_lower and "drink" not in name_lower:
                            item["spice_level"] = modifier
                            found = True
                            reply = f"Got it! Added note to {item['name']}: {modifier} 🌶️"
                            break
                    if not found:
                        reply = "You don't have any food items in your cart to modify."
                    updates["cart"] = cart

                elif intent == "select_delivery":
                    if not cart: reply = _pick(*EMPTY_CART)
                    else:
                        updates["delivery_mode"] = "delivery"
                        updates["category"] = "awaiting_address"
                        reply = DELIVERY_PROMPT

                elif intent == "select_pickup":
                    if not cart: reply = _pick(*EMPTY_CART)
                    else:
                        updates["delivery_mode"] = "pickup"
                        updates["category"] = "awaiting_confirmation"
                        summary = OrderEngine.cart_summary(cart)
                        line_strs = "\\n".join([f"• {i['qty']}x {i['name']}" for i in summary["items"]])
                        reply = PICKUP_CONFIRM.format(summary=line_strs, total=summary["total"])

                elif intent == "provide_address" or state == "awaiting_address":
                    addr = entities.get("address_text", line).strip()
                    if not addr: addr = line.strip()
                    updates["delivery_address"] = addr
                    updates["category"] = "awaiting_confirmation"
                    summary = OrderEngine.cart_summary(cart)
                    line_strs = "\\n".join([f"• {i['qty']}x {i['name']}" for i in summary["items"]])
                    reply = ADDRESS_RECEIVED.format(address=addr, summary=line_strs, total=summary["total"])

                elif intent == "budget_query" or "under" in line.lower() or "budget" in line.lower():
                    import re
                    budget_match = re.search(r"under\s*(\d+)", line.lower())
                    budget = int(budget_match.group(1)) if budget_match else 700
                    
                    # 1. Category Combo Logic: Prioritize meals
                    items = db.query(models.InventoryItem).filter(
                        models.InventoryItem.shop_id == shop_id,
                        models.InventoryItem.price <= budget,
                        models.InventoryItem.quantity > 0,
                        func.lower(models.InventoryItem.category).in_(['food', 'meal', 'biryani', 'curry'])
                    ).limit(2).all()
                    
                    if not items:
                        reply = "Sorry, we couldn't find a combo under that budget."
                    else:
                        new_cart = list(cart)
                        added_names = []
                        for item in items:
                            new_cart, _ = OrderEngine.cart_add(new_cart, OrderEngine._product_to_dict(item), 1)
                            added_names.append(item.name)
                        cart = new_cart
                        updates["cart"] = cart
                        updates["category"] = "cart_active"
                        summary = OrderEngine.cart_summary(cart)
                        reply = f"I've built a combo for you: {' and '.join(added_names)}! Added to cart.\nCart total: *₹{summary['total']}*\n\nShall I confirm this? _(yes / no)_"

                elif intent == "confirm_order":
                    last_order_time = session.collected_fields.get("last_order_time")
                    if last_order_time:
                        last_dt = datetime.fromisoformat(last_order_time)
                        if (datetime.now(timezone.utc) - last_dt).total_seconds() < 60:
                            reply = "Your order is already confirmed 😊"
                            continue

                    summary = OrderEngine.cart_summary(cart)
                    if summary["is_empty"]:
                        reply = _pick(*EMPTY_CART)
                        updates["category"] = "shopping"
                    else:
                        mode = session.collected_fields.get("delivery_mode", "pickup")
                        addr = session.collected_fields.get("delivery_address", "")
                        
                        idem = OrderEngine.build_idempotency_key(customer_phone, cart, datetime.utcnow().strftime("%Y%m%d%H%M"))
                        
                        product_summary = "\\n".join([f"{i['qty']}x {i['name']} - ₹{i['subtotal']}" for i in summary["items"]])
                        total_price = summary["total"]
                        method_str = f"\\nDelivery to: {addr}" if mode == "delivery" else "\\nPickup at Store"
                        final_summary = f"{product_summary}\\nTotal: ₹{total_price}{method_str}"
                        
                        # 6. Real Order Write Verification
                        try:
                            new_order = models.Order(
                                shop_id=shop_id,
                                customer_name=profile.customer_name or customer_phone,
                                customer_phone=customer_phone,
                                total_amount=total_price,
                                status="pending",
                                shipping_address=addr if mode == "delivery" else "PICKUP",
                                cart_snapshot={"items": summary["items"]}
                            )
                            db.add(new_order)
                            db.commit()
                            db.refresh(new_order)
                            
                            SalesEngine.create_lead(db, shop_id, session, final_summary, "ORDER", None)
                            
                            # 7. Last Order Accuracy
                            CustomerMemoryEngine.record_order(db, profile, product_summary, total=total_price)
                            
                            d_line = f"📍 Delivering to: _{addr}_" if mode == "delivery" else "🏪 Pickup from store"
                            reply = ORDER_CONFIRMED.format(delivery_line=d_line, total=total_price)
                            
                            updates["category"] = "completed"
                            updates["cart"] = []
                            updates["last_order_time"] = datetime.now(timezone.utc).isoformat()
                        except Exception as db_err:
                            logger.error(f"DB WRITE FAILED: {db_err}")
                            db.rollback()
                            reply = "Sorry, our system failed to save your order. Please try again later."
                            break

                elif intent == "repeat_last_order":
                    if not profile.last_order_summary:
                        reply = "Looks like you haven't ordered from us before. What would you like?"
                    else:
                        reply = f"Last time you ordered: {profile.last_order_summary}. Just tell me to add it!"

                else:
                    if not reply:
                        reply = _pick(*UNCLEAR_MESSAGE)

            if "category" in updates: session.category = updates["category"]
            new_fields = dict(session.collected_fields)
            if "cart" in updates: new_fields["cart"] = updates["cart"]
            if "delivery_mode" in updates: new_fields["delivery_mode"] = updates["delivery_mode"]
            if "delivery_address" in updates: new_fields["delivery_address"] = updates["delivery_address"]
            if "last_order_time" in updates: new_fields["last_order_time"] = updates["last_order_time"]
            
            session.collected_fields = new_fields
            SessionEngine.set_intent(db, session, final_intent)
            SessionEngine.update_history(db, session, "user", message)
            SessionEngine.update_history(db, session, "assistant", reply)
            
            db.commit()
            return reply

        except Exception as e:
            logger.error(f"[ROUTER CRASH] {e}\\n{traceback.format_exc()}")
            return "Vanakkam! 🙏 We're experiencing an issue, our team will get back to you."
