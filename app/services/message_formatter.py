"""
message_formatter.py — LEVIX WhatsApp Message Formatter
========================================================
All human-readable reply strings live here.

Design philosophy:
- Templates never live in router logic.
- All format strings use keyword placeholders.
- Random variant selection creates human-like variety.
- Every public method is a classmethod returning a str — nothing stateful.
"""

from __future__ import annotations

import random
import logging
from typing import Any, Optional

logger = logging.getLogger("levix.formatter")

# FAIL 6.3 + 6.4: Universal Category Terms (Vocabulary Map)
_CATEGORY_TERMS = {
    "Food & Restaurant": {
        "catalogue": "menu",
        "item": "food",
        "items": "dishes",
        "unit": "serving",
        "collection": "menu",
        "action": "order",
        "browse": "see our menu",
        "products": "items"
    },
    "Clothing & Fashion": {
        "catalogue": "catalogue",
        "item": "item",
        "items": "items",
        "unit": "style",
        "collection": "collection",
        "action": "buy",
        "browse": "browse our collection",
        "products": "pieces"
    },
    "Electronics": {
        "catalogue": "product list",
        "item": "product",
        "items": "products",
        "unit": "model",
        "collection": "range",
        "action": "buy",
        "browse": "see our products",
        "products": "products"
    },
    "Grocery": {
        "catalogue": "items",
        "item": "product",
        "items": "products",
        "unit": "unit",
        "collection": "stock",
        "action": "buy",
        "browse": "see our items",
        "products": "products"
    },
    "General / Other": {
        "catalogue": "catalogue",
        "item": "item",
        "items": "items",
        "unit": "unit",
        "collection": "catalogue",
        "action": "buy",
        "browse": "see what we have",
        "products": "products"
    }
}


# ═══════════════════════════════════════════════════════════════════════════════
# Template banks
# ═══════════════════════════════════════════════════════════════════════════════

_GREET = [
    "Hey there! 👋 Welcome to *{shop_name}*! What would you like to {action} today?",
    "Hi! Great to see you 😊 What are you in the mood for?",
    "Vanakkam! 🙏 I'm here to help at *{shop_name}*. What can I get you?",
    "Hello! 😊 Ready to take your {action} at *{shop_name}*. What would you like?",
]

_WELCOME_BACK_VIP = [
    "Welcome back, VIP! ⭐ Great to see you again. Ready for your usual, or shall I suggest something new?",
    "Hey! ⭐ Our favourite customer is back! What can I get for you today?",
]

_WELCOME_BACK_REGULAR = [
    "Welcome back 😊 Good to see you! What are we ordering today?",
    "Hi again! 😊 Ready to take your order. What are you thinking?",
]

_WELCOME_BACK_WITH_FAV = [
    "Welcome back 😊 Should I add *{fav}* again or something different today?",
    "Hey! Last time you loved *{fav}* — want the same, or shall I suggest something new?",
]

_ITEM_ADDED = [
    "✅ Added *{qty}x {item}* (₹{unit_price} each)\nCart total: *₹{total}*\n\nAnything else?",
    "Done! *{qty}x {item}* is in your cart 😊 Total so far: *₹{total}*\n\nWhat else?",
]

_ITEM_ADDED_UPSELL = [
    "✅ *{qty}x {item}* added! Total: *₹{total}*\n\n💡 Customers also love *{upsell}* — want to add it?",
]

_ITEM_REMOVED = [
    "Removed *{item}* from your cart 👍 Updated total: *₹{total}*",
    "Done! *{item}* is out. New total: *₹{total}*",
]

_QTY_UPDATED = [
    "Updated! *{item}* is now *{new_qty}x*. Subtotal: *₹{subtotal}*",
    "Got it 👍 Changed *{item}* to *{new_qty}x*. Subtotal: *₹{subtotal}*",
]

_ITEM_NOT_FOUND = [
    "Hmm, I couldn't find *{hint}* \U0001f914. Remember we are a {item} store! Reply *{catalogue}* to see all our {items}.",
    "Sorry, *{hint}* isn't on our {catalogue} right now. We only sell {items}! Reply *{catalogue}* to see what we have!",
]

