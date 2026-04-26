# -*- coding: utf-8 -*-
"""
intent_engine.py — LEVIX NLU Layer  (v3)
==========================================
Changes from v2:
- Priority-ordered intent classification (order_status > cart_view > clear_cart > confirm > cancel > ...)
- YES+text hybrid detection (modify vs confirm)
- Multi-item parser: "2 fried rice, 1 coke, 1 rose milk"
- order_status / cart_view / clear_cart intents
- Non-food / unrelated item detection
- Better state-aware confirmation gate
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Intent:
    name:       str
    confidence: float                       # 0.0 – 1.0
    entities:   dict[str, Any] = field(default_factory=dict)
    raw_text:   str = ""
    understanding_score: int = 50           # 0-100 composite score


# ─── Stop words ───────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "on", "at", "by", "for", "with", "about",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "from", "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their", "it", "its",
    "that", "this", "these", "those", "what", "which", "who", "whom",
    "please", "just", "like", "want", "get", "give", "tell", "show",
    "let", "make", "put", "take", "go", "come", "send", "bring",
}

# Universal Domain Semantic Map
_DOMAIN_KEYWORDS = {
    "food": {
        "biryani", "rice", "curry", "roti", "naan", "parotta", "dosa", "idli",
        "meal", "lunch", "dinner", "breakfast", "snack", "chicken", "mutton",
        "fish", "prawn", "paneer", "veg", "egg", "coke", "pepsi", "juice",
        "water", "tea", "coffee", "chai", "milk", "lassi", "shake",
        "fried", "grilled", "roasted", "steam", "tandoori", "kebab", "tikka",
        "sandwich", "burger", "pizza", "wrap", "roll", "parcel", "combo",
        "wings", "leg", "piece", "fry", "masala", "gravy", "dal", "sambar",
        "rasam", "payasam", "dessert", "sweet", "halwa", "kheer", "cake",
        "pastry", "ice cream", "kulfi", "faluda", "rose", "badam",
    },
    "electronics": {
        "iphone", "android", "samsung", "laptop", "computer", "phone", "mobile",
        "charger", "cable", "screen guard", "battery", "earphones", "headphones",
        "bluetooth", "speaker", "cover", "case", "tablet", "ipad", "macbook",
        "repair", "screen", "display", "tv", "television", "fridge", "refrigerator",
        "washing machine", "ac", "air conditioner",
    },
    "fashion": {
        "shirt", "trouser", "shoes", "sandal", "dress", "jeans", "saree",
        "kurti", "lehenga", "suit", "jacket", "tshirt", "t-shirt", "pant",
        "skirt", "top", "leggings", "sneakers", "boots", "heels", "flats",
        "watch", "belt", "wallet", "bag", "purse", "sunglasses", "cap", "hat",
        "fabric", "material", "cotton", "silk", "wool", "linen", "polyester",
    },
    "pharmacy": {
        "medicine", "tablet", "capsule", "syrup", "ointment", "cream", "gel",
        "bandage", "mask", "sanitizer", "vitamin", "supplement", "dosage",
        "strip", "pack", "bottle", "injection", "health", "first aid",
    },
    "hardware": {
        "tool", "hammer", "screwdriver", "drill", "wrench", "bolt", "screw",
        "nail", "paint", "brush", "ladder", "hardware", "plywood", "metal",
        "wire", "pipe", "fitting", "electrical", "plumbing",
    },
    "grocery": {
        "milk", "egg", "bread", "butter", "cheese", "rice", "dal", "flour",
        "sugar", "salt", "oil", "spice", "vegetable", "fruit", "grocery",
        "soap", "shampoo", "detergent", "biscuit", "snacks", "beverage",
    },
    "salon": {
        "haircut", "facial", "makeup", "bridal", "spa", "massage", "waxing",
        "threading", "manicure", "pedicure", "hair", "color", "dye", "straightening",
        "smoothing", "keratin", "trim", "shave", "beard", "bleach", "cleanup",
    },
    "hardware": {
        "paint", "tools", "cement", "pipes", "nails", "hammer", "drill",
        "screws", "nuts", "bolts", "wood", "plywood", "glass", "tiles", "plumbing",
        "electrical", "wire", "switch", "socket", "bulb", "tube", "fitting",
    },
    "medical": {
        "medicine", "tablet", "capsule", "syrup", "injection", "ointment", "cream",
        "drops", "bandage", "cotton", "plaster", "thermometer", "oximeter", "mask",
    },
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _keywords(text: str) -> set[str]:
    return {t for t in _tokenize(text) if t not in _STOP_WORDS}


# ─── Entity extractors ────────────────────────────────────────────────────────

_WORD_NUMS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "couple": 2, "few": 3,
    "half a dozen": 6, "a dozen": 12, "dozen": 12,
}


def extract_quantity(text: str) -> Optional[int]:
    low = text.lower()
    # Gap 4: Check absolute/relative quantity first
    rel = _PAT_QTY_RELATIVE.search(low)
    if rel:
        return int(rel.group(1))
    abs_m = _PAT_QTY_ABSOLUTE.search(low)
    if abs_m:
        return int(abs_m.group(1))

    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 999:
            return val
    for phrase, val in sorted(_WORD_NUMS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", low):
            return val
    return None


def extract_budget(text: str) -> Optional[float]:
    low = text.lower()
    m = re.search(
        r"(?:under|below|within|max|less\s+than|upto|up\s+to|around|about)\s*"
        r"(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)",
        low,
    )
    if m:
        return float(m.group(1))
    m2 = re.search(r"(?:rs\.?|₹)\s*(\d+(?:\.\d+)?)", low)
    if m2:
        return float(m2.group(1))
    return None


def extract_group_size(text: str) -> Optional[int]:
    m = re.search(r"(?:for|feed|serves?|of|party\s+of)\s*(\d+)", text.lower())
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d+)\s*(?:people|persons?|pax|guests?|heads?)", text.lower())
    if m2:
        return int(m2.group(1))
    return None


def extract_spice_preference(text: str) -> Optional[str]:
    low = text.lower()
    if re.search(r"\b(less\s+spic|mild|not\s+spic|no\s+spic|low\s+spic|lightly\s+spic)\w*", low):
        return "mild"
    if re.search(r"\b(extra\s+spic|very\s+spic|more\s+spic|super\s+hot|fire)\w*", low):
        return "extra_spicy"
    if re.search(r"\b(medium\s+spic|normal|regular\s+spic|medium\s+hot)\w*", low):
        return "medium"
    if re.search(r"\b(spicy|hot\s+spic|spice)\w*", low):
        return "spicy"
    return None


def extract_veg_preference(text: str) -> Optional[str]:
    low = text.lower()
    if re.search(r"\b(non[\s-]?veg|nonveg|egg|chicken|mutton|fish|prawn|meat)\b", low):
        return "non_veg"
    if re.search(r"\b(veg|vegetarian|veggie|plant[\s-]?based|no\s+meat)\b", low):
        return "veg"
    return None


def extract_item_hint(text: str, trigger_pattern: re.Pattern) -> str:
    m = trigger_pattern.search(text.lower())
    if m:
        after = text[m.end():].strip()
        return after if after else text
    return text


# ─── Multi-item parser ────────────────────────────────────────────────────────

# Matches: "2 chicken biryani", "1 coke", "rose milk", "3 fried rice"
_MULTI_ITEM_RE = re.compile(
    r"(?:^|,|;|\band\b|\+)\s*(\d+)?\s*([a-zA-Z][a-zA-Z0-9\s]{1,30}?)(?=\s*(?:,|;|\band\b|\+|$))",
    re.IGNORECASE,
)

def parse_multi_items(text: str) -> list[dict[str, Any]]:
    """
    Parse a comma/and/with-separated list of items.
    Returns list of {hint: str, quantity: int} dicts.
    Only triggered when text contains separators OR 'with'.

    "2 fried rice, 1 coke, 1 rose milk" ->
    [
      {hint: "fried rice", quantity: 2},
      {hint: "coke",       quantity: 1},
      {hint: "rose milk",  quantity: 1},
    ]
    "single coke with mushroom biryani" ->
    [
      {hint: "coke",              quantity: 1},
      {hint: "mushroom biryani",  quantity: 1},
    ]
    """
    # Must have at least one separator signal (including 'with')
    if not re.search(r"[,;]|\band\b|\bplus\b|\+|\bwith\b", text, re.IGNORECASE):
        return []

    items = []
    # Split on comma, semicolon, " and ", " with ", " + "
    parts = re.split(r"[,;]|\band\b|\bwith\b|\bplus\b|\+", text, flags=re.IGNORECASE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Extract leading numeric quantity
        m = re.match(r"^(\d+)\s+(.+)$", part)
        if m:
            qty  = int(m.group(1))
            hint = m.group(2).strip()
        else:
            # Try word number (longest match first)
            qty  = 1
            hint = part
            for phrase, val in sorted(_WORD_NUMS.items(), key=lambda x: -len(x[0])):
                if re.match(rf"^{re.escape(phrase)}\s+", part.lower()):
                    qty  = val
                    hint = part[len(phrase):].strip()
                    break
        if hint and len(hint) >= 2:
            items.append({"hint": hint, "quantity": qty})
    return items


def is_unrelated(text: str, business_category: str) -> bool:
    """Return True if the message is clearly about an unrelated domain."""
    if not business_category:
        return False
        
    low_cat = business_category.lower()
    
    # Map business_category to our known domains
    active_domains = set()
    if any(w in low_cat for w in ["restaurant", "cafe", "bakery", "food", "supermarket", "grocery", "snack"]):
        active_domains.add("food")
    if any(w in low_cat for w in ["mobile", "electronic", "phone", "computer", "appliance"]):
        active_domains.add("electronics")
    if any(w in low_cat for w in ["fashion", "clothing", "apparel", "wear", "boutique", "garment"]):
        active_domains.add("fashion")
    if any(w in low_cat for w in ["salon", "beauty", "hair", "spa", "parlor"]):
        active_domains.add("salon")
    if any(w in low_cat for w in ["hardware", "paint", "tool"]):
        active_domains.add("hardware")
    if any(w in low_cat for w in ["pharmacy", "medical", "clinic"]):
        active_domains.add("medical")
        
    if not active_domains:
        return False  # Mixed or unknown stores accept everything

    tokens = set(_tokenize(text))
    
    # Count matches in active domains vs inactive domains
    active_matches = 0
    inactive_matches = 0
    
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        matches = len(tokens & keywords)
        if domain in active_domains:
            active_matches += matches
        else:
            inactive_matches += matches
            
    # It is unrelated if it strongly matches an inactive domain and has NO matches in active domains
    return inactive_matches > 0 and active_matches == 0


# ─── Pattern banks ────────────────────────────────────────────────────────────

# Bug 1 fix: typo-tolerant greeting — helo/helloo/hii/heyy/hey all map here
_PAT_GREETING = re.compile(
    r"^(hi+|he+llo*|hey+|hola|howdy|good\s*(morning|afternoon|evening|night)|"
    r"what'?s\s*up|sup|greetings|namaste|vanakkam|start|begin|yo)\b",
    re.IGNORECASE,
)
_PAT_GOODBYE = re.compile(
    r"\b(bye|goodbye|see\s+you|later|cya|take\s+care|that'?s\s+all|nothing\s+else|"
    r"thanks?\s*(that'?s\s+all)?|no\s*thanks?|done\s+for\s+now|all\s+good)\b",
    re.IGNORECASE,
)

# Bug 5 fix: fuzzy YES — yess/yesss/yeahhh all match
_PAT_CONFIRM_BARE = re.compile(
    r"^(ye+s+|yea+h*|ye+p|yu+p|yah|sure|ok+a*y*|k|confirm|correct|right|absolutely|"
    r"go\s+ahead|place.*order|proceed|done|finalize|sounds\s+good|haan+|ha)\s*[.!]*$",
    re.IGNORECASE,
)
# Yes with additional content => modify
_PAT_YES_PREFIX = re.compile(
    r"^(ye+s+|yea+h*|ok+a*y*|sure)\s+(.+)$",
    re.IGNORECASE,
)
# Bug 5 fix: fuzzy NO — noo/nooo/noooo all match
_PAT_CANCEL = re.compile(
    r"^(no+|nope|nah|cancel|stop|reset|clear\s+order|start\s+over|nevermind|never\s+mind|"
    r"forget\s+it|don'?t|abort|scratch\s+that)\b",
    re.IGNORECASE,
)
_PAT_PRODUCT_INFO = re.compile(
    r"(tell me about|details of|what is|describe|info on|more about|what does|is .* good|details about|details$)",
    re.IGNORECASE,
)
_PAT_CLEAR_CART = re.compile(
    r"\b(clear\s+cart|empty\s+cart|remove\s+all|start\s+fresh|clear\s+all|"
    r"delete\s+cart|reset\s+cart|cancel\s+cart)\b",
    re.IGNORECASE,
)
_PAT_ORDER_STATUS = re.compile(
    r"\b(order\s+status|track.*order|where.*order|order.*ready|"
    r"how\s+long|delivery\s+status|when.*deliver|check.*order|"
    r"my\s+order\s+status|status\s+of\s+order|tell.*status|order\s+update)\b",
    re.IGNORECASE,
)
_PAT_CART_VIEW = re.compile(
    r"\b(cart|basket|my\s+order|what.*ordered|show.*cart|current\s+order|"
    r"what.*added|review.*order|see.*cart|view.*cart|check.*cart|total|bill)\b",
    re.IGNORECASE,
)
_PAT_ADD = re.compile(
    r"\b(add|want|order|get|give|bring|need|take|include|put|i'?ll\s+have|gimme|lemme\s+have)\b",
    re.IGNORECASE,
)
_PAT_ADD_TRIGGER = re.compile(
    r"\b(?:add|want|order|get|give|bring|need|take|include|put|i'?ll\s+have|gimme|lemme\s+have)\b",
    re.IGNORECASE,
)
_PAT_REMOVE = re.compile(
    r"\b(remove|delete|drop|no\s+more|don'?t\s+want|skip|exclude|without|take\s+off|take\s+out)\b",
    re.IGNORECASE,
)
_PAT_REMOVE_TRIGGER = re.compile(
    r"\b(?:remove|delete|drop|skip|exclude|take\s+off)\b",
    re.IGNORECASE,
)
_PAT_CHANGE_QTY = re.compile(
    r"\b(make\s+it|change.*to|update.*to|set.*to|actually|instead|modify|"
    r"quantity|qty|increase|decrease|reduce|more|less|bump|lower)\b",
    re.IGNORECASE,
)
_PAT_DELIVERY = re.compile(
    r"\b(deliver|delivery|home\s*delivery|send.*to|drop.*at|bring.*to|shipping|door\s*delivery)\b",
    re.IGNORECASE,
)
_PAT_PICKUP = re.compile(
    r"\b(pick\s*up|pickup|self\s*collect|collect|take\s*away|takeaway|"
    r"i'?ll\s*come|come.*shop|come.*store|i\s*will\s*come)\b",
    re.IGNORECASE,
)
_PAT_ADDRESS = re.compile(
    r"\b(address|location|flat|door|house|no\.?|number|street|road|"
    r"lane|nagar|colony|area|city|pin\s*code|zip|near|landmark)\b",
    re.IGNORECASE,
)
_PAT_REPEAT = re.compile(
    r"\b(same\s+as\s+last|repeat.*order|previous.*order|last.*order|"
    r"order\s+again|reorder|usual|same\s+thing|my\s+usual)\b",
    re.IGNORECASE,
)
_PAT_RECOMMEND = re.compile(
    r"\b(suggest|recommend|what.*good|best|popular|special|top|"
    r"favourite|favorite|what.*try|anything.*good|surprise\s+me|chef|special)\b",
    re.IGNORECASE,
)
# Bug 2 fix: menu/show menu/price list all anchor here at high priority
_PAT_MENU = re.compile(
    r"\b(menu|price\s+list|item\s+list|show\s+menu|show.*items?|food\s+list|"
    r"catalogue|catalog|what.*have|what.*offer|available|options?|choices?|varieties?)\b",
    re.IGNORECASE,
)
# Bug 3 fix: checkout/place-order intent — NEVER treat as add_item
_PAT_CHECKOUT = re.compile(
    r"^(order|checkout|place order)$|\b(enough|place.*order|checkout|check\s*out|confirm.*cart|confirm.*order|"
    r"finalize.*order|done.*ordering|that'?s\s+all|proceed.*order|submit.*order)\b",
    re.IGNORECASE,
)
# Bug 4 fix: negation parser — dont need / no need / remove / not this
_PAT_NEGATE = re.compile(
    r"\b(don'?t\s+(need|want|like)|no\s+need|not\s+this|remove|cancel\s+that|"
    r"skip\s+that|take\s+it\s+off|drop|scratch|without|ignore\s+that)\b",
    re.IGNORECASE,
)
# Order-status pattern — handles 'order 12345 status' and loose queries
_PAT_ORDER_STATUS = re.compile(
    r"(order\s+\d+\s*(status|track|update|where)?|"
    r"\b(order\s+status|track.*order|where.*(?:my\s+)?order|order.*ready|"
    r"delivery\s+status|when.*deliver|check.*order|"
    r"my\s+order\s+status|tell.*status|order\s+update))\b",
    re.IGNORECASE,
)
_PAT_PRICE = re.compile(
    r"\b(price|cost|rate|how\s+much|charges?|fee|amount|rs\.?|₹)\b",
    re.IGNORECASE,
)
_PAT_SPICE = re.compile(
    r"\b(spic|mild|hot|medium|extra|less\s+spic|more\s+spic)\w*\b",
    re.IGNORECASE,
)
_PAT_HELP = re.compile(
    r"\b(help|support|assist|how.*work|how.*order|guide|confused|"
    r"don'?t\s+understand|not\s+sure|what.*do)\b",
    re.IGNORECASE,
)
_PAT_COMPLAINT = re.compile(
    r"\b(bad|terrible|awful|horrible|worst|disgusting|cheated|rotten|"
    r"not\s+fresh|wrong\s+order|missing|late|very\s+late|too\s+late|"
    r"never\s+came|complaint|refund|money\s+back)\b",
    re.IGNORECASE,
)
_PAT_VAGUE_HUNGER = re.compile(
    r"\b(hungry|something\s+(nice|good|tasty|light|heavy)|light\s+meal|"
    r"anything|whatever|you\s+decide|kids\s+food|party\s+food|"
    r"family\s+pack|cheap\s+combo|quick\s+bite|fast\s+food)\b",
    re.IGNORECASE,
)
_PAT_GROUP_MEAL = re.compile(
    r"\b(dinner|lunch|breakfast|meal|food|party|family|event)\b.{0,20}\b(for|of)\b.{0,5}\d+",
    re.IGNORECASE,
)
_PAT_CHANGE_ADDR = re.compile(
    r"\b(change\s+address|different\s+address|new\s+address|update\s+address|"
    r"wrong\s+address|incorrect\s+address)\b",
    re.IGNORECASE,
)
_PAT_EDIT_CART = re.compile(
    r"\b(change|edit|update|modify|wait|hold\s+on)\b",
    re.IGNORECASE,
)
_PAT_SERVICE_BOOKING = re.compile(
    r"\b(book|appointment|schedule|time\s+slot|booking|reserve|reservation)\b|\b(tomorrow|today|morning|evening|afternoon)\b",
    re.IGNORECASE,
)

# Bug 4 fix: Name/identity detection — MUST intercept before add_item
_PAT_NAME_UPDATE = re.compile(
    r"^(?:i(?:'?m|\s+am)\s+|my\s+name\s+is\s+|this\s+is\s+|call\s+me\s+|name\s*[:=]?\s*)([A-Za-z][A-Za-z\s]{1,30})$",
    re.IGNORECASE,
)

# Bug 3/6 fix: Stock check / availability query — do NOT add to cart
_PAT_STOCK_CHECK = re.compile(
    r"\b(do\s+you\s+have|is\s+there|got\s+any|have\s+you\s+got|any\s+stock|in\s+stock|available|availability|stock\s+check|do\s+u\s+have|you\s+have)\b",
    re.IGNORECASE,
)

# P1 FIX 4: Dedicated Inquiry intent
_PAT_INQUIRE = re.compile(
    r"\b(inquire|send\s+(?:an?\s+)?inquiry|ask\s+for|send\s+(?:an?\s+)?request)\b",
    re.IGNORECASE,
)

# Bug 5 fix: Cancel existing order by ID — separate from cancel_order (checkout cancel)
_PAT_CANCEL_EXISTING = re.compile(
    r"\bcancel\s+(?:order|my\s+order)\s*#?\s*(\d{4,6})\b",
    re.IGNORECASE,
)

# Reject upsell — "no thanks", "not interested", "skip" during upsell
_PAT_REJECT_UPSELL = re.compile(
    r"^(no+\s*thanks?|not?\s*interested|skip|pass|nah|i'?m\s+good|no\s+need|don'?t\s+want\s+it|i'?m\s+fine)\s*[.!]*$",
    re.IGNORECASE,
)

# Gap 5: Retry intent
_PAT_RETRY = re.compile(r"^(retry|try\s+again|repeat\s+last\s+attempt)\b", re.IGNORECASE)

# Gap 6: Ambiguous Selection (1, 2, 3 or Option 1, Option 2)
_PAT_SELECTION = re.compile(r"^(?:option\s+)?([123])$", re.IGNORECASE)

# Gap 4: Relative Quantity ("2 more", "make it 5")
_PAT_QTY_RELATIVE = re.compile(r"\b(\d+)\s+more\b", re.IGNORECASE)
_PAT_QTY_ABSOLUTE = re.compile(r"\b(?:make\s+it|set\s+to|change\s+to)\s+(\d+)\b", re.IGNORECASE)

# Bug 10 / Gap 8: Words that should never trigger an add_item fallback
_CONVERSATIONAL = {
    "ok", "yes", "no", "hi", "hey", "hello", "bye", "thanks", "thank",
    "sure", "okay", "fine", "good", "great", "nice", "cool", "wow",
    "how", "why", "what", "when", "where", "who", "can", "may",
    "jack", "john", "mike", "raj", "sam", "alex", "im", "am",
}



# ═══════════════════════════════════════════════════════════════════════════════
# IntentEngine v3
# ═══════════════════════════════════════════════════════════════════════════════

class IntentEngine:
    """
    Rule-based intent classifier with understanding score.
    Priority order: status > cart > clear_cart > confirm > cancel > (shopping intents)
    """

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text: return ""
        n = text.lower().strip()
        n = re.sub(r"[?.,!]", " ", n)
        # Gap 8: Expanded common typos and informal text
        EXTRA_ALIASES = {
            "biriyani": "biryani", "briyani": "biryani", "biryni": "biryani",
            "coke": "cola", "pepsi": "cola", "wat": "what", "u": "you",
            "bhai": "", "da": "", "bro": "", "ek": "1", "do": "2", "teen": "3"
        }
        tokens = n.split()
        aliased_tokens = [EXTRA_ALIASES.get(t, t) for t in tokens]
        n = " ".join(aliased_tokens).strip()
        return " ".join(n.split())

    def classify(self, text: str, session_state: str = "", business_category: str = "") -> Intent:
        text = self.normalize_text(text)
        entities: dict[str, Any] = {}
        low = text.lower()

        # Gap 4: Determine quantity mode
        qty_mode = "set"
        if _PAT_QTY_RELATIVE.search(low):
            qty_mode = "add"
        entities["qty_mode"] = qty_mode

        # Always extract optional entities
        qty = extract_quantity(text)
        if qty is not None:
            entities["quantity"] = qty

        budget = extract_budget(text)
        if budget is not None:
            entities["budget"] = budget

        group_size = extract_group_size(text)
        if group_size is not None:
            entities["group_size"] = group_size

        spice = extract_spice_preference(text)
        if spice:
            entities["spice_level"] = spice

        veg = extract_veg_preference(text)
        if veg:
            entities["veg_preference"] = veg

        # ── Unrelated domain check (always first) ─────────────────────────────
        if is_unrelated(text, business_category):
            return self._make("unrelated_item", 0.92, entities, text, score=88)

        # ── Pending YES/NO state — highest priority gate ──────────────────────
        if session_state == "awaiting_yes_no":
            if _PAT_CONFIRM_BARE.match(low):
                return self._make("pending_yes", 0.97, entities, text, score=95)
            if _PAT_CANCEL.match(low) or _PAT_REJECT_UPSELL.match(low):
                return self._make("pending_no", 0.95, entities, text, score=90)
            return self._make("pending_unclear", 0.50, entities, text, score=30)

        # ── Pending Address state — highest priority gate ──────────────────────
        if session_state == "awaiting_address":
            entities["address"] = text
            return self._make("provide_address", 0.99, entities, text, score=100)

        # ── PRIORITY 0a: Name/Identity detection (Bug 4 — NEVER treat as product) ──
        name_match = _PAT_NAME_UPDATE.match(text.strip())
        if name_match:
            entities["customer_name"] = name_match.group(1).strip()
            return self._make("user_name_update", 0.97, entities, text, score=95)

        # ── PRIORITY 0b: Cancel existing order by ID (Bug 5) ─────────────────
        cancel_match = _PAT_CANCEL_EXISTING.search(low)
        if cancel_match:
            entities["order_number"] = cancel_match.group(1)
            return self._make("cancel_existing_order", 0.96, entities, text, score=92)

        # Gap 5: Retry handler
        if _PAT_RETRY.match(low):
            return self._make("retry_order", 0.98, entities, text, score=95)

        # Gap 6: Selection handler
        sel_match = _PAT_SELECTION.match(low)
        if sel_match and session_state == "awaiting_clarification":
            entities["selection_index"] = int(sel_match.group(1))
            return self._make("ambiguous_selection", 0.99, entities, text, score=100)

        # ── PRIORITY 0: Greeting (before everything — typos like helloo) ─────
        if _PAT_GREETING.match(low):
            return self._make("greet", 0.97, entities, text, score=90)

        # ── PRIORITY 1: Stock check (Bug 3/6 — "do you have X?" is NOT add_item) ──
        if _PAT_STOCK_CHECK.search(low):
            hint = re.sub(_PAT_STOCK_CHECK, "", low).strip()
            hint = re.sub(r"[?.,!]+", "", hint).strip()
            entities["item_hint"] = hint if hint else text
            return self._make("stock_check", 0.94, entities, text, score=90)

        if _PAT_INQUIRE.search(low) or (session_state == "shopping" and low in ("1", "inquire", "1. inquire", "type inquire", "1️⃣")):
            hint = re.sub(_PAT_INQUIRE, "", low).strip()
            entities["item_hint"] = hint
            return self._make("inquire_product", 0.95, entities, text, score=95)

        # ── PRIORITY 1: Menu (strict — before any product matching) ──────────
        if _PAT_MENU.search(low):
            return self._make("view_menu", 0.95, entities, text, score=88)

        # ── PRIORITY 2: Checkout start (NEVER treat as add_item) ─────────────
        if _PAT_CHECKOUT.search(low):
            return self._make("checkout_start", 0.96, entities, text, score=92)

        # ── Service Businesses / Booking ──────────────────────────────────────
        if _PAT_SERVICE_BOOKING.search(low):
            # Try to extract the requested service
            service = extract_item_hint(text, _PAT_SERVICE_BOOKING)
            entities["service"] = service
            return self._make("service_booking", 0.90, entities, text, score=90)

        # ── Product Info (Change 2) ──────────────────────────────────────────
        if _PAT_PRODUCT_INFO.search(low):
            hint = extract_item_hint(text, _PAT_PRODUCT_INFO).strip()
            hint = re.sub(r"^(the|a|an)\s+", "", hint, flags=re.I)
            entities["item_hint"] = hint
            return self._make("product_info", 0.9, entities, text, score=90)

        # ── PRIORITY 2: Core intents (Status, Clear Cart) ──────────────────────────────────────────
        if _PAT_ORDER_STATUS.search(low):
            # extract numeric order id if present
            m_id = re.search(r"\border\s+(\d{4,6})\b", low)
            if m_id:
                entities["order_number"] = m_id.group(1)
            return self._make("order_status", 0.95, entities, text, score=90)

        # ── Multi-item parse ─────────────────────────────────────────────────
        multi = parse_multi_items(text)
        # Trigger multi-add when 2+ distinct items OR 'with' separator found
        if multi and (len(multi) >= 2 or "with" in text.split()):
            entities["multi_items"] = multi
            return self._make("multi_add_items", 0.90, entities, text,
                              score=self._score(0.90, len(entities), text))

        # ── PRIORITY 2: Clear cart (before cart_view — both contain 'cart') ────
        if _PAT_CLEAR_CART.search(low):
            return self._make("clear_cart", 0.92, entities, text, score=88)

        # ── PRIORITY 3: Cart view ─────────────────────────────────────────────
        if _PAT_CART_VIEW.search(low):
            return self._make("show_cart", 0.92, entities, text, score=88)

        # ── State-aware overrides ────────────────────────────────────────────

        if session_state == "awaiting_address" and len(text) >= 1:
            entities["address_text"] = text
            return self._make(
                "provide_address", 0.90, entities, text,
                score=self._score(0.90, len(entities), text),
            )

        if session_state == "awaiting_confirmation":
            # YES + extra text = modify, not confirm
            yes_extra = _PAT_YES_PREFIX.match(text)
            if yes_extra:
                extra = yes_extra.group(2).strip()
                entities["modification_text"] = extra
                return self._make("yes_with_modification", 0.88, entities, text, score=80)
            if _PAT_CONFIRM_BARE.match(low):
                return self._make("confirm_order", 0.97, entities, text, score=95)
            if _PAT_CANCEL.match(low):
                return self._make("cancel_order", 0.95, entities, text, score=90)
            if _PAT_EDIT_CART.search(low):
                return self._make("edit_cart", 0.85, entities, text, score=80)
            return self._make("unclear_in_confirmation", 0.60, entities, text, score=40)

        if session_state == "awaiting_delivery_mode":
            if _PAT_DELIVERY.search(low):
                return self._make("select_delivery", 0.92, entities, text, score=88)
            if _PAT_PICKUP.search(low):
                return self._make("select_pickup", 0.92, entities, text, score=88)

        if session_state == "awaiting_clear_confirm":
            if _PAT_CONFIRM_BARE.match(low):
                return self._make("clear_cart_confirmed", 0.97, entities, text, score=95)
            if _PAT_CANCEL.match(low):
                return self._make("cancel_order", 0.90, entities, text, score=85)

        # ── Deterministic rules ──────────────────────────────────────────────

        if _PAT_GREETING.match(low):
            return self._make("greet", 0.95, entities, text, score=85)

        if _PAT_GOODBYE.search(low):
            return self._make("goodbye", 0.90, entities, text, score=80)

        if _PAT_COMPLAINT.search(low):
            return self._make("complaint", 0.88, entities, text, score=78)

        if _PAT_REPEAT.search(low):
            return self._make("repeat_last_order", 0.92, entities, text, score=88)

        if _PAT_CONFIRM_BARE.match(low):
            return self._make("confirm_order", 0.85, entities, text, score=75)

        if _PAT_CANCEL.match(low):
            return self._make("cancel_order", 0.85, entities, text, score=75)

        if _PAT_CHANGE_ADDR.search(low):
            return self._make("change_address", 0.88, entities, text, score=82)

        # Bug 4: negation (dont need wings) → remove_item
        if _PAT_NEGATE.search(low):
            hint = extract_item_hint(text, _PAT_NEGATE)
            entities["item_hint"] = hint if hint else text
            return self._make("remove_item", 0.90, entities, text,
                              score=self._score(0.90, len(entities), text))

        if _PAT_REMOVE.search(low):
            hint = extract_item_hint(text, _PAT_REMOVE_TRIGGER)
            entities["item_hint"] = hint
            return self._make("remove_item", 0.88, entities, text,
                              score=self._score(0.88, len(entities), text))

        if _PAT_CHANGE_QTY.search(low) and qty is not None and not _PAT_ADD.search(low):
            return self._make("change_quantity", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        if _PAT_GROUP_MEAL.search(low):
            return self._make("group_meal_request", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        if budget is not None and not _PAT_ADD.search(low):
            return self._make("budget_request", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        if _PAT_SPICE.search(low) and not _PAT_ADD.search(low) and not _PAT_REMOVE.search(low):
            return self._make("set_preference", 0.82, entities, text,
                              score=self._score(0.82, len(entities), text))

        if _PAT_DELIVERY.search(low):
            return self._make("select_delivery", 0.90, entities, text, score=85)

        if _PAT_PICKUP.search(low):
            return self._make("select_pickup", 0.90, entities, text, score=85)

        if _PAT_ADDRESS.search(low) and session_state in ("", "awaiting_address", "shopping"):
            entities["address_text"] = text
            return self._make("provide_address", 0.80, entities, text,
                              score=self._score(0.80, len(entities), text))

        if _PAT_PRICE.search(low):
            item_hint = re.sub(
                r"\b(price|cost|rate|how\s+much|charges?|fee|amount|rs\.?|₹)\b",
                "", low, flags=re.IGNORECASE,
            ).strip()
            entities["item_hint"] = item_hint
            return self._make("ask_price", 0.88, entities, text,
                              score=self._score(0.88, len(entities), text))

        # (menu already handled at top priority — this line is a safety net)

        if _PAT_RECOMMEND.search(low):
            return self._make("ask_recommendation", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        if _PAT_HELP.search(low):
            return self._make("ask_help", 0.85, entities, text, score=75)

        if _PAT_VAGUE_HUNGER.search(low):
            return self._make("vague_request", 0.70, entities, text,
                              score=self._score(0.70, len(entities), text))

        if _PAT_ADD.search(low):
            hint = extract_item_hint(text, _PAT_ADD_TRIGGER)
            entities["item_hint"] = hint
            return self._make("add_item", 0.80, entities, text,
                              score=self._score(0.80, len(entities), text))

        kw = _keywords(low)
        all_domain_kws = set().union(*_DOMAIN_KEYWORDS.values())
        
        if qty is not None and len(text.split()) <= 6:
            # Gap 8: Only treat as add_item if there's a domain-relevant word
            if any(k for k in kw if k in all_domain_kws):
                entities["item_hint"] = low
                return self._make("add_item", 0.60, entities, text,
                                  score=self._score(0.60, len(entities), text))

        product_kw = {k for k in kw if k not in _CONVERSATIONAL and len(k) >= 3}
        
        # Gap 8 fix: Only fallback to add_item if at least one keyword is domain-relevant
        all_domain_kws = set().union(*_DOMAIN_KEYWORDS.values())
        is_domain_relevant = any(k in all_domain_kws for k in product_kw)

        if is_domain_relevant and len(text) >= 3 and len(text.split()) <= 5:
            entities["item_hint"] = text
            return self._make("add_item", 0.45, entities, text, score=30)

        # Gap 8 fix: If unrecognizable, offer menu/browsing instead of auto-adding.
        return self._make("unrecognizable_fallback", 0.10, entities, text, score=5)

    # ── Understanding score ───────────────────────────────────────────────────

    @staticmethod
    def _score(confidence: float, entity_count: int, text: str) -> int:
        base = int(confidence * 50)
        entity_bonus = min(entity_count * 10, 30)
        length_bonus = min(len(text.split()) * 2, 15)
        return min(base + entity_bonus + length_bonus, 100)

    @staticmethod
    def _make(
        name: str,
        confidence: float,
        entities: dict,
        raw_text: str,
        score: int = 50,
    ) -> Intent:
        return Intent(
            name=name,
            confidence=confidence,
            entities=entities,
            raw_text=raw_text,
            understanding_score=score,
        )

    @staticmethod
    def extract_item_hint_tokens(hint: str) -> list[str]:
        tokens = _tokenize(hint)
        return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
