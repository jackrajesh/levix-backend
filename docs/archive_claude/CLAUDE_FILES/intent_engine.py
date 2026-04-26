"""
intent_engine.py — LEVIX NLU Layer
Classifies customer messages and extracts structured entities
without relying on any external NLP libraries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    name: str                          # canonical intent label
    confidence: float                  # 0.0 – 1.0
    entities: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

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

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())

def _keywords(text: str) -> set[str]:
    return {t for t in _tokenize(text) if t not in _STOP_WORDS}


# ---------------------------------------------------------------------------
# Entity extractors
# ---------------------------------------------------------------------------

# Written-out numbers → int
_WORD_NUMS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "a": 1, "an": 1,
}


def extract_quantity(text: str) -> int | None:
    """Return first explicit quantity found, or None."""
    # digit form: "2 biryani", "add 3"
    m = re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))
    # word form: "two biryanis"
    for word, val in _WORD_NUMS.items():
        if re.search(rf"\b{word}\b", text.lower()):
            return val
    return None


def extract_budget(text: str) -> int | None:
    """Return numeric budget if present, e.g. 'under 700' → 700."""
    m = re.search(r"(?:under|below|within|max|less than|upto|up to)\s*(?:rs\.?|₹)?\s*(\d+)", text.lower())
    if m:
        return int(m.group(1))
    # bare "700" after budget-trigger words
    m2 = re.search(r"(?:rs\.?|₹)\s*(\d+)", text.lower())
    if m2:
        return int(m2.group(1))
    return None


def extract_group_size(text: str) -> int | None:
    """Return group size: 'dinner for 5' → 5."""
    m = re.search(r"(?:for|feed|serves?|people|persons?|pax)\s*(\d+)", text.lower())
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d+)\s*(?:people|persons?|pax|guests?)", text.lower())
    if m2:
        return int(m2.group(1))
    return None


def extract_spice_preference(text: str) -> str | None:
    low = text.lower()
    if re.search(r"\b(less spic|mild|not spic|no spic|low spic)\w*", low):
        return "mild"
    if re.search(r"\b(extra spic|very spic|more spic|hot)\w*", low):
        return "extra_spicy"
    if re.search(r"\b(medium spic|normal spic|regular spic)\w*", low):
        return "medium"
    return None


# ---------------------------------------------------------------------------
# Pattern banks  (order matters — first match wins)
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|hola|howdy|good\s*(morning|afternoon|evening|night)|"
    r"what'?s up|sup|greetings|namaste|vanakkam|start|begin)\b",
    re.IGNORECASE,
)

_GOODBYE_PATTERNS = re.compile(
    r"\b(bye|goodbye|see you|later|cya|take care|that'?s all|nothing else|"
    r"thanks?\s*(that'?s all)?|no\s*thanks?)\b",
    re.IGNORECASE,
)

_PRICE_PATTERNS = re.compile(
    r"\b(price|cost|rate|how much|charges?|fee|amount|rs\.?|₹)\b",
    re.IGNORECASE,
)

_MENU_PATTERNS = re.compile(
    r"\b(menu|list|what.*have|what.*offer|show.*items?|catalogue|catalog|"
    r"available|options?|choices?|varieties?)\b",
    re.IGNORECASE,
)

_ADD_PATTERNS = re.compile(
    r"\b(add|want|order|get|give|bring|need|take|include|put)\b",
    re.IGNORECASE,
)

_REMOVE_PATTERNS = re.compile(
    r"\b(remove|cancel|delete|drop|no more|don'?t want|skip|exclude|without)\b",
    re.IGNORECASE,
)

_CHANGE_QTY_PATTERNS = re.compile(
    r"\b(make it|change.*to|update.*to|set.*to|actually|instead|modify|"
    r"quantity|qty|increase|decrease|reduce|more|less)\b",
    re.IGNORECASE,
)

_DELIVERY_PATTERNS = re.compile(
    r"\b(deliver|delivery|home\s*delivery|send.*to|drop.*at|bring.*to|shipping)\b",
    re.IGNORECASE,
)

_PICKUP_PATTERNS = re.compile(
    r"\b(pick\s*up|pickup|self\s*collect|collect|take\s*away|takeaway|"
    r"i'?ll\s*come|come.*shop|come.*store)\b",
    re.IGNORECASE,
)

_ADDRESS_PATTERNS = re.compile(
    r"\b(address|location|where|flat|door|house|no\.?|number|street|road|"
    r"lane|nagar|colony|area|city|pin\s*code|zip)\b",
    re.IGNORECASE,
)

_CONFIRM_PATTERNS = re.compile(
    r"^(yes|yeah|yep|yup|sure|ok|okay|confirm|correct|right|absolutely|"
    r"go ahead|place.*order|proceed|done|finalize|sounds good)\b",
    re.IGNORECASE,
)

_CANCEL_PATTERNS = re.compile(
    r"^(no|nope|nah|cancel|stop|reset|clear|start over|nevermind|never mind|"
    r"forget it|don'?t|abort)\b",
    re.IGNORECASE,
)

_VIEW_CART_PATTERNS = re.compile(
    r"\b(cart|basket|my order|what.*ordered|show.*cart|current order|"
    r"what.*added|review.*order)\b",
    re.IGNORECASE,
)

_REPEAT_ORDER_PATTERNS = re.compile(
    r"\b(same as last|repeat.*order|previous.*order|last.*order|"
    r"order again|reorder|usual)\b",
    re.IGNORECASE,
)

_RECOMMENDATION_PATTERNS = re.compile(
    r"\b(suggest|recommend|what.*good|best|popular|special|top|"
    r"favourite|favorite|what.*try|anything.*good)\b",
    re.IGNORECASE,
)

_HELP_PATTERNS = re.compile(
    r"\b(help|support|assist|how.*work|how.*order|guide|confused|"
    r"don'?t understand|not sure|what.*do)\b",
    re.IGNORECASE,
)

_SPICE_PATTERNS = re.compile(
    r"\b(spic|mild|hot|medium|extra|less\s+spic|more\s+spic)\w*\b",
    re.IGNORECASE,
)

_GROUP_MEAL_PATTERNS = re.compile(
    r"\b(dinner|lunch|breakfast|meal|food|party|family|event)\b.*\bfor\b.*\d+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

class IntentEngine:
    """
    Rule-based intent classifier.
    Returns the most specific Intent for a customer message.
    """

    def classify(self, text: str, session_state: str = "") -> Intent:
        """
        Classify *text* given optional *session_state* for context
        (e.g. 'awaiting_address', 'awaiting_confirm').
        """
        text = text.strip()
        entities: dict[str, Any] = {}
        low = text.lower()

        # Always extract optional entities
        qty = extract_quantity(text)
        if qty is not None:
            entities["quantity"] = qty

        budget = extract_budget(text)
        if budget is not None:
            entities["budget"] = budget

        group = extract_group_size(text)
        if group is not None:
            entities["group_size"] = group

        spice = extract_spice_preference(text)
        if spice:
            entities["spice_level"] = spice

        # --- State-aware overrides ---
        if session_state == "awaiting_address" and len(text) > 6:
            # anything typed at this state is likely an address
            entities["address_text"] = text
            return Intent("provide_address", 0.85, entities, text)

        if session_state == "awaiting_confirm":
            if _CONFIRM_PATTERNS.search(low):
                return Intent("confirm_order", 0.95, entities, text)
            if _CANCEL_PATTERNS.search(low):
                return Intent("cancel_order", 0.90, entities, text)

        # --- Deterministic rules (ordered by specificity) ---

        if _GREETING_PATTERNS.match(low):
            return Intent("greet", 0.95, entities, text)

        if _GOODBYE_PATTERNS.search(low):
            return Intent("goodbye", 0.90, entities, text)

        if _REPEAT_ORDER_PATTERNS.search(low):
            return Intent("repeat_last_order", 0.92, entities, text)

        if _VIEW_CART_PATTERNS.search(low):
            return Intent("view_cart", 0.90, entities, text)

        if _CONFIRM_PATTERNS.match(low):
            return Intent("confirm_order", 0.88, entities, text)

        if _CANCEL_PATTERNS.match(low):
            return Intent("cancel_order", 0.88, entities, text)

        if _REMOVE_PATTERNS.search(low):
            # extract item name: everything after the trigger verb
            m = re.search(
                r"\b(?:remove|cancel|delete|drop|skip|exclude)\b\s*(.*)",
                low,
            )
            if m:
                entities["item_hint"] = m.group(1).strip()
            return Intent("remove_item", 0.88, entities, text)

        # "make it 3" / "change quantity" — must come BEFORE add_item
        if _CHANGE_QTY_PATTERNS.search(low) and qty is not None and not _ADD_PATTERNS.search(low):
            return Intent("change_quantity", 0.85, entities, text)

        # Spice preference without add/remove context
        if _SPICE_PATTERNS.search(low) and not _ADD_PATTERNS.search(low):
            return Intent("set_preference", 0.82, entities, text)

        if _DELIVERY_PATTERNS.search(low):
            return Intent("select_delivery", 0.90, entities, text)

        if _PICKUP_PATTERNS.search(low):
            return Intent("select_pickup", 0.90, entities, text)

        if _ADDRESS_PATTERNS.search(low) and session_state in ("", "awaiting_address"):
            entities["address_text"] = text
            return Intent("provide_address", 0.80, entities, text)

        if _GROUP_MEAL_PATTERNS.search(low):
            return Intent("group_meal_request", 0.85, entities, text)

        if _PRICE_PATTERNS.search(low):
            # item name: strip price keywords
            item_hint = re.sub(
                r"\b(price|cost|rate|how much|charges?|fee|amount|rs\.?|₹)\b",
                "", low, flags=re.IGNORECASE,
            ).strip()
            entities["item_hint"] = item_hint
            return Intent("ask_price", 0.88, entities, text)

        if _MENU_PATTERNS.search(low):
            return Intent("view_menu", 0.88, entities, text)

        if _RECOMMENDATION_PATTERNS.search(low):
            return Intent("ask_recommendation", 0.85, entities, text)

        if _HELP_PATTERNS.search(low):
            return Intent("ask_help", 0.85, entities, text)

        if _ADD_PATTERNS.search(low):
            # extract item hint: text after the trigger verb
            m = re.search(
                r"\b(?:add|want|order|get|give|bring|need|take|include|put)\b\s*(.*)",
                low,
            )
            if m:
                entities["item_hint"] = m.group(1).strip()
            return Intent("add_item", 0.80, entities, text)

        # Fallback: treat as add if there's a quantity and no other signal
        if qty is not None:
            entities["item_hint"] = low
            return Intent("add_item", 0.60, entities, text)

        return Intent("unknown", 0.40, entities, text)

    def extract_item_hint_tokens(self, hint: str) -> list[str]:
        """
        Return meaningful tokens from a raw item hint string.
        Used by order_engine to fuzzy-match against DB product names.
        """
        tokens = _tokenize(hint)
        return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