_ITEM_OUT_OF_STOCK = [
    "Ah, *{item}* is out of stock right now 😔 Want something similar?",
    "Sorry! *{item}* just sold out. Can I suggest an alternative?",
]

_EMPTY_CART = [
    "Your cart is empty! Tell me what you'd like — e.g. _2 chicken biryani_ 🍗",
    "Nothing in your cart yet 😊 What would you like to order?",
]

_CART_SUMMARY = "Your cart:\n{lines}\nTotal: *₹{total}*"

_DELIVERY_PROMPT = [
    "Perfect! 🚗 Please share your delivery address.\n_(Street / flat no / area / city)_",
    "Great choice! 😊 Send me your delivery address and I'll get that to you.",
]

_PICKUP_SUMMARY = (
    "Great, you'll pick it up! 🏪\nHere's your order:\n{summary}\n"
    "\nTotal: *₹{total}*\n\nShall I confirm? _(yes / no)_"
)

_ADDRESS_RECEIVED = (
    "Got it! Delivering to:\n_{address}_\n\nHere's your order:\n{summary}"
    "\n\nTotal: *₹{total}*\n\nConfirm order? _(yes / no)_"
)

_ORDER_CONFIRMED_DELIVERY = (
    "🎉 Order placed!\n📍 Delivering to: _{address}_\n"
    "Total: *₹{total}*\n\nWe'll notify you when it's on its way!"
)

_ORDER_CONFIRMED_PICKUP = (
    "🎉 Order placed!\n🏪 Pickup from store\nTotal: *₹{total}*\n\nSee you soon!"
)

_ORDER_CANCELLED = [
    "Cart cleared 👍 What else can I get you?",
    "No problem! Let me know when you're ready to order again 😊",
]

_ALREADY_CONFIRMED = [
    "Your order is already confirmed 😊 We're working on it!",
    "Looks like that order is already placed 👍 Anything else?",
]

_WAIT_WHAT = [
    "I didn't quite catch that! \U0001f9d0 Try saying something like: _'2 biryani'_ or _'show menu'_. What can I help with?",
    "Hmm, I'm not sure what you mean. You can browse our *menu* or ask me about our products!",
]

_SPICE_NOTED = [
    "Got it! Note added to *{item}*: {modifier} 🌶️",
    "Sure! Updating *{item}* with: {modifier}",
]

_RECOMMENDATION_BUDGET = (
    "For a budget of *₹{budget}*, here's what I'd suggest:\n{lines}\n\nTotal: *₹{total}*\n\nShall I add these to your cart? _(yes / no)_"
)

_RECOMMENDATION_GENERAL = (
    "Here are some of our popular items:\n{lines}\n\nWhat would you like to try?"
)

_ASK_DELIVERY_MODE = [
    "Got it 😊 Pickup or Delivery?",
    "Almost there! Would you like pickup or delivery?",
]

_REPEAT_ORDER_PROMPT = [
    "Last time you ordered: {summary}\n\nWant the same again? _(yes / no)_",
    "Your previous order was: {summary}\n\nShall I reorder that for you?",
]

_NO_PREVIOUS_ORDER = [
    "Looks like you haven't ordered from us before 😊 What would you like?",
    "No previous order found! Let's start fresh — what are you in the mood for?",
]

_COMPLAINT = [
    "I'm really sorry to hear that 🙏 I've flagged this for the owner to check immediately. We'll make it right!",
    "That's not acceptable, and I sincerely apologise 🙏 The owner has been alerted. We'll get back to you shortly.",
]

_HELP = [
    "I'm the AI assistant for *{shop_name}* 😊 I can:\n• Take your order\n• Show menu & prices\n• Recommend combos\n\nJust tell me what you'd like!",
]

_GOODBYE = [
    "Thanks for visiting *{shop_name}*! Have a great day 😊",
    "See you next time! 🙏 Take care.",
]

_MENU_INTRO = "Here's what we have 😊\n{lines}\n\nWhat would you like to order?"

