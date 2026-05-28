# -*- coding: utf-8 -*-
"""
router_engine.py — LEVIX Central Message Router (v4)
All P0/P1/P2 production fixes applied.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 9 — CANONICAL CHATBOT FLOW (source of truth)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEW CUSTOMER:
  Bot → "Hi! Welcome to [Business Name] 😊 What's your name?"
  Customer → [name]
  Validate: if name is a greeting word (hi/hey/hello…) → ask again
  Bot → "Nice to meet you, [Name]! What's your phone number? (10 digits)"
  Customer → [phone]
  Validate: must be 10 digits. Max 2 retries then skip.
  MemoryEngine.flush() + ConversationEngine.flush() → IDLE
  Bot → "Perfect! Here's what we have today 👇" + product list
  State → BROWSING

RETURNING CUSTOMER:
  Bot → "Welcome back, [Name]! 😊 Want your usual [last item] again
          or shall I show you everything?"

BROWSING:
  menu request       → formatted product list with prices
  product_info       → 2-4 bullet points + CTA (see _handle_product_info)
  unavailable item   → reply + MissingProductRequest DB insert

ADDING TO CART (add_item / multi_add_items):
  1. Normalise: _apply_typo_corrections() + category aliases
  2. Fuzzy match   (name / category / product_details)
  3. If score == 0 → NOT added → treated as stock_check → pending inquiry
  4. If out of stock → suggest replacement
  5. If ambiguous (multiple matches) → ask clarification
  6. Add to cart → confirm with upsell

  Multi-item phrases:
    "X and Y", "X with Y", "X, Y and Z"  → multi_add_items
    "single X"  → qty=1
    "one X"     → qty=1
    "couple X"  → qty=2
    "few X"     → qty=3
    "2 X and 1 Y" → [X qty=2, Y qty=1]

CHECKOUT:
  Step 1 → cart summary
  Step 2 → pickup or delivery?
  Step 3 → if delivery: ask address
  Step 4 → show total + delivery fee
  Step 5 → confirm yes/no
  Step 6 → DB write → generate LEV-XXXXXXXX booking_id + 5-digit order_id
  Step 7 → order_confirmed_full() with dividers

POST ORDER:
  status check  → booking ID + order ID + status + items
  cancel order  → 2-step confirm → DB update + SSE broadcast

PRODUCT MATCHING PIPELINE (order_engine.find_products):
  1. Exact name match
  6. Keyword overlap scoring
  7. score == 0 → return [] → stock_check + pending_inquiry
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import logging
import random
import re
import traceback
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from .conversation_engine import ConversationEngine
from .intent_engine import IntentEngine, parse_multi_items
from .memory_engine import MemoryEngine
from .order_engine import OrderEngine
from .recommendation_engine import RecommendationEngine
from .sales_engine import SalesEngine
from .validation_engine import ValidationEngine
from .message_formatter import MessageFormatter
from .. import models

logger = logging.getLogger("levix.router")

# ── Order statuses ─────────────────────────────────────────────────────────────
ORDER_STATUSES = ["PENDING", "CONFIRMED", "PREPARING", "READY", "DELIVERED", "CANCELLED"]

_ALIASES: dict[str, str] = {
    "coca cola": "coke",
    "coca-cola": "coke",
    "pepsi cola": "pepsi",
}

def _normalise(text: str) -> str:
    low = text.lower()
    for src, tgt in _ALIASES.items():
        low = low.replace(src, tgt)
    return low

def _gen_order_number() -> str:
    """5-digit human-friendly order number."""
    return str(random.randint(10000, 99999))

def _gen_booking_id() -> str:
    """Change 6: Generate LEV-XXXXXXXX booking ID."""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "LEV-" + "".join(random.choice(chars) for _ in range(8))


# ═══════════════════════════════════════════════════════════════════════════════
class RouterEngine:

    @classmethod
    def process_message(cls, db: Session, shop_id: int, customer_phone: str, raw_message: str) -> str:
        logger.info("[ROUTER] Using GuidedConversationEngine")
        from .guided_conversation_engine import GuidedConversationEngine
        return GuidedConversationEngine.process_message(db, str(shop_id), customer_phone, raw_message)

    @classmethod
    def _route(cls, ctx: "_Context", score: int) -> str:
        logger.error("[LEGACY ROUTER] CRITICAL: _route called! This flow is disabled.")
        raise Exception("[LEGACY ROUTER] _route is disabled. Use GuidedConversationEngine instead.")

    # ── Handlers ──────────────────────────────────────────────────────────────

    # Greeting words that must never be stored as customer names
    _GREETING_WORDS = {
        "hi", "hello", "hey", "hiya", "yo", "sup", "helo", "hii", "hiii",
        "hai", "heyy", "heya", "howdy", "greetings", "namaste", "vanakkam",
    }

    # ── Change 4: Onboarding Flow ─────────────────────────────────────────────
    @classmethod
    def _handle_onboarding(cls, ctx: "_Context") -> str:
        step = ctx.mem.session.onboarding_step
        msg  = ctx.message.strip()
        
        # If this is the first message (turn_count 1 because it's incremented in process_message)
        # and we just started onboarding, give a warmer welcome.
        if step == "collect_name" and getattr(ctx.session, "turn_count", 0) <= 1 and msg.lower() in cls._GREETING_WORDS:
            return f"Welcome to *{ctx.shop_name}*! \U0001f31f I'm your AI assistant.\n\nTo get started, what's your name?"

        if step == "collect_name":
            # Bug 11: Prevent intents from being taken as names
            ie = IntentEngine()
            intent_obj = ie.classify(msg, session_state="idle")
            if intent_obj.name not in ("unrecognizable_fallback", "greet", "user_name_update") and intent_obj.understanding_score > 60:
                return f"I see you want to *{intent_obj.name.replace('_', ' ')}* \u263a But first, what's your name?"

            if len(msg) < 2 or any(c.isdigit() for c in msg):
                return "That doesn't look like a name \U0001f914 Please send your name to get started."
            if msg.lower() in cls._GREETING_WORDS:
                return "That sounds like a greeting \U0001f60a What's your actual name?"
            
            placeholders = {"vip", "customer", "unknown", "guest", "none", "null"}
            if msg.lower() in placeholders:
                return "Please provide your actual name to continue \U0001f60a"
            
            clean_name = " ".join(w.capitalize() for w in msg.split())[:50]
            ctx.mem.profile.customer_name = clean_name
            ctx.mem.session.customer_name = clean_name
            ctx.mem.session.onboarding_step = "collect_phone"
            return MessageFormatter.onboarding_phone(clean_name)

        if step == "collect_phone":
            digits = "".join(filter(str.isdigit, msg))
            if len(digits) != 10:
                ctx.mem.session.retry_phone_count += 1
                if ctx.mem.session.retry_phone_count >= 2:
                    ConversationEngine.transition(ctx.db, ctx.session, "idle")
                    ctx.mem.session.onboarding_step = None
                    MemoryEngine.flush(ctx.db, ctx.session, ctx.mem)
                    ConversationEngine.flush(ctx.db, ctx.session)
                    return MessageFormatter.onboarding_complete()
                return MessageFormatter.onboarding_phone_invalid()

            ConversationEngine.transition(ctx.db, ctx.session, "idle")
            ctx.mem.session.onboarding_step = None
            ctx.mem.session.retry_phone_count = 0

            if not ctx.mem.profile.customer_name:
                ctx.mem.profile.customer_name = ctx.customer_phone

            MemoryEngine.flush(ctx.db, ctx.session, ctx.mem)
            ConversationEngine.flush(ctx.db, ctx.session)
            return MessageFormatter.onboarding_complete()

        ConversationEngine.transition(ctx.db, ctx.session, "idle")
        return MessageFormatter.greet(ctx.shop_name, action=MessageFormatter._get_terms(ctx.shop_category)["action"])

    @classmethod
    def _handle_product_info(cls, ctx: "_Context") -> str:
        hint = ctx.entities.get("item_hint")
        if not hint: return MessageFormatter.unclear()
        products = OrderEngine.find_products(ctx.db, ctx.shop_id, hint.split(), limit=1, shop_category=ctx.shop_category)
        if not products: return cls._handle_add_item(ctx)
        p = products[0]
        
        # FAIL 4.3: variant_query detection
        if ctx.entities.get("sub_type") == "variant_query":
            details = p.get("product_details", "").lower()
            size_keywords = ["ml", "litre", "liter", "l", "gram", "kg", "size", "capacity", "serving", "piece", "pack"]
            found_info = None
            for kw in size_keywords:
                # Look for patterns like "500ml", "1 liter", etc.
                match = re.search(rf"\d+\s*{kw}", details)
                if match:
                    found_info = match.group(0)
                    break
            
            if found_info:
                return f"*{p['name']}* comes in {found_info} size \U0001f60a\n\nWant me to add it to your cart?"
            else:
                return f"I don't have exact size details for *{p['name']}* right now. Type *inquire* and I'll ask the owner for you!"

        raw_details = p.get("product_details", "")
        points = [pt.strip() for pt in re.split(r"[\n;.]", raw_details) if len(pt.strip()) > 3] if raw_details else []
        # Limit to 4 meaningful points
        points = points[:4]
        return MessageFormatter.product_info(name=p["name"], price=p["price"], points=points, shop_category=ctx.shop_category)

    @staticmethod
    def _handle_greet(ctx):
        # FAIL 1.7: Returning customer uses real name
        cust_name = ctx.mem.profile.customer_name or "there"
        ConversationEngine.transition(ctx.db, ctx.session, "browsing")
        # Clear stale pending actions on greeting
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload = None
        
        if ctx.mem.is_returning_customer:
            wb = ctx.mem.welcome_back_message()
            if wb:
                # Replace generic VIP/Customer with real name if possible
                wb = wb.replace("VIP", cust_name).replace("Customer", cust_name)
                return wb
            return f"Welcome back, {cust_name}! \U0001f60a Ready to order?"
            
        return MessageFormatter.greet(ctx.shop_name, action=MessageFormatter._get_terms(ctx.shop_category)["action"])

    @staticmethod
    def _handle_checkout_start(ctx):
        """Bug 3 fix: 'enough', 'place order', 'confirm cart' → show summary + ask mode."""
        cart = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()
        summary = OrderEngine.cart_summary(cart)
        lines = "\n".join(
            f"\u2022 {i['qty']}x {i['name']} \u20b9{i['unit_price'] * i['qty']:.0f}"
            for i in summary.items
        )
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_delivery_mode")
        return (
            f"\u2705 *Order Summary*\n{lines}\n\n"
            f"*Total: \u20b9{summary.total:.0f}*\n\n"
            f"How would you like to receive it?\n"
            f"Reply *pickup* or *delivery*"
        )

    @staticmethod
    def _handle_pending_yes(ctx):
        """Execute the pending action stored in session."""
        action  = ctx.mem.session.pending_action_type
        payload = ctx.mem.session.pending_payload or {}
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload     = None
        ctx.mem.session.pending_created_at  = None

        if action == "log_missing_product":
            product_name = payload.get("product_name", "item")
            category_context = payload.get("category_context", "")
            OrderEngine.log_missing_product(
                ctx.db, ctx.shop_id, ctx.customer_phone, ctx.mem.profile.customer_name or "Customer",
                product_name, message_text=f"Interested in {product_name} ({category_context})"
            )
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")
            return MessageFormatter.missing_product_noted(product_name)

        if action == "cancel_order_confirm":
            order_id = payload.get("order_id")
            # Reuse existing cancel logic
            ctx.entities["order_number"] = str(order_id)
            return cls._handle_cancel_existing_order_final(ctx)

        if action == "clear_cart_confirm":
            ctx.mem.session.cart             = []
            ctx.mem.session.delivery_mode    = None
            ctx.mem.session.delivery_address = None
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")
            return "Cart cleared \U0001f44d What would you like to order?"

        ConversationEngine.transition(ctx.db, ctx.session, "shopping")
        return "Done! What else can I help with? \U0001f60a"

    @staticmethod
    def _handle_pending_no(ctx):
        action = ctx.mem.session.pending_action_type
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload     = None
        ctx.mem.session.pending_created_at  = None
        
        # FAIL 2.1: Standalone "no" during shopping
        if ctx.state in ("browsing", "shopping", "cart_active") and not action:
            return "No problem! Let me know what you'd like \U0001f60a"

        ConversationEngine.transition(ctx.db, ctx.session, "browsing")
        if action == "log_missing_product":
            return "No problem! Let me know what else you'd like \U0001f60a"
        if action == "cancel_order_confirm":
            return f"No problem, your order *#{ctx.mem.session.pending_payload.get('order_id')}* is still active. \U0001f44d"
        if action == "clear_cart_confirm" or ctx.state == "awaiting_clear_confirm":
            return "No problem! Your cart is safe \U0001f60a"
        return "Okay! What else can I help with? \U0001f60a"



    @staticmethod
    def _handle_inquire_product(ctx):
        # FAIL 4.7: Clean product requested field
        hint = ctx.mem.session.pending_inquiry_product or ctx.entities.get("item_hint", ctx.message).strip()
        
        # 1. Strip quantities and filler words
        clean_hint = re.sub(r"^\d+\s*", "", hint)
        fillers = ["some", "the", "a", "an", "please", "need", "one", "two", "three", "single"]
        for f in fillers:
            clean_hint = re.sub(rf"\b{f}\b", "", clean_hint, flags=re.IGNORECASE)
        
        clean_hint = clean_hint.strip().capitalize()[:100]
        
        # Legacy PendingRequest for backwards-compatibility
        inquiry = models.PendingRequest(
            shop_id=ctx.shop_id,
            customer_name=ctx.mem.profile.customer_name or "Customer",
            customer_phone=ctx.customer_phone,
            product_name=clean_hint,
            customer_message=ctx.message,
            request_type="customer"
        )
        ctx.db.add(inquiry)
        
        # CRM ConversationSession integration
        from datetime import datetime, timezone
        active_session = ctx.db.query(models.ConversationSession).filter(
            models.ConversationSession.shop_id == ctx.shop_id,
            models.ConversationSession.customer_phone == ctx.customer_phone,
            models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
        ).first()
        
        try:
            if not active_session:
                from .guided_conversation_engine import get_auto_category
                inq_num = models.ConversationSession.generate_unique_number(ctx.db)
                category_id = get_auto_category(ctx.db, ctx.shop_id, ctx.customer_phone, "INQUIRY")
                active_session = models.ConversationSession(
                    shop_id=ctx.shop_id,
                    customer_name=ctx.mem.profile.customer_name or "Customer",
                    customer_phone=ctx.customer_phone,
                    status="NEW",
                    inquiry_number=inq_num,
                    conversation_type="INQUIRY",
                    category_id=category_id
                )
                ctx.db.add(active_session)
                ctx.db.flush()
            else:
                active_session.status = "NEW"
                
            new_msg = models.ConversationMessage(
                session_id=active_session.id,
                sender_type="CUSTOMER",
                message=f"Product Inquiry: {clean_hint}\nMessage: {ctx.message}"
            )
            ctx.db.add(new_msg)
            active_session.updated_at = datetime.now(timezone.utc)
            active_session.last_message_at = datetime.now(timezone.utc)
            ctx.db.commit()
            
            from .sse import broadcast_event
            broadcast_event(ctx.shop_id, "conversation_updated")
        except Exception as e:
            ctx.db.rollback()
            import logging
            logging.getLogger("levix.router").error(f"[ROUTER INQUIRY ERROR] {e}")
            
        ctx.mem.session.pending_inquiry_product = None
        ConversationEngine.transition(ctx.db, ctx.session, "browsing")
        return f"Sent! The owner will be notified \U0001f4e9"

    @staticmethod
    def _handle_add_item(ctx):
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        qty    = ctx.entities.get("quantity", 1)
        spice  = ctx.entities.get("spice_level")
        qty_mode = ctx.entities.get("qty_mode", "set")

        # Gap 6: Multi-match clarification
        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=3, shop_category=ctx.shop_category)
        # FAIL 3.5: Threshold logic and FAIL 3.6 Clean name
        if not products:
            clean_hint = re.sub(r"^\d+\s*", "", hint).title()
            ctx.mem.session.pending_inquiry_product = clean_hint
            ConversationEngine.transition(ctx.db, ctx.session, "awaiting_inquiry_or_menu")
            return (
                f"Sorry, *{clean_hint}* isn't on our {MessageFormatter._get_terms(ctx.shop_category)['catalogue']} right now \U0001f614\n\n"
                f"What would you like to do?\n"
                f"1\ufe0f\u20e3 Type *inquire* \u2014 I'll send your request to the owner\n"
                f"2\ufe0f\u20e3 Type *menu* \u2014 See what's available"
            )

        # FAIL 3.5: Direct-add threshold 88+. 65-87 clarification.
        best_product = products[0]
        score = best_product.get("match_score", 0)
        
        if score < 88 and len(products) == 1:
            # Ambiguous but only one option exists
            pass # Add directly as per requirements
        elif score < 88 or len(products) > 1:
            if ctx.state != "awaiting_clarification":
                ctx.mem.session.ambiguous_options = products
                ConversationEngine.transition(ctx.db, ctx.session, "awaiting_clarification")
                options = "\n".join([f"{i+1}. *{p['name']}* \u2014 \u20b9{p['price']:.0f}" for i, p in enumerate(products)])
                return f"Did you mean one of these?\n{options}\n3. Something else"

        product = products[0]
        if product.get("stock", product.get("max_qty_per_order", 1)) <= 0:
            repl = RecommendationEngine.replacement_for(ctx.db, ctx.shop_id, product["name"], product.get("category"))
            if repl:
                return MessageFormatter.item_out_of_stock(item=product["name"]) + f"\n\nHow about *{repl['name']}* instead? (\u20b9{repl['price']:.0f})"
            return MessageFormatter.item_out_of_stock(item=product["name"])

        # Gap 4: Handle relative/absolute quantity
        cart = ctx.mem.session.cart
        if qty_mode == "add":
            # Find item in cart
            existing = next((i for i in cart if i["id"] == product["id"]), None)
            if existing:
                qty = existing["qty"] + qty
            elif ctx.mem.session.last_item_id:
                # Add to last item instead? No, requirements say "increase last added item by 2"
                last_item = next((i for i in cart if i["id"] == ctx.mem.session.last_item_id), None)
                if last_item:
                    last_item["qty"] += qty
                    qty = last_item["qty"]
                    product = last_item
        elif qty_mode == "set" and "make it" in ctx.message.lower():
             last_item = next((i for i in cart if i["id"] == (ctx.mem.session.last_item_id or (cart[-1]["id"] if cart else None))), None)
             if last_item:
                 last_item["qty"] = qty
                 product = last_item

        # Clear stale pending action
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload = None

        cart, result = OrderEngine.cart_add(cart, product, qty, spice)
        ctx.mem.session.cart = cart
        ctx.mem.session.last_item_id = product["id"]
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        summary = OrderEngine.cart_summary(cart)
        ctx.mem.session.upsell_active = False
        upsell = None
        if summary.total < 600:
            ui = RecommendationEngine.upsell_for(ctx.db, ctx.shop_id, cart, budget_left=200)
            if ui:
                upsell = ui["name"]
                ctx.mem.session.upsell_active = True
                ctx.mem.session.upsell_product = upsell

        reply = MessageFormatter.item_added(
            qty=qty, 
            item=product["name"],
            unit_price=product["price"],
            total=summary.total,
            upsell=upsell,
        )
        return reply

    @staticmethod
    def _handle_multi_add(ctx):
        """Handle "2 fried rice, 1 coke, 1 rose milk" in one shot."""
        items_to_add = ctx.entities.get("multi_items") or parse_multi_items(ctx.message)
        if not items_to_add:
            return RouterEngine._handle_add_item(ctx)

        cart    = ctx.mem.session.cart
        added   = []
        missing = []

        for entry in items_to_add:
            tokens   = IntentEngine.extract_item_hint_tokens(entry["hint"])
            qty      = entry.get("quantity", 1)
            products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1, shop_category=ctx.shop_category)
            if not products:
                OrderEngine.log_missing_product(
                    ctx.db, ctx.shop_id, ctx.customer_phone, ctx.mem.profile.customer_name or "Customer", 
                    entry["hint"]
                )
                missing.append(entry["hint"])
            else:
                product = products[0]
                cart, result = OrderEngine.cart_add(cart, product, qty)
                added.append((qty, product['name']))

        ctx.mem.session.cart = cart
        if added:
            ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        summary = OrderEngine.cart_summary(cart)

        lines = "\n".join(f"\u2705 {qty}x {name}" for qty, name in added)
        reply = f"Added to cart:\n{lines}\n\n*Cart total: \u20b9{summary.total:.0f}*"
        if missing:
            reply += f"\n\n_Could not find: {', '.join(missing)}_"
        
        reply += "\n\nAnything else?"
        return reply

    @staticmethod
    def _handle_remove_item(ctx):
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        qty_to_remove = ctx.entities.get("quantity")  # None if no number specified
        cart   = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()

        from .order_engine import OrderEngine, CartItem
        items = [CartItem.from_dict(i) for i in cart]
        target = OrderEngine._match_cart_item(items, tokens) if tokens else items[-1]

        if not target:
            return "I couldn't find that in your cart \U0001f60a"

        if qty_to_remove is not None and target.quantity > qty_to_remove:
            target.quantity -= qty_to_remove
            action = "reduced"
        else:
            items.remove(target)
            action = "removed"

        ctx.mem.session.cart = [i.to_dict() for i in items]
        if not items:
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")
            return f"Removed {target.name}. Your cart is now empty! \U0001f60a"

        summary = OrderEngine.cart_summary(ctx.mem.session.cart)
        if action == "reduced":
            return f"Reduced *{target.name}* to {target.quantity}. Subtotal: \u20b9{target.subtotal:.0f}"
        return MessageFormatter.item_removed(item=target.name, total=summary.total)

    @staticmethod
    def _handle_change_quantity(ctx):
        qty    = ctx.entities.get("quantity", 1)
        hint   = ctx.entities.get("item_hint", "")
        tokens = IntentEngine.extract_item_hint_tokens(hint) if hint else []
        cart   = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()
        cart, result = OrderEngine.cart_change_quantity(cart, tokens, qty)
        ctx.mem.session.cart = cart
        if result["action"] in ("cart_empty", "not_found"):
            return "I couldn't find that in your cart \U0001f60a. Try saying *show cart* to see your items."
        return MessageFormatter.quantity_updated(item=result["item"], new_qty=result["new_qty"], subtotal=result["subtotal"])

    @staticmethod
    def _handle_set_preference(ctx):
        spice = ctx.entities.get("spice_level")
        veg   = ctx.entities.get("veg_preference")
        if spice:
            cart = ctx.mem.session.cart
            if cart:
                cart, result = OrderEngine.cart_apply_spice(cart, spice)
                ctx.mem.session.cart = cart
                if result["action"] == "spice_set":
                    return MessageFormatter.spice_noted(item=result["item"], modifier=spice)
            ctx.mem.note_preference(spice_level=spice)
            return f"Got it! I'll remember you prefer *{spice}* \U0001f336\ufe0f"
        if veg:
            ctx.mem.note_preference(veg_preference=veg)
            return f"Noted! Filtering to *{'veg' if veg == 'veg' else 'non-veg'}* options \U0001f60a"
        return MessageFormatter.unclear()

    @staticmethod
    def _handle_show_cart(ctx):
        summary = OrderEngine.cart_summary(ctx.mem.session.cart)
        if summary.is_empty:
            return MessageFormatter.empty_cart()
        return MessageFormatter.cart_summary(summary.items, summary.total)

    @staticmethod
    def _handle_clear_cart(ctx):
        if not ctx.mem.session.cart:
            return MessageFormatter.empty_cart()
        ctx.mem.session.pending_action_type = "clear_cart_confirm"
        ctx.mem.session.pending_payload     = {}
        ctx.mem.session.pending_created_at  = datetime.now(timezone.utc).isoformat()
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
        return "Are you sure you want to clear your cart? *(yes / no)*"

    @staticmethod
    def _handle_clear_cart_confirmed(ctx):
        ctx.mem.session.cart = []
        ctx.mem.session.delivery_mode   = None
        ctx.mem.session.delivery_address = None
        ConversationEngine.transition(ctx.db, ctx.session, "shopping")
        return "Cart cleared \U0001f44d What would you like to order?"

    @staticmethod
    def _handle_select_delivery(ctx):
        if not ctx.mem.session.cart:
            return MessageFormatter.empty_cart()
        ctx.mem.session.delivery_mode = "delivery"
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_address")
        return MessageFormatter.delivery_prompt()

    @staticmethod
    def _handle_select_pickup(ctx):
        if not ctx.mem.session.cart:
            return MessageFormatter.empty_cart()
        ctx.mem.session.delivery_mode = "pickup"
        summary = OrderEngine.cart_summary(ctx.mem.session.cart)
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_confirmation")
        return MessageFormatter.pickup_confirmation(summary.items, summary.total)

    @staticmethod
    def _handle_provide_address(ctx):
        addr = ctx.entities.get("address_text", ctx.message).strip()
        vr   = ValidationEngine.address(addr)
        if not vr:
            return MessageFormatter.address_clarify()

        ctx.mem.session.delivery_address = vr.cleaned
        summary = OrderEngine.cart_summary(ctx.mem.session.cart)
        fee     = OrderEngine.delivery_fee(summary.total, ctx.shop_settings)
        total   = round(summary.total + fee, 2)
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_confirmation")

        reply = MessageFormatter.address_received(address=vr.cleaned, items=summary.items, total=total)
        if fee > 0:
            reply += f"\n_(\u20b9{fee:.0f} delivery charge included)_"
        return reply

    @staticmethod
    def _handle_change_address(ctx):
        ctx.mem.session.delivery_address = None
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_address")
        return MessageFormatter.delivery_prompt()

    @staticmethod
    def _handle_confirm_order(ctx):
        logger.error(f"[LEGACY ROUTER] CRITICAL: Legacy _handle_confirm_order called! This flow is disabled. State: {ctx.session.category if ctx.session else 'None'}")
        raise Exception("[LEGACY ROUTER] _handle_confirm_order is disabled. Use GuidedConversationEngine instead.")

    @staticmethod
    def _handle_cancel_order(ctx):
        """Bug 3 fix: Cancel checkout flow only. Cart is NOT cleared unless explicit."""
        # If we're in a checkout flow, cancel the checkout but keep the cart
        if ctx.session.category in ("awaiting_confirmation", "awaiting_delivery_mode", "awaiting_address"):
            ctx.mem.session.delivery_mode = None
            ctx.mem.session.delivery_address = None
            ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
            return "Checkout cancelled \U0001f44d Your cart is still intact. Need to change anything?"

        # If we're in awaiting_yes_no (upsell), just reject
        if ctx.session.category == "awaiting_yes_no":
            ctx.mem.session.pending_action_type = None
            ctx.mem.session.pending_payload = None
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")
            return "No problem! What else can I help with? \U0001f60a"

        # Only clear cart if user has no active checkout and explicitly says cancel
        if not ctx.mem.session.cart:
            return "I'm here \U0001f60a What would you like to order?"

        # Cart exists but not in checkout — ask for confirmation before clearing
        ctx.mem.session.pending_action_type = "clear_cart_confirm"
        ctx.mem.session.pending_payload = {}
        ctx.mem.session.pending_created_at = datetime.now(timezone.utc).isoformat()
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
        return "You have items in your cart. Do you want to clear it? *(yes / no)*"

    @staticmethod
    def _handle_yes_with_modification(ctx):
        """User said "yes add coke too" — treat as cart modification, not confirm."""
        extra = ctx.entities.get("modification_text", "")
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        # Re-route the extra part as add_item
        sub_ctx = _Context(
            db=ctx.db, shop_id=ctx.shop_id, shop_name=ctx.shop_name,
            shop_settings=ctx.shop_settings, business_category=ctx.business_category,
            business_subnote=getattr(ctx, 'business_subnote', ''),
            customer_phone=ctx.customer_phone,
            message=extra, session=ctx.session, mem=ctx.mem,
            state="cart_active", entities={"item_hint": extra}, intent="add_item",
        )
        return RouterEngine._handle_add_item(sub_ctx)

    @staticmethod
    def _handle_edit_cart(ctx):
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        return MessageFormatter.cart_edit_prompt()

    @staticmethod
    def _handle_repeat_last_order(ctx):
        summary = ctx.mem.last_order_summary
        if not summary:
            return MessageFormatter.no_previous_order()
        return MessageFormatter.repeat_order_prompt(summary=summary)

    @staticmethod
    def _handle_budget_request(ctx):
        budget = ctx.entities.get("budget") or ctx.mem.estimated_budget
        people = ctx.entities.get("group_size", 1)
        spice  = ctx.entities.get("spice_level")
        veg    = ctx.entities.get("veg_preference")

        if not budget:
            return "What's your budget? I'll build the perfect combo \U0001f60a"

        ctx.mem.note_preference(budget=float(budget), group_size=int(people) if people else None,
                                spice_level=spice, veg_preference=veg)

        result = RecommendationEngine.combo_under_budget(
            ctx.db, ctx.shop_id, float(budget), people=int(people), veg_only=(veg == "veg"))

        if result.is_empty:
            return f"Hmm, no combo under \u20b9{budget:.0f} right now \U0001f614 Want to see the full menu?"

        cart = ctx.mem.session.cart
        for item in result.items:
            cart, _ = OrderEngine.cart_add(cart, item, item.get("qty", 1), spice)
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        return MessageFormatter.recommendation_budget(budget=float(budget), items=result.items, total=result.total)

    @staticmethod
    def _handle_group_meal_request(ctx):
        people = ctx.entities.get("group_size", 2)
        budget = ctx.entities.get("budget") or ctx.mem.estimated_budget

        if not budget:
            ctx.mem.note_preference(group_size=int(people))
            return f"Sure! For {people} people \u2014 what's your budget? \U0001f60a"

        result = RecommendationEngine.group_meal(ctx.db, ctx.shop_id, people=int(people), budget=float(budget))
        if result.is_empty:
            return f"Couldn't build a group meal for {people} under \u20b9{budget:.0f} right now \U0001f614"

        cart = ctx.mem.session.cart
        for item in result.items:
            cart, _ = OrderEngine.cart_add(cart, item, item.get("qty", 1))
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        return MessageFormatter.recommendation_budget(budget=float(budget), items=result.items, total=result.total)

    @staticmethod
    def _handle_vague_request(ctx):
        if not ctx.mem.session.budget and not ctx.mem.estimated_budget:
            return "What's your budget? I'll suggest the best option! \U0001f60a"
        if not ctx.mem.session.group_size:
            return "How many people are we ordering for? \U0001f60a"
        result = RecommendationEngine.popular_items(ctx.db, ctx.shop_id, limit=4)
        if result.is_empty:
            return "Tell me what you'd like \U0001f60a"
        return MessageFormatter.recommendation_general(result.items)

    @staticmethod
    def _handle_recommendation(ctx):
        result = RecommendationEngine.popular_items(ctx.db, ctx.shop_id, limit=4)
        if result.is_empty:
            return "Let me know what you'd like \u2014 I'll find it for you \U0001f60a"
        return MessageFormatter.recommendation_general(result.items)

    @staticmethod
    def _handle_view_menu(ctx):
        items = RecommendationEngine.menu_items(ctx.db, ctx.shop_id, limit=8)
        return MessageFormatter.menu(items, category=ctx.shop_category)

    @staticmethod
    def _handle_ask_price(ctx):
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        if not tokens:
            return "Which item would you like the price for? \U0001f60a"
        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1, shop_category=ctx.shop_category)
        if not products:
            return MessageFormatter.item_not_found(hint=hint)
        product = products[0]
        raw_details = product.get("product_details", "")
        points = [pt.strip() for pt in re.split(r"[\n;.]", raw_details) if len(pt.strip()) > 3] if raw_details else []
        return MessageFormatter.product_info(name=product["name"], price=product["price"], points=points, shop_category=ctx.shop_category)

    @staticmethod
    def _handle_help(ctx):
        return MessageFormatter.help_message(ctx.shop_name)

    @staticmethod
    def _handle_complaint(ctx):
        ctx.mem.record_complaint(ctx.db, ctx.message)
        try:
            SalesEngine.create_lead(ctx.db, ctx.shop_id, ctx.session, message=ctx.message, intent="COMPLAINT")
        except Exception:
            pass
        return MessageFormatter.complaint()

    @staticmethod
    def _handle_goodbye(ctx):
        ConversationEngine.close_session(ctx.db, ctx.session)
        return MessageFormatter.goodbye(ctx.shop_name)

    @staticmethod
    def _handle_order_status(ctx):
        """Return status — by specific 'order 20923 status' or latest order."""
        order_number = ctx.entities.get("order_number")
        q = (
            ctx.db.query(models.Order)
            .filter(models.Order.shop_id == ctx.shop_id, models.Order.phone == ctx.customer_phone)
        )
        if order_number:
            order = q.filter(
                models.Order.order_id.ilike(f"%{order_number}%")
            ).order_by(models.Order.id.desc()).first()
            if not order:
                order = q.order_by(models.Order.id.desc()).first()
        else:
            order = q.order_by(models.Order.id.desc()).first()

        if not order:
            return "I couldn't find any recent orders for you \U0001f60a Place a new order and I'll track it for you!"

        tracking_id = order.order_id or str(order.id)
        status  = (order.status or "PENDING").upper()
        emoji_map = {
            "PENDING":   "\u23f3",
            "CONFIRMED": "\u2705",
            "PREPARING": "\U0001f373",
            "READY":     "\U0001f6ce\ufe0f",
            "DELIVERED": "\U0001f3c1",
            "CANCELLED": "\u274c",
        }
        emoji = emoji_map.get(status, "\U0001f4e6")
        booking_ref = getattr(order, "booking_id", None)
        booking_str = f" (Booking: {booking_ref})" if booking_ref else ""
        return (
            f"Order *#{tracking_id}*{booking_str} \u2014 {emoji} *{status}*\n"
            f"Items: {order.product}\n"
            f"Total: *\u20b9{order.total_amount}*"
        )

    @staticmethod
    def _handle_unrelated(ctx):
        category = ctx.business_category.lower() if ctx.business_category else ""
        if "mobile" in category or "electronic" in category or "phone" in category:
            return "We mainly handle mobile phones & accessories \U0001f60a Need help choosing one?"
        if "restaurant" in category or "food" in category or "cafe" in category:
            return "We mainly serve food \U0001f60a Want to see today's menu?"
        if "salon" in category or "beauty" in category:
            return "We provide beauty & salon services \U0001f60a Need to book an appointment?"
        return f"We mainly sell items in our {ctx.business_category or 'store'} category \U0001f60a Want to see what we have?"

    @staticmethod
    def _handle_service_booking(ctx):
        service = ctx.entities.get("service", ctx.message)
        ctx.mem.session.pending_action_type = "log_missing_product"
        ctx.mem.session.pending_payload     = {"product_name": service.title(), "message": ctx.message, "category_context": ctx.business_category}
        ctx.mem.session.pending_created_at  = datetime.now(timezone.utc).isoformat()
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
        return (
            f"Would you like me to send a booking request for *{service}* to the shop owner? \U0001f4c5\n"
            f"*(yes / no)*"
        )

    @staticmethod
    def _handle_user_name_update(ctx):
        """Bug 4 fix: 'I'm Jack' stores name, returns greeting. Never triggers product search."""
        name = ctx.entities.get("customer_name", "").strip()
        if name:
            ctx.mem.session.customer_name = name
            # Also persist to long-term profile
            if ctx.mem.profile and not ctx.mem.profile.customer_name:
                ctx.mem.profile.customer_name = name
        return f"Nice to meet you, {name}! \U0001f60a What would you like to order today?"

    @staticmethod
    def _handle_stock_check(ctx):
        """Bug 3/6 fix: 'do you have curd rice?' checks stock. Never adds to cart."""
        hint = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        if not tokens:
            return "What item would you like me to check? \U0001f60a"
        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
        if products:
            p = products[0]
            stock = p.get("stock", 0)
            if stock > 0:
                detail = f"\n_({p['details'][:80]})_" if p.get("details") else ""
                return (
                    f"Yes! *{p['name']}* is available \u2705 (\u20b9{p['price']:.0f}){detail}\n\n"
                    f"Want me to add it to your cart?"
                )
            else:
                repl = RecommendationEngine.replacement_for(ctx.db, ctx.shop_id, p["name"], p.get("category"))
                msg = f"Sorry, *{p['name']}* is out of stock right now \U0001f614"
                if repl:
                    msg += f"\n\nHow about *{repl['name']}* instead? (\u20b9{repl['price']:.0f})"
                return msg
        # Not found at all
        return (
            f"Sorry, we don't have *{hint.title()}* in our menu right now \U0001f614\n"
            f"Want to see what's available?"
        )

    @staticmethod
    def _handle_cancel_existing_order(ctx):
        """Gap 3 fix: 2-step confirmation for cancelling an existing order."""
        order_number = ctx.entities.get("order_number")
        if not order_number:
            return "Which order would you like to cancel? Please include the order number."
            
        order = (
            ctx.db.query(models.Order)
            .filter(
                models.Order.shop_id == ctx.shop_id,
                models.Order.phone == ctx.customer_phone,
                models.Order.order_id.ilike(f"%{order_number}%"),
            )
            .order_by(models.Order.id.desc())
            .first()
        )
        
        if not order:
            return f"I couldn't find order *#{order_number}* for your account \U0001f614"
            
        current_status = (order.status or "").upper()
        if current_status in ("DELIVERED", "COMPLETED"):
            return f"Order *#{order_number}* has already been *{current_status}* and cannot be cancelled."
        if current_status == "CANCELLED":
            return f"Order *#{order_number}* is already cancelled."

        # Show order summary and ask for confirmation
        ctx.mem.session.pending_action_type = "cancel_order_confirm"
        ctx.mem.session.pending_payload = {"order_id": order_number, "db_id": order.id}
        ctx.mem.session.pending_created_at = datetime.now(timezone.utc).isoformat()
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
        
        return (
            f"Are you sure you want to cancel order *#{order_number}*?\n"
            f"\U0001f4e6 Items: {order.product}\n"
            f"\U0001f4b0 Total: \u20b9{order.total_amount:.0f}\n\n"
            f"Reply *yes* to confirm."
        )

    @staticmethod
    def _handle_cancel_existing_order_final(ctx):
        """Step 2: Actually execute the cancellation."""
        order_number = ctx.entities.get("order_number")
        order = (
            ctx.db.query(models.Order)
            .filter(
                models.Order.shop_id == ctx.shop_id,
                models.Order.phone == ctx.customer_phone,
                models.Order.order_id.ilike(f"%{order_number}%"),
            )
            .first()
        )
        if not order:
            return "Something went wrong. I couldn't find that order anymore."

        order.status = "CANCELLED"
        try:
            ctx.db.commit()
            log = models.OrderLog(
                shop_id=ctx.shop_id, order_id=str(order.order_id),
                action="order_cancelled_by_customer", performed_by=ctx.customer_phone, user_type="customer"
            )
            ctx.db.add(log)
            ctx.db.commit()
            
            from ..routes.sse import broadcast_event
            broadcast_event(ctx.shop_id, "order_cancelled", {"order_id": order_number})
        except Exception as exc:
            logger.error(f"[ROUTER] Order cancel DB error: {exc}")
            ctx.db.rollback()
            return "Sorry, I couldn't cancel that order right now. Please try again."

        ConversationEngine.transition(ctx.db, ctx.session, "shopping")
        return f"\u274c Order *#{order_number}* has been cancelled. Anything else I can help with?"

    @staticmethod
    def _handle_retry_order(ctx):
        """Gap 5: Retry failed order placement."""
        payload = ctx.mem.session.retry_payload
        if not payload:
            return "There's no order to retry \U0001f60a What would you like to buy?"
        
        # Restore context from payload
        ctx.entities["delivery_mode"] = payload["delivery_mode"]
        ctx.mem.session.cart = payload["cart"]
        ctx.mem.session.delivery_mode = payload["delivery_mode"]
        ctx.mem.session.delivery_address = payload["address"]
        
        return RouterEngine._handle_confirm_order(ctx)

    @staticmethod
    def _handle_ambiguous_selection(ctx):
        """Gap 6: Handle selection from clarifying options."""
        idx = ctx.entities.get("selection_index")
        options = ctx.mem.session.ambiguous_options
        
        if not options or idx > len(options):
            if idx == 3: # "Something else"
                ctx.mem.session.ambiguous_options = []
                ConversationEngine.transition(ctx.db, ctx.session, "shopping")
                return "No problem, what would you like instead? \U0001f60a"
            return "Please pick 1, 2, or 3 \U0001f60a to continue."

        product = options[idx-1]
        ctx.mem.session.ambiguous_options = []
        # Inject product as item_hint and re-run add_item
        ctx.entities["item_hint"] = product["name"]
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        return RouterEngine._handle_add_item(ctx)

    @staticmethod
    def _handle_unrecognizable(ctx):
        """Gap 8: Safe fallback for completely unrecognizable text."""
        if ctx.mem.session.cart:
            summary = OrderEngine.cart_summary(ctx.mem.session.cart)
            return (
                f"I didn't quite get that \U0001f60a You have *{summary.item_count} items* in your cart.\n"
                f"Reply *place order* to checkout, or tell me what you'd like to add!"
            )
        return (
            "I didn't quite get that \U0001f60a You can browse our *menu* or "
            "tell me what you'd like to order!"
        )

    @staticmethod
    def _handle_reject_upsell(ctx):
        """Bug 1/3 fix: 'no thanks' during upsell keeps cart unchanged."""
        # Just acknowledge and stay in cart_active
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        summary = OrderEngine.cart_summary(ctx.mem.session.cart)
        if summary.is_empty:
            return "No problem! What would you like to order? \U0001f60a"
        return (
            f"No problem! \U0001f60a Your cart total is *\u20b9{summary.total:.0f}*.\n"
            f"Reply *place order* when you're ready, or keep adding items!"
        )

    @staticmethod
    def _handle_unclear_in_confirmation(ctx):
        return "Please reply *yes* to confirm, or *no* to cancel \U0001f60a"

    @staticmethod
    def _handle_unknown(ctx):
        hint   = ctx.message
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        if tokens and len(hint) >= 3:
            products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
            if products:
                p = products[0]
                return (f"I think you're looking for *{p['name']}* (\u20b9{p['price']:.0f}) \U0001f60a "
                        f"Is that right? I can add it to your cart!")
            # Domain-relevant unknown item \u2192 offer to log as pending request
            ctx.mem.session.pending_action_type = "log_missing_product"
            ctx.mem.session.pending_payload     = {"product_name": hint.title(), "message": hint, "category_context": ctx.business_category}
            ctx.mem.session.pending_created_at  = datetime.now(timezone.utc).isoformat()
            ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
            return (
                f"We don't have *{hint.title()}* right now. \U0001f614\n"
                f"Shall I send your request to the shop owner? *(yes / no)*"
            )
        return MessageFormatter.unclear()



# ─── Context ──────────────────────────────────────────────────────────────────

class _Context:
    __slots__ = (
        "db", "shop_id", "shop_name", "shop_settings", "business_category", 
        "shop_category", "business_subnote",
        "customer_phone", "message", "session", "mem",
        "state", "entities", "intent",
    )

    def __init__(self, db, shop_id, shop_name, shop_settings, business_category, 
                 shop_category, business_subnote,
                 customer_phone, message, session, mem, state, entities, intent):
        self.db             = db
        self.shop_id        = shop_id
        self.shop_name      = shop_name
        self.shop_settings  = shop_settings
        self.business_category = business_category
        self.shop_category  = shop_category
        self.business_subnote  = business_subnote
        self.customer_phone = customer_phone
        self.message        = message
        self.session        = session
        self.mem            = mem
        self.state          = state
        self.entities       = entities
        self.intent         = intent
