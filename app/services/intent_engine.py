"""
intent_engine.py — LEVIX NLU Layer  (v2 — full production rewrite)
====================================================================
Classifies customer messages and extracts structured entities
without relying on any external NLP libraries.

v2 improvements over v1:
- Understanding score (0-100) based on confidence + entity richness + context
- Vague-intent detection (hungry, something nice, etc.)
- Complaint detection
- Veg/non-veg extraction
- Improved quantity extraction (handles "half dozen", ordinal edge cases)
- Context-aware overrides are properly ordered
- All extractors return typed Optional values
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


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


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _keywords(text: str) -> set[str]:
    return {t for t in _tokenize(text) if t not in _STOP_WORDS}


# ─── Entity extractors ────────────────────────────────────────────────────────

_WORD_NUMS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "half a dozen": 6, "a dozen": 12, "dozen": 12,
}


def extract_quantity(text: str) -> Optional[int]:
    """Return first explicit quantity found, or None."""
    low = text.lower()
    # digit form: "2 biryani", "add 3"
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 999:   # sanity gate
            return val
    # word form: "two biryanis"
    for phrase, val in sorted(_WORD_NUMS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", low):
            return val
    return None


def extract_budget(text: str) -> Optional[float]:
    """Return numeric budget if present, e.g. 'under 700' → 700.0"""
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
    """Return group/person count: 'dinner for 5' → 5"""
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
    """
    Extract the item name from text after a trigger verb.
    Returns the stripped remainder, or the full text as fallback.
    """
    m = trigger_pattern.search(text.lower())
    if m:
        after = text[m.end():].strip()
        return after if after else text
    return text


# ─── Pattern banks ────────────────────────────────────────────────────────────

_PAT_GREETING = re.compile(
    r"^(hi|hello|hey|hola|howdy|good\s*(morning|afternoon|evening|night)|"
    r"what'?s\s*up|sup|greetings|namaste|vanakkam|start|begin|yo)\b",
    re.IGNORECASE,
)
_PAT_GOODBYE = re.compile(
    r"\b(bye|goodbye|see\s+you|later|cya|take\s+care|that'?s\s+all|nothing\s+else|"
    r"thanks?\s*(that'?s\s+all)?|no\s*thanks?|done\s+for\s+now|all\s+good)\b",
    re.IGNORECASE,
)
_PAT_CONFIRM = re.compile(
    r"^(yes|yeah|yep|yup|yah|sure|ok|okay|k|confirm|correct|right|absolutely|"
    r"go\s+ahead|place.*order|proceed|done|finalize|sounds\s+good|haan|ha)\b",
    re.IGNORECASE,
)
_PAT_CANCEL = re.compile(
    r"^(no|nope|nah|cancel|stop|reset|clear|start\s+over|nevermind|never\s+mind|"
    r"forget\s+it|don'?t|abort|scratch\s+that)\b",
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
    r"\b(remove|cancel|delete|drop|no\s+more|don'?t\s+want|skip|exclude|without|take\s+off|take\s+out)\b",
    re.IGNORECASE,
)
_PAT_REMOVE_TRIGGER = re.compile(
    r"\b(?:remove|cancel|delete|drop|skip|exclude|take\s+off)\b",
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
_PAT_VIEW_CART = re.compile(
    r"\b(cart|basket|my\s+order|what.*ordered|show.*cart|current\s+order|"
    r"what.*added|review.*order|see.*cart)\b",
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
_PAT_MENU = re.compile(
    r"\b(menu|list|what.*have|what.*offer|show.*items?|catalogue|catalog|"
    r"available|options?|choices?|varieties?|show\s+me)\b",
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


# ═══════════════════════════════════════════════════════════════════════════════
# IntentEngine
# ═══════════════════════════════════════════════════════════════════════════════

class IntentEngine:
    """
    Rule-based intent classifier with understanding score.
    Returns the most specific Intent for a customer message.
    """

    def classify(self, text: str, session_state: str = "") -> Intent:
        """
        Classify `text` given optional `session_state` for context.
        session_state values: idle, shopping, cart_active, awaiting_delivery_mode,
                              awaiting_address, awaiting_confirmation, completed
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

        group_size = extract_group_size(text)
        if group_size is not None:
            entities["group_size"] = group_size

        spice = extract_spice_preference(text)
        if spice:
            entities["spice_level"] = spice

        veg = extract_veg_preference(text)
        if veg:
            entities["veg_preference"] = veg

        # ── State-aware overrides (highest priority) ─────────────────────────

        if session_state == "awaiting_address" and len(text) >= 1:
            entities["address_text"] = text
            return self._make(
                "provide_address", 0.90, entities, text,
                score=self._score(0.90, len(entities), text)
            )

        if session_state == "awaiting_confirmation":
            if _PAT_CONFIRM.search(low):
                return self._make("confirm_order", 0.95, entities, text, score=90)
            if _PAT_CANCEL.search(low):
                return self._make("cancel_order", 0.92, entities, text, score=88)
            if _PAT_EDIT_CART.search(low):
                return self._make("edit_cart", 0.85, entities, text, score=80)
            # Non-yes/no in confirmation state
            return self._make("unclear_in_confirmation", 0.60, entities, text, score=40)

        if session_state == "awaiting_delivery_mode":
            if _PAT_DELIVERY.search(low):
                return self._make("select_delivery", 0.92, entities, text, score=88)
            if _PAT_PICKUP.search(low):
                return self._make("select_pickup", 0.92, entities, text, score=88)

        # ── Deterministic rules (ordered by specificity) ─────────────────────

        if _PAT_GREETING.match(low):
            return self._make("greet", 0.95, entities, text, score=85)

        if _PAT_GOODBYE.search(low):
            return self._make("goodbye", 0.90, entities, text, score=80)

        if _PAT_COMPLAINT.search(low):
            return self._make("complaint", 0.88, entities, text, score=78)

        if _PAT_REPEAT.search(low):
            return self._make("repeat_last_order", 0.92, entities, text, score=88)

        if _PAT_VIEW_CART.search(low):
            return self._make("show_cart", 0.90, entities, text, score=85)

        if _PAT_CONFIRM.match(low):
            return self._make("confirm_order", 0.85, entities, text, score=75)

        if _PAT_CANCEL.match(low):
            return self._make("cancel_order", 0.85, entities, text, score=75)

        if _PAT_CHANGE_ADDR.search(low):
            return self._make("change_address", 0.88, entities, text, score=82)

        if _PAT_REMOVE.search(low):
            hint = extract_item_hint(text, _PAT_REMOVE_TRIGGER)
            entities["item_hint"] = hint
            return self._make("remove_item", 0.88, entities, text,
                              score=self._score(0.88, len(entities), text))

        # "make it 3" / quantity change — before add_item to avoid misfire
        if _PAT_CHANGE_QTY.search(low) and qty is not None and not _PAT_ADD.search(low):
            return self._make("change_quantity", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        # Group meal with count
        if _PAT_GROUP_MEAL.search(low):
            return self._make("group_meal_request", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        # Budget query: "under 500", "around 300"
        if budget is not None and not _PAT_ADD.search(low):
            return self._make("budget_request", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        # Spice preference alone
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

        if _PAT_MENU.search(low):
            return self._make("view_menu", 0.88, entities, text, score=80)

        if _PAT_RECOMMEND.search(low):
            return self._make("ask_recommendation", 0.85, entities, text,
                              score=self._score(0.85, len(entities), text))

        if _PAT_HELP.search(low):
            return self._make("ask_help", 0.85, entities, text, score=75)

        # Vague hunger / open-ended requests
        if _PAT_VAGUE_HUNGER.search(low):
            return self._make("vague_request", 0.70, entities, text,
                              score=self._score(0.70, len(entities), text))

        if _PAT_ADD.search(low):
            hint = extract_item_hint(text, _PAT_ADD_TRIGGER)
            entities["item_hint"] = hint
            return self._make("add_item", 0.80, entities, text,
                              score=self._score(0.80, len(entities), text))

        # Fallback: bare quantity implies ordering
        if qty is not None:
            entities["item_hint"] = low
            return self._make("add_item", 0.60, entities, text,
                              score=self._score(0.60, len(entities), text))

        # Pure product name guess (4+ chars, no stop words)
        kw = _keywords(low)
        if len(kw) >= 1 and len(text) >= 3:
            entities["item_hint"] = text
            return self._make("add_item", 0.45, entities, text, score=30)

        return self._make("unknown", 0.30, entities, text, score=15)

    # ── Understanding score ───────────────────────────────────────────────────

    @staticmethod
    def _score(confidence: float, entity_count: int, text: str) -> int:
        """
        Compute a 0-100 understanding score.

        Formula:
        - Base: confidence × 50
        - Entity bonus: min(entity_count × 10, 30)
        - Length bonus: small bonus for non-trivial messages
        """
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

    # ── Token helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def extract_item_hint_tokens(hint: str) -> list[str]:
        """
        Return meaningful tokens from a raw item hint string.
        Used by order_engine to fuzzy-match against DB product names.
        """
        tokens = _tokenize(hint)
        return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
