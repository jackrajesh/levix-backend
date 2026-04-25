import random
import logging

logger = logging.getLogger("levix.fallback_engine")

class FallbackEngine:
    """
    Generates premium, human-like replies without AI.
    Used for Layer 1 (Rules) and Layer 7 (Rate Limit Shield).
    """

    TEMPLATES = {
        "GREETING": [
            "Hi! Welcome to {shop_name}. How can I help you today? 😊",
            "Vanakkam! 🙏 How can we help you at {shop_name}? ✨",
            "Namaste! 🙏 What are you looking for today? I'm here to help!"
        ],
        "PRICE_GENERAL": [
            "Which item would you like the price for? I'll find the best deal for you! 🏷️",
            "I'm happy to help with prices. Which product are you checking? 😊"
        ],
        "STOCK_GENERAL": [
            "Checking stock for you! 📦 Which item are you looking for?",
            "Tell me the item name and I'll see if it's available in our shop! ✨"
        ],
        "PRODUCT_INFO": [
            "Yes! *{product_name}* is available! {details}. Price: ₹{price}. {stock}. 🏷️",
            "*{product_name}* costs ₹{price}. It's {details} and currently {stock}. Want to book it? ✨"
        ],
        "STATUS": [
            "Checking order #{order_id}... It's currently *{status}*. 🚚 Don't worry, it's on the way!",
            "Your order #{order_id} is *{status}*. We're working on it! 🙏"
        ],
        "NO_ORDER_FOUND": [
            "I couldn't find an active order for this number. Could you double-check? 🤔",
            "Hmm, no order found. No worries, just send your order ID or phone number again!"
        ],
        "HELP": [
            "I'm LEVIX! I can help you find products, check prices, and take orders. Just ask! 😊",
            "I can assist with orders and info. What are you looking for today? ✨"
        ],
        "CANCEL": [
            "Got it. Your request has been cancelled. Can I help with anything else? 👍",
            "No problem, cancelled. Let me know if you need anything else! 😊"
        ],
        "OOS": [
            "Sorry, *{product_name}* is currently out of stock. Want to see something similar? 📦",
            "Unfortunately, *{product_name}* is sold out right now. Can I suggest an alternative? 😊"
        ],
        "UNKNOWN": [
            "I'm not quite sure, but I've alerted the owner to check for you! 😊 They will contact you shortly.",
            "Let me check that and get back to you soon. Anything else I can help with? ✨"
        ],
        "ORDER_START": [
            "Great! Let's get your order started. 🛍️",
            "Exciting! Starting your order flow now. ✨ What's your delivery address?"
        ],
        "ORDER_PROMPT": [
            "Type *ORDER* to place your order! 🛍️",
            "Want to buy this? Just type *ORDER*! ✨"
        ],
        "COMPLAINT": [
            "I'm really sorry to hear that. I've alerted the owner to look into this immediately. 🙏 We will fix this for you.",
            "I apologize for the trouble. Our team will assist you shortly. Please stay tuned. 🙏"
        ]
    }

    @classmethod
    def get_reply(cls, intent: str, context: dict) -> str:
        templates = cls.TEMPLATES.get(intent, cls.TEMPLATES["UNKNOWN"])
        template = random.choice(templates)
        
        # Add order prompt for product info (Phase 2)
        if intent == "PRODUCT_INFO":
            template += "\n\n" + random.choice(cls.TEMPLATES["ORDER_PROMPT"])

        try:
            # Clean up empty strings or None in context
            safe_context = {k: (v if v is not None else "") for k, v in context.items()}
            return template.format(**safe_context)
        except Exception:
            return random.choice(cls.TEMPLATES["UNKNOWN"])