_VIEW_MENU_NO_STOCK = "Hmm, it seems our menu is empty right now. Please check back soon!"

_ADDRESS_CLARIFY = [
    "Could you give a bit more detail on the address? Like the street name or landmark 😊",
    "Could you add the area or street name to the address? That helps us deliver correctly.",
]

_CART_EDIT_PROMPT = [
    "Sure! What would you like to change?",
    "No problem 😊 Tell me what to update in your cart.",
]

_MISSING_PRODUCT_NOTED = [
    "I don't have *{hint}* in our menu right now, but I've noted your request for the owner! 📝 Is there anything else I can help you with?",
    "We don't carry *{hint}* yet, but I've logged your interest 👍 Want to try something similar?",
]

_SYSTEM_ERROR = "Something went wrong on our end \U0001f64f. Your cart is safe \u2014 reply *place order* to try again."

# Change 4: Onboarding Flow
_ONBOARDING_NAME = "Hi! Welcome to *{shop_name}* 😊\nBefore we get started, what's your name?"
_ONBOARDING_PHONE = "Nice to meet you, {name}! 😊\nCould I get your phone number? (10 digits)"
_ONBOARDING_PHONE_INVALID = "That doesn't look right — please send your 10-digit number."
_ONBOARDING_COMPLETE = "Perfect! Here's what we have for you today 👇"

_MISSING_PRODUCT_RESPONSE = "Sorry, we don't have *{product}* right now \U0001f614\nI've noted your interest and the owner will be informed!"


# ═══════════════════════════════════════════════════════════════════════════════
# MessageFormatter — stateless class
# ═══════════════════════════════════════════════════════════════════════════════

