"""
router.py — LEVIX WhatsApp Bot Core Router
Orchestrates intent classification, session memory, cart operations,
and generates human-like chat replies.

Entry point:
    router = LEVIXRouter(database_url="postgresql+psycopg2://...")
    reply = router.handle(phone="+919876543210", message="add 2 biryani")
"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from intent_engine import IntentEngine
from memory_engine import MemoryEngine, init_db
from order_engine import OrderEngine, init_order_db

# ---------------------------------------------------------------------------
# Human-like reply templates
# ---------------------------------------------------------------------------

def _pick(*variants: str) -> str:
    return random.choice(variants)


GREET_REPLIES = [
    "Hey there! 👋 Welcome to *LEVIX*! What would you like to order today?",
    "Hi! Great to see you 😊 I'm LEVIX, your food buddy. What are you craving?",
    "Hello! 🙌 Ready to take your order. What sounds good today?",
]

MENU_PROMPT = (
    "Here's a quick look at our categories:\n{categories}\n\n"
    "Just tell me what you'd like — e.g. _chicken biryani_ or _veg combo_ 🍽️"
)

ITEM_NOT_FOUND = [
    "Hmm, I couldn't find *{hint}* on our menu 🤔 Could you be more specific?",
    "I don't see *{hint}* right now. Want me to suggest something similar?",
    "Sorry, *{hint}* isn't available. Want to check our popular items?",
]

MULTIPLE_MATCHES = (
    "I found a few options for *{hint}*:\n{options}\n\nWhich one did you mean? "
    "Just reply with the number 👆"
)

ITEM_ADDED = [
    "✅ Added *{qty}x {item}* to your cart! (₹{unit_price} each)\n"
    "Cart total: *₹{total}*\n\nAnything else?",
    "Done! *{qty}x {item}* is in your cart 🛒 Total so far: *₹{total}*\nWhat else can I add?",
]

ITEM_REMOVED = [
    "Removed *{item}* from your cart 👍 Updated total: *₹{total}*",
    "Got it, *{item}* is out! New total: *₹{total}*",
]

ITEM_NOT_IN_CART = [
    "I couldn't find *{hint}* in your cart. Here's what you have:\n{cart_list}",
]

QTY_CHANGED = [
    "Updated! *{item}* is now *{new_qty}x* in your cart. Subtotal: *₹{subtotal}*",
    "Changed to *{new_qty}x {item}* ✅ New subtotal: *₹{subtotal}*",
]

EMPTY_CART = [
    "Your cart is empty! Tell me what you'd like — e.g. _2 chicken biryani_ 🍗",
    "Nothing in the cart yet. What are you in the mood for today?",
]

DELIVERY_PROMPT = (
    "Perfect! 🚗 Please share your delivery address.\n\n"
    "_(Street / flat no / area / landmark)_"
)

PICKUP_CONFIRM = (
    "Great, you'll pick it up from our store! 🏪\n"
    "Here's your order summary:\n{summary}\n\n"
    "Total: *₹{total}*\n\nShall I confirm this order? _(yes / no)_"
)

ADDRESS_RECEIVED = (
    "Got it! Delivering to:\n_{address}_\n\n"
    "Here's your order:\n{summary}\n\n"
    "Total: *₹{total}*\n\nConfirm order? _(yes / no)_"
)

ORDER_CONFIRMED = (
    "🎉 Order placed successfully!\n"
    "Order ID: *#{order_id}*\n"
    "{delivery_line}\n"
    "Total: *₹{total}*\n\n"
    "We'll notify you once it's ready. Thank you! 🙏"
)

ORDER_CANCELLED = [
    "No problem, order cancelled. Your cart has been cleared. Start fresh anytime! 😊",
    "Okay, cancelled! Come back when you're ready to order 👋",
]

UNCLEAR_MESSAGE = [
    "I'm not sure I got that 😅 You can:\n"
    "• Tell me what to order (e.g. _add biryani_)\n"
    "• Ask for price (e.g. _biryani price_)\n"
    "• View your cart (e.g. _show cart_)\n"
    "• Choose delivery or pickup",
    "Hmm, didn't quite catch that! Try saying something like:\n"
    "_'2 chicken biryani'_ or _'what's on the menu?'_ 😊",
]

PRICE_REPLY = (
    "💰 *{name}*\n"
    "Price: *₹{price}*\n"
    "{desc_line}"
    "Want to add it to your cart? Just say _add {name}_ 👇"
)

REPEAT_ORDER_FOUND = (
    "Found your last order from {date}! Here it is:\n{summary}\n\n"
    "Total: *₹{total}*\n\nShall I load this into your cart? _(yes / no)_"
)

NO_PREVIOUS_ORDER = [
    "Looks like you haven't ordered from us before — let's fix that! 😄 What would you like?",
    "No previous orders found. Let me know what you'd like today!",
]

GROUP_MEAL_REPLY = (
    "Sure! 🍽️ Here are some options for *{group_size} people* under *₹{budget}*:\n"
    "{options}\n\nJust say _add_ + the item name to build your order!"
)

RECOMMENDATION_REPLY = (
    "Here are our most popular picks right now 🔥\n"
    "{options}\n\nWant to add any? Just say the name!"
)

GOODBYE_REPLY = [
    "Take care! Come back when you're hungry 😊",
    "Bye! See you next time 👋",
    "Thank you for visiting LEVIX! Have a great day! 🎉",
]

PREFERENCE_SET = [
    "Got it! *{spice}* spice level noted 🌶️",
    "Sure, keeping it *{spice}* 👍",
]

SPICE_LABELS = {
    "mild": "mild",
    "medium": "medium",
    "extra_spicy": "extra spicy 🌶️🌶️🌶️",
}

# ---------------------------------------------------------------------------
# LEVIXRouter
# ---------------------------------------------------------------------------

class LEVIXRouter:

    def __init__(self, database_url: str, echo_sql: bool = False) -> None:
        init_db(database_url, echo=echo_sql)
        init_order_db(database_url, echo=echo_sql)
        self.intent_engine = IntentEngine()
        self.memory = MemoryEngine()
        self.order_engine = OrderEngine()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle(self, phone: str, message: str) -> str:
        """
        Main handler. Returns a WhatsApp-safe reply string.
        """
        message = message.strip()
        if not message:
            return _pick(*UNCLEAR_MESSAGE)

        # 1. Load customer + session
        customer = self.memory.get_or_create_customer(phone)
        session = self.memory.get_active_session(phone)
        if not session:
            session = self.memory.create_session(phone, customer["id"])

        # 2. Classify intent with current FSM state
        intent = self.intent_engine.classify(message, session_state=session["state"])

        # 3. Route
        reply, session_updates = self._dispatch(intent, session, customer, message)

        # 4. Persist session changes
        if session_updates:
            self.memory.save_session(session["id"], session_updates)

        return reply

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        intent,
        session: dict,
        customer: dict,
        raw_message: str,
    ) -> tuple[str, dict]:

        name = intent.name
        e = intent.entities
        cart: list[dict] = session.get("cart", [])
        prefs: dict = session.get("preferences", {})

        updates: dict[str, Any] = {}

        # ---- Greet --------------------------------------------------------
        if name == "greet":
            greeting = _pick(*GREET_REPLIES)
            updates["state"] = "browsing"
            return greeting, updates

        # ---- Goodbye -------------------------------------------------------
        if name == "goodbye":
            return _pick(*GOODBYE_REPLY), {"state": "idle"}

        # ---- Help ----------------------------------------------------------
        if name == "ask_help":
            return (
                "Here's how to order with LEVIX:\n\n"
                "• *Browse:* say _show menu_ or _what's popular?_\n"
                "• *Add item:* say _2 chicken biryani_\n"
                "• *Remove:* say _remove coke_\n"
                "• *Change qty:* say _make it 3_\n"
                "• *Budget:* say _dinner for 5 under ₹700_\n"
                "• *Repeat:* say _same as last time_\n"
                "• *Checkout:* say _delivery_ or _pickup_\n\n"
                "What would you like to do?"
            ), updates

        # ---- View menu -----------------------------------------------------
        if name == "view_menu":
            categories = self.order_engine.get_all_categories()
            if not categories:
                return "Our menu is being updated. Please check back soon! 🙏", updates
            cat_text = "\n".join(f"  • {c}" for c in categories)
            updates["state"] = "browsing"
            return MENU_PROMPT.format(categories=cat_text), updates

        # ---- Ask price -----------------------------------------------------
        if name == "ask_price":
            hint = e.get("item_hint", raw_message)
            tokens = self.intent_engine.extract_item_hint_tokens(hint)
            products = self.order_engine.find_products(tokens, limit=1)
            if not products:
                return _pick(*ITEM_NOT_FOUND).format(hint=hint or "that item"), updates
            p = products[0]
            desc_line = f"_{p['description']}_\n" if p.get("description") else ""
            return PRICE_REPLY.format(
                name=p["name"], price=p["price"], desc_line=desc_line
            ), updates

        # ---- Add item ------------------------------------------------------
        if name == "add_item":
            hint = e.get("item_hint", raw_message)
            tokens = self.intent_engine.extract_item_hint_tokens(hint)
            qty = e.get("quantity", 1)
            spice = e.get("spice_level") or prefs.get("spice_level")
            products = self.order_engine.find_products(tokens, limit=3)

            if not products:
                updates["state"] = "awaiting_item_clarification"
                return _pick(*ITEM_NOT_FOUND).format(hint=hint or "that item"), updates

            if len(products) > 1 and _ambiguous(products, tokens):
                options = "\n".join(
                    f"  {i+1}. *{p['name']}* — ₹{p['price']}" for i, p in enumerate(products)
                )
                updates["state"] = "awaiting_item_selection"
                updates["pending_qty"] = qty
                updates["pending_products"] = [p["id"] for p in products]
                return MULTIPLE_MATCHES.format(
                    hint=hint or "that item", options=options
                ), updates

            product = products[0]
            new_cart, ctx = self.order_engine.cart_add(cart, product, qty, spice)
            summary = self.order_engine.cart_summary(new_cart)
            updates["cart"] = new_cart
            updates["state"] = "cart_building"
            return _pick(*ITEM_ADDED).format(
                qty=qty,
                item=product["name"],
                unit_price=product["price"],
                total=summary["total"],
            ), updates

        # ---- Handle numeric reply for item selection -----------------------
        if name == "unknown" and session.get("state") == "awaiting_item_selection":
            m = re.search(r"\d+", raw_message)
            if m:
                idx = int(m.group()) - 1
                pending_ids: list[int] = session.get("pending_products", [])
                qty: int = session.get("pending_qty", 1)
                if 0 <= idx < len(pending_ids):
                    product = self.order_engine.get_product_by_id(pending_ids[idx])
                    if product:
                        spice = prefs.get("spice_level")
                        new_cart, _ = self.order_engine.cart_add(cart, product, qty, spice)
                        summary = self.order_engine.cart_summary(new_cart)
                        updates["cart"] = new_cart
                        updates["state"] = "cart_building"
                        updates.pop("pending_products", None)
                        updates.pop("pending_qty", None)
                        return _pick(*ITEM_ADDED).format(
                            qty=qty,
                            item=product["name"],
                            unit_price=product["price"],
                            total=summary["total"],
                        ), updates

        # ---- Remove item ---------------------------------------------------
        if name == "remove_item":
            hint = e.get("item_hint", raw_message)
            tokens = self.intent_engine.extract_item_hint_tokens(hint)
            new_cart, ctx = self.order_engine.cart_remove(cart, tokens)
            summary = self.order_engine.cart_summary(new_cart)
            updates["cart"] = new_cart

            if ctx["action"] == "not_found":
                if not cart:
                    return _pick(*EMPTY_CART), updates
                cart_list = _format_cart_list(summary["items"])
                return _pick(*ITEM_NOT_IN_CART).format(
                    hint=hint, cart_list=cart_list
                ), updates

            return _pick(*ITEM_REMOVED).format(
                item=ctx["item"], total=summary["total"]
            ), updates

        # ---- Change quantity -----------------------------------------------
        if name == "change_quantity":
            qty = e.get("quantity")
            if qty is None:
                return "How many would you like? Just tell me the number 🔢", updates
            hint = e.get("item_hint", "")
            tokens = self.intent_engine.extract_item_hint_tokens(hint) if hint else []
            new_cart, ctx = self.order_engine.cart_change_quantity(cart, tokens, qty)
            updates["cart"] = new_cart

            if ctx.get("action") == "cart_empty":
                return _pick(*EMPTY_CART), updates
            if ctx.get("action") == "not_found":
                summary = self.order_engine.cart_summary(new_cart)
                return _pick(*ITEM_NOT_IN_CART).format(
                    hint=hint, cart_list=_format_cart_list(summary["items"])
                ), updates

            return _pick(*QTY_CHANGED).format(
                item=ctx["item"],
                new_qty=ctx["new_qty"],
                subtotal=ctx["subtotal"],
            ), updates

        # ---- Set preference -----------------------------------------------
        if name == "set_preference":
            spice = e.get("spice_level")
            if spice:
                prefs["spice_level"] = spice
                updates["preferences"] = prefs
                new_cart, _ = self.order_engine.cart_apply_preference(cart, [], spice)
                updates["cart"] = new_cart
                return _pick(*PREFERENCE_SET).format(
                    spice=SPICE_LABELS.get(spice, spice)
                ), updates
            return _pick(*UNCLEAR_MESSAGE), updates

        # ---- View cart -----------------------------------------------------
        if name == "view_cart":
            summary = self.order_engine.cart_summary(cart)
            if summary["is_empty"]:
                return _pick(*EMPTY_CART), updates
            cart_text = _format_cart_lines(summary["items"])
            return (
                f"🛒 *Your Cart:*\n{cart_text}\n\n"
                f"*Total: ₹{summary['total']}*\n\n"
                "Ready to order? Say _delivery_ or _pickup_ 👇"
            ), updates

        # ---- Repeat last order --------------------------------------------
        if name == "repeat_last_order":
            last = self.memory.get_last_order(session["phone"])
            if not last:
                return _pick(*NO_PREVIOUS_ORDER), updates
            rebuilt = self.order_engine.rebuild_cart_from_order(last)
            summary = self.order_engine.cart_summary(rebuilt)
            dt = _format_date(last["placed_at"])
            updates["state"] = "confirm_repeat"
            updates["pending_cart"] = rebuilt
            return REPEAT_ORDER_FOUND.format(
                date=dt,
                summary=_format_cart_lines(summary["items"]),
                total=summary["total"],
            ), updates

        # ---- Confirm repeat order -----------------------------------------
        if session.get("state") == "confirm_repeat" and name == "confirm_order":
            pending = session.get("pending_cart", [])
            if pending:
                updates["cart"] = pending
                updates["state"] = "cart_building"
                summary = self.order_engine.cart_summary(pending)
                return (
                    f"✅ Loaded! *{summary['item_count']} items* in cart.\n"
                    f"Total: *₹{summary['total']}*\n\n"
                    "How would you like to receive it? _delivery_ or _pickup_? 🚗"
                ), updates

        # ---- Select delivery ----------------------------------------------
        if name == "select_delivery":
            if not cart:
                return _pick(*EMPTY_CART), updates
            # Check if customer has saved address
            if customer.get("default_address"):
                updates["state"] = "awaiting_address_confirm"
                updates["delivery_type"] = "delivery"
                return (
                    f"Deliver to your saved address?\n"
                    f"_{customer['default_address']}_\n\n"
                    "_(yes)_ or share a new address 👇"
                ), updates
            updates["state"] = "awaiting_address"
            updates["delivery_type"] = "delivery"
            return DELIVERY_PROMPT, updates

        # ---- Select pickup ------------------------------------------------
        if name == "select_pickup":
            if not cart:
                return _pick(*EMPTY_CART), updates
            summary = self.order_engine.cart_summary(cart)
            updates["state"] = "awaiting_confirm"
            updates["delivery_type"] = "pickup"
            return PICKUP_CONFIRM.format(
                summary=_format_cart_lines(summary["items"]),
                total=summary["total"],
            ), updates

        # ---- Address confirm (use saved address) -------------------------
        if session.get("state") == "awaiting_address_confirm":
            if name == "confirm_order":
                address = customer["default_address"]
                updates["delivery_address"] = address
                summary = self.order_engine.cart_summary(cart)
                updates["state"] = "awaiting_confirm"
                return ADDRESS_RECEIVED.format(
                    address=address,
                    summary=_format_cart_lines(summary["items"]),
                    total=summary["total"],
                ), updates
            # They typed something else — treat as new address
            if len(raw_message) > 6:
                address = raw_message.strip()
                updates["delivery_address"] = address
                self.memory.update_customer_address(session["phone"], address)
                summary = self.order_engine.cart_summary(cart)
                updates["state"] = "awaiting_confirm"
                return ADDRESS_RECEIVED.format(
                    address=address,
                    summary=_format_cart_lines(summary["items"]),
                    total=summary["total"],
                ), updates

        # ---- Provide address ---------------------------------------------
        if name == "provide_address":
            address = e.get("address_text", raw_message).strip()
            updates["delivery_address"] = address
            self.memory.update_customer_address(session["phone"], address)
            summary = self.order_engine.cart_summary(cart)
            updates["state"] = "awaiting_confirm"
            return ADDRESS_RECEIVED.format(
                address=address,
                summary=_format_cart_lines(summary["items"]),
                total=summary["total"],
            ), updates

        # ---- Confirm order -----------------------------------------------
        if name == "confirm_order":
            if session.get("state") != "awaiting_confirm":
                if cart:
                    summary = self.order_engine.cart_summary(cart)
                    updates["state"] = "awaiting_confirm"
                    return (
                        f"Here's your order:\n{_format_cart_lines(summary['items'])}\n\n"
                        f"*Total: ₹{summary['total']}*\n\n"
                        "Shall I confirm? _(yes / no)_"
                    ), updates
                return _pick(*EMPTY_CART), updates

            summary = self.order_engine.cart_summary(cart)
            if summary["is_empty"]:
                return _pick(*EMPTY_CART), updates

            delivery_type = session.get("delivery_type", "pickup")
            delivery_address = session.get("delivery_address")
            if delivery_type == "delivery" and not delivery_address:
                updates["state"] = "awaiting_address"
                return DELIVERY_PROMPT, updates

            # Idempotency key (minute-bucket)
            minute_bucket = datetime.utcnow().strftime("%Y%m%d%H%M")
            idem_key = self.order_engine.build_idempotency_key(
                session["phone"], cart, minute_bucket
            )

            result = self.memory.record_order(
                phone=session["phone"],
                customer_id=session["customer_id"],
                session_id=session["id"],
                cart=cart,
                total=summary["total"],
                delivery_type=delivery_type,
                delivery_address=delivery_address,
                idempotency_key=idem_key,
            )

            if result is None:
                # Duplicate guard triggered
                return (
                    "⚠️ It looks like this order was already placed! "
                    "Check your order status or start a new order."
                ), {}

            delivery_line = (
                f"📍 Delivering to: _{delivery_address}_"
                if delivery_type == "delivery"
                else "🏪 Pickup from our store"
            )

            self.memory.close_session(session["id"])
            return ORDER_CONFIRMED.format(
                order_id=result["id"][:8].upper(),
                delivery_line=delivery_line,
                total=summary["total"],
            ), {}

        # ---- Cancel order -------------------------------------------------
        if name == "cancel_order":
            self.memory.close_session(session["id"])
            return _pick(*ORDER_CANCELLED), {"state": "idle", "cart": []}

        # ---- Recommendations ---------------------------------------------
        if name == "ask_recommendation":
            products = self.order_engine.get_popular_products(limit=5)
            if not products:
                return "Our menu is being updated — check back soon! 🙏", updates
            options = "\n".join(
                f"  {i+1}. *{p['name']}* — ₹{p['price']}"
                + (" ⭐" if p["is_popular"] else "")
                for i, p in enumerate(products)
            )
            return RECOMMENDATION_REPLY.format(options=options), updates

        # ---- Group meal / budget -----------------------------------------
        if name == "group_meal_request":
            budget = e.get("budget")
            group = e.get("group_size", 1)
            if budget:
                products = self.order_engine.get_products_by_budget(budget, group)
                if not products:
                    return (
                        f"Hmm, couldn't find items within ₹{budget} for {group} people 😕\n"
                        "Want me to suggest our best value meals instead?"
                    ), updates
                options = "\n".join(
                    f"  • *{p['name']}* — ₹{p['price']} per person"
                    for p in products[:6]
                )
                return GROUP_MEAL_REPLY.format(
                    group_size=group, budget=budget, options=options
                ), updates
            return (
                f"Great, feeding {group} people! What's your budget? "
                "_(e.g. under ₹700)_"
            ), updates

        # ---- Unknown / fallback ------------------------------------------
        # Smart recovery: check if it looks like an item name with no verb
        if len(raw_message.split()) >= 1:
            tokens = self.intent_engine.extract_item_hint_tokens(raw_message)
            if tokens:
                products = self.order_engine.find_products(tokens, limit=2)
                if products and len(products) == 1:
                    p = products[0]
                    return (
                        f"Did you mean *{p['name']}* (₹{p['price']})? 🤔\n"
                        f"Say _add {p['name']}_ to order, or _price_ to check the rate!"
                    ), updates
                if products:
                    options = "\n".join(
                        f"  {i+1}. *{p['name']}* — ₹{p['price']}"
                        for i, p in enumerate(products)
                    )
                    return (
                        f"Did you mean one of these?\n{options}\n\n"
                        "Reply with a number or say _add [item name]_ 👆"
                    ), updates

        return _pick(*UNCLEAR_MESSAGE), updates


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_cart_lines(items: list[dict]) -> str:
    if not items:
        return "_(empty)_"
    lines = []
    for it in items:
        spice = f" [{SPICE_LABELS.get(it['spice_level'], it['spice_level'])}]" if it.get("spice_level") else ""
        lines.append(
            f"  • {it['qty']}x *{it['name']}*{spice} — ₹{it['subtotal']}"
        )
    return "\n".join(lines)


def _format_cart_list(items: list[dict]) -> str:
    return "\n".join(f"  • {it['qty']}x {it['name']}" for it in items)


def _format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d %b %Y")
    except Exception:
        return iso_str


def _ambiguous(products: list[dict], tokens: list[str]) -> bool:
    """Return True if multiple products have similar match scores."""
    if len(products) < 2:
        return False

    def _score(p: dict) -> int:
        text = p["name"].lower() + " " + (p.get("tags") or "")
        return sum(1 for t in tokens if t in text)

    scores = [_score(p) for p in products[:3]]
    return abs(scores[0] - scores[1]) <= 1


SPICE_LABELS = {
    "mild": "mild",
    "medium": "medium",
    "extra_spicy": "extra spicy 🌶️🌶️🌶️",
}
