"""
router_engine.py — LEVIX Central Message Router  (Production v2)
=================================================================
The single entry point for processing every incoming WhatsApp message.

Architecture:
  RouterEngine.process_message(db, shop_id, customer_phone, message)
      ↓
  1. Load session + memory
  2. Validate input
  3. Classify intent (IntentEngine)
  4. Route intent → handler
  5. Flush state to DB
  6. Return reply string

Handler map:
  greet                   → _handle_greet
  add_item                → _handle_add_item
  remove_item             → _handle_remove_item
  change_quantity         → _handle_change_quantity
  set_preference          → _handle_set_preference
  show_cart               → _handle_show_cart
  select_delivery         → _handle_select_delivery
  select_pickup           → _handle_select_pickup
  provide_address         → _handle_provide_address
  confirm_order           → _handle_confirm_order
  cancel_order            → _handle_cancel_order
  edit_cart               → _handle_edit_cart
  repeat_last_order       → _handle_repeat_last_order
  budget_request          → _handle_budget_request
  group_meal_request      → _handle_group_meal_request
  vague_request           → _handle_vague_request
  ask_recommendation      → _handle_recommendation
  view_menu               → _handle_view_menu
  ask_price               → _handle_ask_price
  ask_help                → _handle_help
  complaint               → _handle_complaint
  goodbye                 → _handle_goodbye
  change_address          → _handle_change_address
  unclear_in_confirmation → _handle_unclear_in_confirmation
  unknown                 → _handle_unknown
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from .conversation_engine import ConversationEngine
from .intent_engine import IntentEngine
from .memory_engine import MemoryEngine
from .order_engine import OrderEngine
from .recommendation_engine import RecommendationEngine
from .sales_engine import SalesEngine
from .validation_engine import ValidationEngine
from .message_formatter import MessageFormatter
from .. import models

logger = logging.getLogger("levix.router")


# ─── Aliases normalisation map ────────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    "coca cola": "coke",
    "coca-cola": "coke",
    "pepsi cola": "pepsi",
    "add it":        "repeat_context",
    "same one":      "repeat_context",
    "repeat last combo": "repeat_context",
}


def _normalise(text: str) -> str:
    low = text.lower()
    for src, tgt in _ALIASES.items():
        low = low.replace(src, tgt)
    return low


# ═══════════════════════════════════════════════════════════════════════════════
# RouterEngine
# ═══════════════════════════════════════════════════════════════════════════════

class RouterEngine:
    """
    Central message router.  One public method: `process_message`.
    """

    @classmethod
    def process_message(
        cls,
        db:             Session,
        shop_id:        int,
        customer_phone: str,
        raw_message:    str,
    ) -> str:
        """
        Process one incoming WhatsApp message and return the reply string.

        Never raises — all exceptions are caught and a graceful error message
        is returned.
        """
        try:
            # ── 1. Validate raw input ────────────────────────────────────────
            vr = ValidationEngine.message(raw_message)
            if not vr:
                return MessageFormatter.unclear()

            message = _normalise(vr.cleaned)

            # ── 2. Load session + memory ─────────────────────────────────────
            session  = ConversationEngine.get_session(db, shop_id, customer_phone)
            shop     = db.query(models.Shop).get(shop_id)
            shop_name = (shop.shop_name if shop else "our shop")
            shop_settings = (shop.settings or {}) if shop else {}

            mem = MemoryEngine.load(db, session, customer_phone)
            state = session.category or "idle"

            # ── 3. Classify intent ───────────────────────────────────────────
            ie = IntentEngine()
            intent_obj = ie.classify(message, session_state=state)
            intent     = intent_obj.name
            entities   = intent_obj.entities
            score      = intent_obj.understanding_score

            logger.info(
                f"[ROUTER] phone={customer_phone} state={state} "
                f"intent={intent} score={score} conf={intent_obj.confidence:.2f}"
            )

            # ── 4. Route to handler ──────────────────────────────────────────
            ctx = _Context(
                db=db,
                shop_id=shop_id,
                shop_name=shop_name,
                shop_settings=shop_settings,
                customer_phone=customer_phone,
                message=message,
                session=session,
                mem=mem,
                state=state,
                entities=entities,
                intent=intent,
            )

            reply = cls._route(ctx, score)

            # ── 5. Flush state to DB ─────────────────────────────────────────
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

    # ── Intent router ─────────────────────────────────────────────────────────

    @classmethod
    def _route(cls, ctx: "_Context", score: int) -> str:
        """Dispatch to the correct handler based on intent name."""

        # Low understanding score — ask for clarification first
        if score < 20 and ctx.intent not in ("greet", "confirm_order", "cancel_order"):
            return MessageFormatter.unclear()

        handler_map = {
            "greet":                    cls._handle_greet,
            "add_item":                 cls._handle_add_item,
            "remove_item":              cls._handle_remove_item,
            "change_quantity":          cls._handle_change_quantity,
            "set_preference":           cls._handle_set_preference,
            "show_cart":                cls._handle_show_cart,
            "view_cart":                cls._handle_show_cart,
            "select_delivery":          cls._handle_select_delivery,
            "select_pickup":            cls._handle_select_pickup,
            "provide_address":          cls._handle_provide_address,
            "change_address":           cls._handle_change_address,
            "confirm_order":            cls._handle_confirm_order,
            "cancel_order":             cls._handle_cancel_order,
            "edit_cart":                cls._handle_edit_cart,
            "repeat_last_order":        cls._handle_repeat_last_order,
            "budget_request":           cls._handle_budget_request,
            "group_meal_request":       cls._handle_group_meal_request,
            "vague_request":            cls._handle_vague_request,
            "ask_recommendation":       cls._handle_recommendation,
            "view_menu":                cls._handle_view_menu,
            "ask_price":                cls._handle_ask_price,
            "ask_help":                 cls._handle_help,
            "complaint":                cls._handle_complaint,
            "goodbye":                  cls._handle_goodbye,
            "unclear_in_confirmation":  cls._handle_unclear_in_confirmation,
        }

        handler = handler_map.get(ctx.intent, cls._handle_unknown)
        return handler(ctx)

    # ── Handlers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _handle_greet(ctx: "_Context") -> str:
        ConversationEngine.transition(ctx.db, ctx.session, "shopping")

        # Returning customer personalisation
        wb = ctx.mem.welcome_back_message()
        if wb:
            return wb

        return MessageFormatter.greet(ctx.shop_name)

    @staticmethod
    def _handle_add_item(ctx: "_Context") -> str:
        hint = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        qty   = ctx.entities.get("quantity", 1)
        spice = ctx.entities.get("spice_level")

        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
        if not products:
            # Log the miss and forward to owner
            OrderEngine.log_missing_product(ctx.db, ctx.shop_id, ctx.customer_phone, hint)
            return MessageFormatter.missing_product_noted(hint=hint)

        product = products[0]

        # OOS guard (quantity field holds stock)
        if product.get("max_qty_per_order", 0) <= 0:
            replacement = RecommendationEngine.replacement_for(
                ctx.db, ctx.shop_id, product["name"], product.get("category")
            )
            if replacement:
                return (
                    MessageFormatter.item_out_of_stock(item=product["name"])
                    + f"\n\nHow about *{replacement['name']}* instead? (₹{replacement['price']:.0f})"
                )
            return MessageFormatter.item_out_of_stock(item=product["name"])

        cart = ctx.mem.session.cart
        cart, result = OrderEngine.cart_add(cart, product, qty, spice)
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        summary = OrderEngine.cart_summary(cart)

        # Upsell?
        upsell = None
        if summary.total < 600:
            upsell_item = RecommendationEngine.upsell_for(
                ctx.db, ctx.shop_id, cart, budget_left=300
            )
            if upsell_item:
                upsell = upsell_item["name"]

        return MessageFormatter.item_added(
            qty=result.get("qty", result.get("new_qty", qty)),
            item=product["name"],
            unit_price=product["price"],
            total=summary.total,
            upsell=upsell,
        )

    @staticmethod
    def _handle_remove_item(ctx: "_Context") -> str:
        hint = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)

        cart = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()

        cart, result = OrderEngine.cart_remove(cart, tokens)
        ctx.mem.session.cart = cart

        if result["action"] == "not_found":
            return f"I couldn't find that in your cart 😊 {MessageFormatter.cart_summary(OrderEngine.cart_summary(cart).items, OrderEngine.cart_summary(cart).total)}"

        if not cart:
            ConversationEngine.transition(ctx.db, ctx.session, "shopping")

        return MessageFormatter.item_removed(item=result["item"], total=result.get("new_total", 0))

    @staticmethod
    def _handle_change_quantity(ctx: "_Context") -> str:
        qty  = ctx.entities.get("quantity", 1)
        hint = ctx.entities.get("item_hint", "")
        tokens = IntentEngine.extract_item_hint_tokens(hint) if hint else []

        cart = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()

        cart, result = OrderEngine.cart_change_quantity(cart, tokens, qty)
        ctx.mem.session.cart = cart

        if result["action"] == "cart_empty":
            return MessageFormatter.empty_cart()
        if result["action"] == "not_found":
            return MessageFormatter.unclear()

        return MessageFormatter.quantity_updated(
            item=result["item"],
            new_qty=result["new_qty"],
            subtotal=result["subtotal"],
        )

    @staticmethod
    def _handle_set_preference(ctx: "_Context") -> str:
        spice = ctx.entities.get("spice_level")
        veg   = ctx.entities.get("veg_preference")

        if spice:
            cart = ctx.mem.session.cart
            if cart:
                cart, result = OrderEngine.cart_apply_spice(cart, spice)
                ctx.mem.session.cart = cart
                if result["action"] == "spice_set":
                    return MessageFormatter.spice_noted(item=result["item"], modifier=spice)
            # No cart yet — save as session preference
            ctx.mem.note_preference(spice_level=spice)
            return f"Got it! I'll remember you prefer *{spice}* 🌶️"

        if veg:
            ctx.mem.note_preference(veg_preference=veg)
            pref_str = "veg" if veg == "veg" else "non-veg"
            return f"Noted! I'll filter to *{pref_str}* options for you 😊"

        return MessageFormatter.unclear()

    @staticmethod
    def _handle_show_cart(ctx: "_Context") -> str:
        cart = ctx.mem.session.cart
        summary = OrderEngine.cart_summary(cart)
        if summary.is_empty:
            return MessageFormatter.empty_cart()
        return MessageFormatter.cart_summary(summary.items, summary.total)

    @staticmethod
    def _handle_select_delivery(ctx: "_Context") -> str:
        cart = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()
        ctx.mem.session.delivery_mode = "delivery"
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_address")
        return MessageFormatter.delivery_prompt()

    @staticmethod
    def _handle_select_pickup(ctx: "_Context") -> str:
        cart = ctx.mem.session.cart
        if not cart:
            return MessageFormatter.empty_cart()
        ctx.mem.session.delivery_mode = "pickup"
        summary = OrderEngine.cart_summary(cart)
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_confirmation")
        return MessageFormatter.pickup_confirmation(summary.items, summary.total)

    @staticmethod
    def _handle_provide_address(ctx: "_Context") -> str:
        addr = ctx.entities.get("address_text", ctx.message).strip()

        vr = ValidationEngine.address(addr)
        if not vr:
            return MessageFormatter.address_clarify()

        ctx.mem.session.delivery_address = vr.cleaned
        cart = ctx.mem.session.cart
        summary = OrderEngine.cart_summary(cart)

        # Add delivery fee
        fee = OrderEngine.delivery_fee(summary.total, ctx.shop_settings)
        total_with_fee = round(summary.total + fee, 2)

        # Update total display with fee note
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_confirmation")

        reply = MessageFormatter.address_received(
            address=vr.cleaned,
            items=summary.items,
            total=total_with_fee,
        )
        if fee > 0:
            reply += f"\n_(includes ₹{fee:.0f} delivery charge)_"

        return reply

    @staticmethod
    def _handle_change_address(ctx: "_Context") -> str:
        ctx.mem.session.delivery_address = None
        ConversationEngine.transition(ctx.db, ctx.session, "awaiting_address")
        return MessageFormatter.delivery_prompt()

    @staticmethod
    def _handle_confirm_order(ctx: "_Context") -> str:
        """Write the order to DB. Full validation pipeline first."""

        # Idempotency: block re-confirmation within window
        vr_idem = ValidationEngine.not_duplicate_order(
            ctx.mem.session.last_order_time
        )
        if not vr_idem:
            logger.warning(f"[ROUTER] Duplicate order blocked: {ctx.customer_phone}")
            return MessageFormatter.already_confirmed()

        cart          = ctx.mem.session.cart
        delivery_mode = ctx.mem.session.delivery_mode or "pickup"
        address       = ctx.mem.session.delivery_address or ""

        # Compute total (with delivery fee)
        summary = OrderEngine.cart_summary(cart)
        fee     = OrderEngine.delivery_fee(summary.total, ctx.shop_settings) if delivery_mode == "delivery" else 0
        total   = round(summary.total + fee, 2)

        # Checkout readiness
        vr = ValidationEngine.checkout_ready(cart, delivery_mode, address, total)
        if not vr:
            logger.warning(f"[ROUTER] Checkout validation failed: {vr.reason}")
            return f"Almost there! {vr.reason} 😊"

        # Write Order to DB
        try:
            order = models.Order(
                shop_id          = ctx.shop_id,
                booking_id       = f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}{ctx.customer_phone[-4:]}",
                order_id         = OrderEngine.build_idempotency_key(
                    ctx.customer_phone, cart,
                    datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                )[:40],
                customer_name    = ctx.mem.session.customer_name or ctx.customer_phone,
                phone            = ctx.customer_phone,
                address          = address if delivery_mode == "delivery" else "PICKUP",
                product          = "; ".join(f"{i['qty']}x {i['name']}" for i in summary.items),
                quantity         = sum(i["qty"] for i in summary.items),
                unit_price       = summary.total,
                total_amount     = total,
                status           = "pending",
            )
            ctx.db.add(order)
            ctx.db.commit()
            ctx.db.refresh(order)

            # Record in long-term memory
            ctx.mem.record_order(ctx.db, summary.items, total)
            ctx.mem.note_order_completed(order.id)

            # Create lead in inbox (non-fatal)
            try:
                SalesEngine.create_lead(
                    ctx.db, ctx.shop_id, ctx.session,
                    message=str(summary.items),
                    intent="ORDER",
                    matched_product=None,
                )
            except Exception as lead_err:
                logger.warning(f"[ROUTER] Lead creation skipped: {lead_err}")

            ConversationEngine.transition(ctx.db, ctx.session, "completed")

            return MessageFormatter.order_confirmed(
                delivery_mode=delivery_mode,
                address=address,
                total=total,
            )

        except Exception as exc:
            logger.error(f"[ROUTER] DB write failed: {exc}\n")
            ctx.db.rollback()
            return "Sorry, we couldn't save your order right now 🙏 Please try again in a moment."

    @staticmethod
    def _handle_cancel_order(ctx: "_Context") -> str:
        ctx.mem.session.cart = []
        ctx.mem.session.delivery_mode = None
        ctx.mem.session.delivery_address = None
        ConversationEngine.transition(ctx.db, ctx.session, "cancelled")
        return MessageFormatter.order_cancelled()

    @staticmethod
    def _handle_edit_cart(ctx: "_Context") -> str:
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")
        return MessageFormatter.cart_edit_prompt()

    @staticmethod
    def _handle_repeat_last_order(ctx: "_Context") -> str:
        summary = ctx.mem.last_order_summary
        if not summary:
            return MessageFormatter.no_previous_order()
        return MessageFormatter.repeat_order_prompt(summary=summary)

    @staticmethod
    def _handle_budget_request(ctx: "_Context") -> str:
        budget     = ctx.entities.get("budget", ctx.mem.estimated_budget)
        people     = ctx.entities.get("group_size", 1)
        spice      = ctx.entities.get("spice_level")
        veg        = ctx.entities.get("veg_preference")

        if not budget:
            return "What's your budget? I'll build the perfect combo 😊"

        ctx.mem.note_preference(
            budget=float(budget),
            group_size=int(people) if people else None,
            spice_level=spice,
            veg_preference=veg,
        )

        result = RecommendationEngine.combo_under_budget(
            ctx.db, ctx.shop_id, float(budget),
            people=int(people),
            veg_only=(veg == "veg"),
        )

        if result.is_empty:
            return f"Hmm, I couldn't find a combo under ₹{budget:.0f} right now 😔 Want me to suggest our popular items instead?"

        # Add items to cart automatically
        cart = ctx.mem.session.cart
        for item in result.items:
            cart, _ = OrderEngine.cart_add(cart, item, item.get("qty", 1), spice)
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        return MessageFormatter.recommendation_budget(
            budget=float(budget),
            items=result.items,
            total=result.total,
        )

    @staticmethod
    def _handle_group_meal_request(ctx: "_Context") -> str:
        people = ctx.entities.get("group_size", 2)
        budget = ctx.entities.get("budget", ctx.mem.estimated_budget)

        if not budget:
            ctx.mem.note_preference(group_size=int(people))
            return f"Sure! For {people} people — what's your budget? 😊"

        result = RecommendationEngine.group_meal(
            ctx.db, ctx.shop_id, people=int(people), budget=float(budget)
        )
        if result.is_empty:
            return f"Hmm, I couldn't find a group meal for {people} under ₹{budget:.0f} right now 😔"

        # Auto-add to cart
        cart = ctx.mem.session.cart
        for item in result.items:
            cart, _ = OrderEngine.cart_add(cart, item, item.get("qty", 1))
        ctx.mem.session.cart = cart
        ConversationEngine.transition(ctx.db, ctx.session, "cart_active")

        return MessageFormatter.recommendation_budget(
            budget=float(budget), items=result.items, total=result.total
        )

    @staticmethod
    def _handle_vague_request(ctx: "_Context") -> str:
        """
        Customer said something vague like 'hungry' or 'something nice'.
        Ask a single smart clarifying question.
        """
        state = ctx.state
        mem   = ctx.mem

        if not mem.session.budget and not mem.estimated_budget:
            return "What's your budget? I'll suggest the best option! 😊"
        if not mem.session.group_size:
            return "How many people are we ordering for? 😊"

        # Have enough context — fall through to recommendation
        budget = mem.estimated_budget or 500
        result = RecommendationEngine.popular_items(ctx.db, ctx.shop_id, limit=4)
        if result.is_empty:
            return "What are you in the mood for? Tell me what you'd like 😊"

        return MessageFormatter.recommendation_general(result.items)

    @staticmethod
    def _handle_recommendation(ctx: "_Context") -> str:
        result = RecommendationEngine.popular_items(ctx.db, ctx.shop_id, limit=4)
        if result.is_empty:
            return "Let me know what you'd like — I'll find it for you 😊"
        return MessageFormatter.recommendation_general(result.items)

    @staticmethod
    def _handle_view_menu(ctx: "_Context") -> str:
        items = RecommendationEngine.menu_items(ctx.db, ctx.shop_id, limit=8)
        return MessageFormatter.menu(items)

    @staticmethod
    def _handle_ask_price(ctx: "_Context") -> str:
        hint   = ctx.entities.get("item_hint", ctx.message)
        tokens = IntentEngine.extract_item_hint_tokens(hint)

        if not tokens:
            return "Which item would you like the price for? 😊"

        products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
        if not products:
            return MessageFormatter.item_not_found(hint=hint)

        p = products[0]
        return f"*{p['name']}* is ₹{p['price']:.0f} 😊 Want to add it to your cart?"

    @staticmethod
    def _handle_help(ctx: "_Context") -> str:
        return MessageFormatter.help_message(ctx.shop_name)

    @staticmethod
    def _handle_complaint(ctx: "_Context") -> str:
        ctx.mem.record_complaint(ctx.db, ctx.message)
        SalesEngine.create_lead(
            ctx.db, ctx.shop_id, ctx.session,
            message=ctx.message,
            intent="COMPLAINT",
        )
        return MessageFormatter.complaint()

    @staticmethod
    def _handle_goodbye(ctx: "_Context") -> str:
        ConversationEngine.close_session(ctx.db, ctx.session)
        return MessageFormatter.goodbye(ctx.shop_name)

    @staticmethod
    def _handle_unclear_in_confirmation(ctx: "_Context") -> str:
        return "Please reply *yes* to confirm your order, or *no* to cancel 😊"

    @staticmethod
    def _handle_unknown(ctx: "_Context") -> str:
        # Last resort: try treating it as an add_item with low confidence
        hint = ctx.message
        tokens = IntentEngine.extract_item_hint_tokens(hint)
        if tokens and len(hint) >= 3:
            products = OrderEngine.find_products(ctx.db, ctx.shop_id, tokens, limit=1)
            if products:
                p = products[0]
                return (
                    f"I think you're looking for *{p['name']}* (₹{p['price']:.0f}) 😊 "
                    f"Is that right? I can add it to your cart!"
                )
        return MessageFormatter.unclear()


# ─── Internal context object ──────────────────────────────────────────────────

class _Context:
    """
    Immutable-ish bag of everything a handler needs.
    Avoids long parameter lists.
    """
    __slots__ = (
        "db", "shop_id", "shop_name", "shop_settings",
        "customer_phone", "message", "session", "mem",
        "state", "entities", "intent",
    )

    def __init__(
        self,
        db:             Session,
        shop_id:        int,
        shop_name:      str,
        shop_settings:  dict,
        customer_phone: str,
        message:        str,
        session:        models.AIConversationSession,
        mem:            MemoryEngine,
        state:          str,
        entities:       dict,
        intent:         str,
    ):
        self.db             = db
        self.shop_id        = shop_id
        self.shop_name      = shop_name
        self.shop_settings  = shop_settings
        self.customer_phone = customer_phone
        self.message        = message
        self.session        = session
        self.mem            = mem
        self.state          = state
        self.entities       = entities
        self.intent         = intent
