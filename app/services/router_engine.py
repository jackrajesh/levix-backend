# -*- coding: utf-8 -*-
"""
router_engine.py — LEVIX Central Message Router (v3)
All 10 production fixes applied.
"""

from __future__ import annotations
import logging
import random
import re
import traceback
from datetime import datetime, timezone
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


# ═══════════════════════════════════════════════════════════════════════════════
class RouterEngine:

    @classmethod
    def process_message(cls, db: Session, shop_id: int, customer_phone: str, raw_message: str) -> str:
        try:
            vr = ValidationEngine.message(raw_message)
            if not vr:
                return MessageFormatter.unclear()

            message = _normalise(vr.cleaned)
            session   = ConversationEngine.get_session(db, shop_id, customer_phone)
            shop      = db.query(models.Shop).get(shop_id)
            shop_name = shop.shop_name if shop else "our shop"
            shop_settings = (shop.settings or {}) if shop else {}
            business_category = shop.business_category or ""
            business_subnote = shop.business_subnote or ""

            mem   = MemoryEngine.load(db, session, customer_phone)
            state = session.category or "idle"

            ie         = IntentEngine()
            intent_obj = ie.classify(message, session_state=state, business_category=business_category)
            intent     = intent_obj.name
            entities   = intent_obj.entities
            score      = intent_obj.understanding_score

            logger.info(f"[ROUTER] phone={customer_phone} state={state} intent={intent} score={score}")

            ctx = _Context(
                db=db, shop_id=shop_id, shop_name=shop_name,
                shop_settings=shop_settings, business_category=business_category, business_subnote=business_subnote,
                customer_phone=customer_phone, message=message, session=session, mem=mem,
                state=state, entities=entities, intent=intent,
            )

            reply = cls._route(ctx, score)

            ConversationEngine.set_last_intent(db, session, intent, intent_obj.confidence)
            ConversationEngine.append_history(session, "user", raw_message)
            ConversationEngine.append_history(session, "assistant", reply)
            MemoryEngine.flush(db, session, mem)
            ConversationEngine.flush(db, session)

            return reply

        except Exception as exc:
            logger.error(f"[ROUTER] CRASH: {exc}\n{traceback.format_exc()}")
            try:
                db.rollback()
            except Exception:
                pass
            return MessageFormatter.system_error()

    @classmethod
    def _route(cls, ctx: "_Context", score: int) -> str:
        if score < 20 and ctx.intent not in ("greet", "confirm_order", "cancel_order", "order_status", "pending_yes", "pending_no"):
            return MessageFormatter.unclear()

        handler_map = {
            "greet":                  cls._handle_greet,
            "checkout_start":         cls._handle_checkout_start,
            "pending_yes":            cls._handle_pending_yes,
            "pending_no":             cls._handle_pending_no,
            "pending_unclear":        cls._handle_unclear_in_confirmation,
            "add_item":               cls._handle_add_item,
            "multi_add_items":        cls._handle_multi_add,
            "remove_item":            cls._handle_remove_item,
            "change_quantity":        cls._handle_change_quantity,
            "set_preference":         cls._handle_set_preference,
            "show_cart":              cls._handle_show_cart,
            "view_cart":              cls._handle_show_cart,
            "clear_cart":             cls._handle_clear_cart,
            "clear_cart_confirmed":   cls._handle_clear_cart_confirmed,
            "select_delivery":        cls._handle_select_delivery,
            "select_pickup":          cls._handle_select_pickup,
            "provide_address":        cls._handle_provide_address,
            "change_address":         cls._handle_change_address,
            "confirm_order":          cls._handle_confirm_order,
            "cancel_order":           cls._handle_cancel_order,
            "yes_with_modification":  cls._handle_yes_with_modification,
            "edit_cart":              cls._handle_edit_cart,
            "repeat_last_order":      cls._handle_repeat_last_order,
            "budget_request":         cls._handle_budget_request,
            "group_meal_request":     cls._handle_group_meal_request,
            "vague_request":          cls._handle_vague_request,
            "ask_recommendation":     cls._handle_recommendation,
            "view_menu":              cls._handle_view_menu,
            "ask_price":              cls._handle_ask_price,
            "ask_help":               cls._handle_help,
            "complaint":              cls._handle_complaint,
            "goodbye":                cls._handle_goodbye,
            "order_status":           cls._handle_order_status,
            "unrelated_item":         cls._handle_unrelated,
            "service_booking":        cls._handle_service_booking,
            "unclear_in_confirmation": cls._handle_unclear_in_confirmation,
        }
        handler = handler_map.get(ctx.intent, cls._handle_unknown)
        return handler(ctx)

    # ── Handlers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _handle_greet(ctx):
        ConversationEngine.transition(ctx.db, ctx.session, "shopping")
        # Clear stale pending actions on greeting
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload = None
        wb = ctx.mem.welcome_back_message()
        if wb:
            return wb
        return MessageFormatter.greet(ctx.shop_name)

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
            try:
                req = models.PendingRequest(
                    shop_id=ctx.shop_id,
                    product_name=product_name,
                    customer_message=payload.get("message", ""),
                    request_type="customer",
                    category_context=category_context,
                )
                ctx.db.add(req)
                ctx.db.commit()
                try:
                    from ..routes.sse import broadcast_event
                    broadcast_event(ctx.shop_id, "new_pending_request", {"product": product_name})
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"[ROUTER] Pending request save failed: {e}")
                ctx.db.rollback()
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")
            return (
                f"\u2705 Got it! Your request for *{product_name}* has been sent to the owner.\n"
                f"They'll look into it. Anything else?"
            )

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
        ConversationEngine.transition(ctx.db, ctx.session, "shopping")
        if action == "log_missing_product":
            return "No problem! Let me know what else you'd like \U0001f60a"
        if action == "clear_cart_confirm":
            return "Cart kept! Anything else? \U0001f60a"
        return "Okay! What else can I help with? \U0001f60a"



    @staticmethod
    def _handle_add_item(ctx):
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        qty    = ctx.entities.get("quantity", 1)
        spice  = ctx.entities.get("spice_level")

        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
        if not products:
            # Domain-relevant missing product \u2192 offer to log as pending request (Yes/No gate)
            ctx.mem.session.pending_action_type = "log_missing_product"
            ctx.mem.session.pending_payload     = {"product_name": hint.title(), "message": ctx.message, "category_context": ctx.business_category}
            ctx.mem.session.pending_created_at  = datetime.now(timezone.utc).isoformat()
            ConversationEngine.transition(ctx.db, ctx.session, "awaiting_yes_no")
            return (
                f"We don't have *{hint.title()}* right now. \U0001f614\n"
                f"Shall I send your request to the shop owner? *(yes / no)*"
            )

        product = products[0]
        if product.get("stock", product.get("max_qty_per_order", 1)) <= 0:
            repl = RecommendationEngine.replacement_for(ctx.db, ctx.shop_id, product["name"], product.get("category"))
            if repl:
                return MessageFormatter.item_out_of_stock(item=product["name"]) + f"\n\nHow about *{repl['name']}* instead? (\u20b9{repl['price']:.0f})"
            return MessageFormatter.item_out_of_stock(item=product["name"])

        # Clear stale pending action since user is adding items
        ctx.mem.session.pending_action_type = None
        ctx.mem.session.pending_payload = None

        # Build detail snippet from product_details (Phase 9 Lock)
        detail_note = ""
        if product.get("details") and not ctx.mem.session.cart:
            detail_note = f"\n_({product['details'][:80]})_"

        cart = ctx.mem.session.cart
        cart, result = OrderEngine.cart_add(cart, product, qty, spice)
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        summary = OrderEngine.cart_summary(cart)
        upsell  = None
        if summary.total < 600:
            ui = RecommendationEngine.upsell_for(ctx.db, ctx.shop_id, cart, budget_left=200)
            if ui:
                upsell = ui["name"]

        reply = MessageFormatter.item_added(
            qty=result.get("qty", result.get("new_qty", qty)),
            item=product["name"],
            unit_price=product["price"],
            total=summary.total,
            upsell=upsell,
        )
        return reply + detail_note

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
            products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
            if not products:
                OrderEngine.log_missing_product(ctx.db, ctx.shop_id, ctx.customer_phone, entry["hint"])
                missing.append(entry["hint"])
            else:
                product = products[0]
                cart, result = OrderEngine.cart_add(cart, product, qty)
                added.append(f"{qty}x {product['name']}")

        ctx.mem.session.cart = cart
        if added:
            ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        summary = OrderEngine.cart_summary(cart)

        lines = "\n".join(f"\u2705 {a}" for a in added)
        reply = f"Added to cart:\n{lines}\n\n*Cart total: \u20b9{summary.total:.0f}*"
        if missing:
            reply += f"\n\n_Could not find: {', '.join(missing)}_"
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
            return MessageFormatter.unclear()
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
        # Phase 3 YES/NO control logic: if yes but no pending state and cart empty
        if not ctx.mem.session.cart and ctx.session.category not in ("awaiting_confirmation", "awaiting_clear_confirm", "awaiting_yes_no"):
            return "I'm here \U0001f60a What would you like to order?"

        # Idempotency
        vr = ValidationEngine.not_duplicate_order(ctx.mem.session.last_order_time)
        if not vr:
            return MessageFormatter.already_confirmed()

        cart          = ctx.mem.session.cart
        delivery_mode = ctx.mem.session.delivery_mode or "pickup"
        address       = ctx.mem.session.delivery_address or ""
        summary       = OrderEngine.cart_summary(cart)
        fee           = OrderEngine.delivery_fee(summary.total, ctx.shop_settings) if delivery_mode == "delivery" else 0
        total         = round(summary.total + fee, 2)

        vr2 = ValidationEngine.checkout_ready(cart, delivery_mode, address, total)
        if not vr2:
            return f"Almost there! {vr2.reason} \U0001f60a"

        try:
            order_number = _gen_order_number() # 5 digit
            booking_ref = str(random.randint(1000000000, 9999999999)) # 10 digit
            order = models.Order(
                shop_id       = ctx.shop_id,
                booking_id    = booking_ref,
                order_id      = order_number, # Order ID is 5 digit, idempotency key might be needed elsewhere but let's use order_number here
                customer_name = ctx.mem.session.customer_name or ctx.customer_phone,
                phone         = ctx.customer_phone,
                address       = address if delivery_mode == "delivery" else "PICKUP",
                product       = "; ".join(f"{i['qty']}x {i['name']}" for i in summary.items),
                quantity      = sum(i["qty"] for i in summary.items),
                unit_price    = summary.total,
                total_amount  = total,
                status        = "PENDING",
            )
            ctx.db.add(order)
            ctx.db.commit()
            ctx.db.refresh(order)

            ctx.mem.record_order(ctx.db, summary.items, total)
            ctx.mem.note_order_completed(order.id)
            
            # Phase 2: Clear cart after order success
            ctx.mem.session.cart = []
            ctx.mem.session.pending_action_type = None
            ctx.mem.session.pending_payload = None

            try:
                SalesEngine.create_lead(ctx.db, ctx.shop_id, ctx.session, message=str(summary.items), intent="ORDER")
            except Exception as e:
                logger.warning(f"[ROUTER] Lead skipped: {e}")

            ConversationEngine.transition(ctx.db, ctx.session, "completed")

            reply_lines = [
                f"\U0001f389 Order *#{order_number}* confirmed!",
                f"Status: *PENDING*"
            ]
            if delivery_mode == "delivery":
                reply_lines.append(f"\U0001f4cd Delivering to: _{address}_")
            else:
                reply_lines.append(f"\U0001f3ea Pickup from store")
            reply_lines.append(f"Total: *\u20b9{total:.0f}*")
            reply_lines.append("\nWe'll notify you when it's on the way!" if delivery_mode == "delivery" else "\nSee you soon!")

            return "\n".join(reply_lines)

        except Exception as exc:
            logger.error(f"[ROUTER] DB write failed: {exc}")
            ctx.db.rollback()
            return "Sorry, we couldn't save your order right now \U0001f64f Please try again."

    @staticmethod
    def _handle_cancel_order(ctx):
        if not ctx.mem.session.cart and ctx.session.category not in ("awaiting_confirmation", "awaiting_clear_confirm", "awaiting_yes_no"):
            return "I'm here \U0001f60a What would you like to order?"

        ctx.mem.session.cart = []
        ctx.mem.session.delivery_mode    = None
        ctx.mem.session.delivery_address = None
        ConversationEngine.transition(ctx.db, ctx.session, "cancelled")
        return MessageFormatter.order_cancelled()

    @staticmethod
    def _handle_yes_with_modification(ctx):
        """User said "yes add coke too" — treat as cart modification, not confirm."""
        extra = ctx.entities.get("modification_text", "")
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        # Re-route the extra part as add_item
        sub_ctx = _Context(
            db=ctx.db, shop_id=ctx.shop_id, shop_name=ctx.shop_name,
            shop_settings=ctx.shop_settings, customer_phone=ctx.customer_phone,
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
        return MessageFormatter.menu(items)

    @staticmethod
    def _handle_ask_price(ctx):
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        if not tokens:
            return "Which item would you like the price for? \U0001f60a"
        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
        if not products:
            return MessageFormatter.item_not_found(hint=hint)
        p      = products[0]
        detail = f"\n_({p['details'][:80]})_" if p.get("details") else ""
        return f"*{p['name']}* is \u20b9{p['price']:.0f} \U0001f60a{detail}\n\nWant to add it to your cart?"

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
        return (
            f"Order *#{tracking_id}* \u2014 {emoji} *{status}*\n"
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
        "db", "shop_id", "shop_name", "shop_settings", "business_category", "business_subnote",
        "customer_phone", "message", "session", "mem",
        "state", "entities", "intent",
    )

    def __init__(self, db, shop_id, shop_name, shop_settings, business_category, business_subnote,
                 customer_phone, message, session, mem, state, entities, intent):
        self.db             = db
        self.shop_id        = shop_id
        self.shop_name      = shop_name
        self.shop_settings  = shop_settings
        self.business_category = business_category
        self.business_subnote  = business_subnote
        self.customer_phone = customer_phone
        self.message        = message
        self.session        = session
        self.mem            = mem
        self.state          = state
        self.entities       = entities
        self.intent         = intent