class MessageFormatter:
    """
    Factory for every WhatsApp reply string LEVIX sends.

    Every method is a classmethod that returns a formatted str.
    Pass keyword arguments matching the template placeholders.
    """

    @classmethod
    def _get_terms(cls, category: str) -> dict:
        return _CATEGORY_TERMS.get(category, _CATEGORY_TERMS["General / Other"])

    @classmethod
    def _pick(cls, pool: list[str], category: str = "General / Other", **kw: Any) -> str:
        template = random.choice(pool)
        terms = cls._get_terms(category)
        combined = {**terms, **kw}
        try:
            return template.format(**combined)
        except KeyError as exc:
            logger.warning(f"[FORMATTER] Missing placeholder {exc} in template")
            return template

    # ── Greeting ──────────────────────────────────────────────────────────────

    @classmethod
    def greet(cls, shop_name: str, action: str = "order") -> str:
        return random.choice([
            f"Hey there! \U0001f44b Welcome to *{shop_name}*! What would you like to {action} today?",
            f"Hi! Great to see you \U0001f60a What are you in the mood for?",
            f"Vanakkam! \U0001f64f I'm here to help at *{shop_name}*. What can I get you?",
            f"Hello! \U0001f60a Ready to take your {action} at *{shop_name}*. What would you like?",
        ])

    @classmethod
    def welcome_back(
        cls,
        vip_tier: str,
        fav_product: Optional[str] = None,
    ) -> str:
        if fav_product:
            return cls._pick(_WELCOME_BACK_WITH_FAV, fav=fav_product)
        if vip_tier == "VIP":
            return cls._pick(_WELCOME_BACK_VIP)
        return cls._pick(_WELCOME_BACK_REGULAR)

    # ── Cart mutations ────────────────────────────────────────────────────────

    @classmethod
    def item_added(
        cls,
        qty: int,
        item: str,
        unit_price: float,
        total: float,
        upsell: Optional[str] = None,
    ) -> str:
        if upsell:
            return cls._pick(
                _ITEM_ADDED_UPSELL,
                qty=qty,
                item=item,
                unit_price=f"{unit_price:.0f}",
                total=f"{total:.0f}",
                upsell=upsell,
            )
        return cls._pick(
            _ITEM_ADDED,
            qty=qty,
            item=item,
            unit_price=f"{unit_price:.0f}",
            total=f"{total:.0f}",
        )

    @classmethod
    def item_removed(cls, item: str, total: float) -> str:
        return cls._pick(_ITEM_REMOVED, item=item, total=f"{total:.0f}")

    @classmethod
    def quantity_updated(cls, item: str, new_qty: int, subtotal: float) -> str:
        return cls._pick(_QTY_UPDATED, item=item, new_qty=new_qty, subtotal=f"{subtotal:.0f}")

    @classmethod
    def item_not_found(cls, hint: str) -> str:
        return cls._pick(_ITEM_NOT_FOUND, hint=hint)

    @classmethod
    def item_out_of_stock(cls, item: str) -> str:
        return cls._pick(_ITEM_OUT_OF_STOCK, item=item)

    @classmethod
    def missing_product_noted(cls, hint: str) -> str:
        return cls._pick(_MISSING_PRODUCT_NOTED, hint=hint)

    @classmethod
    def empty_cart(cls) -> str:
        return cls._pick(_EMPTY_CART)

    @classmethod
    def cart_summary(cls, items: list[dict], total: float) -> str:
        lines = "\n".join(
            f"• {i['qty']}x {i['name']} — ₹{i['subtotal']:.0f}"
            for i in items
        )
        return _CART_SUMMARY.format(lines=lines, total=f"{total:.0f}")

    # ── Delivery / checkout ───────────────────────────────────────────────────

    @classmethod
    def ask_delivery_mode(cls) -> str:
        return cls._pick(_ASK_DELIVERY_MODE)

    @classmethod
    def delivery_prompt(cls) -> str:
        return cls._pick(_DELIVERY_PROMPT)

    @classmethod
    def address_clarify(cls) -> str:
        return cls._pick(_ADDRESS_CLARIFY)

    @classmethod
    def pickup_confirmation(cls, items: list[dict], total: float) -> str:
        summary = "\n".join(f"• {i['qty']}x {i['name']}" for i in items)
        return _PICKUP_SUMMARY.format(summary=summary, total=f"{total:.0f}")

    @classmethod
    def address_received(cls, address: str, items: list[dict], total: float) -> str:
        summary = "\n".join(f"• {i['qty']}x {i['name']}" for i in items)
        return _ADDRESS_RECEIVED.format(address=address, summary=summary, total=f"{total:.0f}")

    # ── Order completion ──────────────────────────────────────────────────────

    @classmethod
    def order_confirmed(cls, delivery_mode: str, address: str, total: float) -> str:
        if delivery_mode == "delivery":
            return _ORDER_CONFIRMED_DELIVERY.format(
                address=address, total=f"{total:.0f}"
            )
        return _ORDER_CONFIRMED_PICKUP.format(total=f"{total:.0f}")

    @classmethod
    def order_cancelled(cls) -> str:
        return cls._pick(_ORDER_CANCELLED)

    @classmethod
    def already_confirmed(cls) -> str:
        return cls._pick(_ALREADY_CONFIRMED)

    # ── Spice / preference ────────────────────────────────────────────────────

    @classmethod
    def spice_noted(cls, item: str, modifier: str) -> str:
        return cls._pick(_SPICE_NOTED, item=item, modifier=modifier)

    # ── Recommendations ───────────────────────────────────────────────────────

    @classmethod
    def recommendation_budget(
        cls, budget: float, items: list[dict], total: float
    ) -> str:
        lines = "\n".join(
            f"• {i['name']} — ₹{float(i['price']):.0f}" for i in items
        )
        return _RECOMMENDATION_BUDGET.format(
            budget=f"{budget:.0f}", lines=lines, total=f"{total:.0f}"
        )

    @classmethod
    def recommendation_general(cls, items: list[dict]) -> str:
        lines = "\n".join(
            f"• {i['name']} — ₹{float(i['price']):.0f}" for i in items
        )
        return _RECOMMENDATION_GENERAL.format(lines=lines)

    # ── Repeat order ──────────────────────────────────────────────────────────

    @classmethod
    def repeat_order_prompt(cls, summary: str) -> str:
        return cls._pick(_REPEAT_ORDER_PROMPT, summary=summary)

    @classmethod
    def no_previous_order(cls) -> str:
        return cls._pick(_NO_PREVIOUS_ORDER)

    # ── Cart editing ──────────────────────────────────────────────────────────

    @classmethod
    def cart_edit_prompt(cls) -> str:
        return cls._pick(_CART_EDIT_PROMPT)

    # ── Help / misc ───────────────────────────────────────────────────────────

    @classmethod
    def help_message(cls, shop_name: str) -> str:
        return cls._pick(_HELP, shop_name=shop_name)

    @classmethod
    def unclear(cls) -> str:
        return cls._pick(_WAIT_WHAT)

    @classmethod
    def complaint(cls) -> str:
        return cls._pick(_COMPLAINT)

    @classmethod
    def goodbye(cls, shop_name: str) -> str:
        return cls._pick(_GOODBYE, shop_name=shop_name)

    @classmethod
    def menu(cls, items: list[dict], category: str = "General / Other") -> str:
        if not items:
            return _VIEW_MENU_NO_STOCK
        lines = "\n".join(
            f"• *{i['name']}* — ₹{float(i['price']):.0f}" for i in items
        )
        return cls._pick([_MENU_INTRO], category=category, lines=lines)

    @classmethod
    def onboarding_name(cls, shop_name: str) -> str:
        return _ONBOARDING_NAME.format(shop_name=shop_name)

    @classmethod
    def onboarding_phone(cls, name: str) -> str:
        return _ONBOARDING_PHONE.format(name=name)

    @classmethod
    def onboarding_phone_invalid(cls) -> str:
        return _ONBOARDING_PHONE_INVALID

    @classmethod
    def onboarding_complete(cls) -> str:
        return _ONBOARDING_COMPLETE

    @classmethod
    def missing_product_inquiry(cls, product: str) -> str:
        return _MISSING_PRODUCT_RESPONSE.format(product=product)

    @classmethod
    def product_info(cls, name: str, price: float, points: list[str], shop_category: str = "General / Other") -> str:
        """Step 6: Formatted 2-4 bullet point product info. Never shows raw text."""
        # Generate generic points if none extracted from product_details
        if not points:
            terms = cls._get_terms(shop_category)
            points = [
                f"A quality {terms['item']} available at *{name}*.",
                f"Priced at \u20b9{price:.0f} per {terms['unit']}.",
            ]
        # Cap to 4 points, minimum 2
        display_points = points[:4]
        while len(display_points) < 2:
            display_points.append(f"Available now at \u20b9{price:.0f}.")
        bullet_points = "\n".join([f"\u2022 {p}" for p in display_points])
        return (
            f"*{name}* \u2014 \u20b9{price:.0f}\n"
            f"{bullet_points}\n\n"
            f"Want to add it to your cart?"
        )

    @classmethod
    def system_error(cls) -> str:
        return _SYSTEM_ERROR

    @classmethod
    def order_confirmed_full(
        cls,
        booking_ref: str,
        order_number: str,
        delivery_mode: str,
        address: str,
        items: list[dict],
        total: float,
    ) -> str:
        """Step 7: Full order confirmation with Booking ID, Order ID, item breakdown."""
        divider = "\u2500" * 26
        item_lines = "\n".join(
            f"  {i['qty']}x {i['name']} \u2014 \u20b9{float(i.get('unit_price', i.get('subtotal', 0)) * i.get('qty', 1) if 'unit_price' in i else i.get('subtotal', 0)):.0f}"
            for i in items
        )
        location_line = (
            f"\U0001f4cd {address}" if delivery_mode == "delivery" else "\U0001f3ea PICKUP"
        )
        lines = [
            "\U0001f389 *Order Confirmed!*",
            divider,
            f"Booking ID : *{booking_ref}*",
            f"Order ID   : *#{order_number}*",
            f"Status     : PENDING",
            location_line,
            divider,
            item_lines,
            divider,
            f"*Total: \u20b9{total:.0f}*",
            "",
            "We'll update you when your order is on the way!" if delivery_mode == "delivery" else "See you soon! \U0001f60a",
        ]
        return "\n".join(lines)
