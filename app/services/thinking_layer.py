import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("levix.thinking")

# FAIL 4.3 / 6.5: Expanded variant trigger patterns
_VARIANT_TRIGGERS = [
    "which size", "what size", "how many ml", "how much ml",
    "how many litre", "how much litre", "what capacity",
    "how big", "how large", "what weight", "how many gram",
    "what volume", "how tall", "dimensions",
]

@dataclass
class AnalysisResult:
    primary_intent: Optional[str] = None
    confidence: float = 0.0
    entities: dict = field(default_factory=dict)
    context_note: str = ""

class ThinkingLayer:
    """
    Pre-processor that runs BEFORE intent classification to understand context.
    """

    @classmethod
    def analyze(cls, message: str, session_state: str, cart: list, history: list) -> AnalysisResult:
        low = message.lower().strip()
        print(f"[THINKING] analyzing message='{low}' state='{session_state}'")
        result = AnalysisResult()

        # Rule 3: Frustration detection
        frustration_pat = re.compile(r"^(no{2,}|why\?*|whyy+|ugh+|wtf|\?{2,}|this is wrong|no means.*)$", re.IGNORECASE)
        if frustration_pat.search(low):
            result.primary_intent = "frustration"
            result.confidence = 0.95
            result.context_note = "User is frustrated"
            return result

        # FAIL 4.3 / 6.5: Size/variant question detection — expanded patterns
        for trigger in _VARIANT_TRIGGERS:
            if trigger in low:
                result.primary_intent = "product_info"
                result.confidence = 0.95
                result.entities["variant_query"] = True
                result.entities["sub_type"] = "variant_query"
                result.entities["focus"] = "size_capacity"
                
                # Extract item hint by removing the trigger
                item_hint = low.replace(trigger, "").strip()
                # Clean up common fillers
                item_hint = re.sub(r"\b(do you have|of|for|the|about)\b", "", item_hint).strip()
                if item_hint:
                    result.entities["item_hint"] = item_hint
                
                result.context_note = f"Querying for size/variant of {item_hint}"
                return result

        # Rule 1: Read last messages for context
        last_bot_msg = ""
        for turn in reversed(history):
            if turn.get("role") == "assistant":
                last_bot_msg = turn.get("content", "").lower()
                break

        # Context-aware 'no' handling
        no_phrases = ["no thanks", "no thank you", "nope", "not now", "noo", "nooo", "never mind", "cancel"]
        rest = None
        if low in no_phrases or low == "no":
            rest = ""
        else:
            no_match = re.match(r"^no\b\s*(.*)", low)
            if no_match:
                rest = no_match.group(1).strip()

        if rest is not None:

            if rest == "":
                result.primary_intent = "reject"
                result.confidence = 0.95
                
                # FAIL 2.5: awaiting_clear_confirm state — must run FIRST
                if session_state == "awaiting_clear_confirm":
                    result.primary_intent = "reject_clear"
                    result.confidence = 0.98
                    result.context_note = "Do not clear cart"
                return result
            
            # If there's more text after "no", strip it and let the standard classifier run on the rest
            if rest:
                result.primary_intent = "strip_no_and_reprocess"
                result.entities["stripped_message"] = rest
                result.confidence = 0.99
                return result

            # FAIL 6.2: Upsell rejection — detect from last bot message
            upsell_keywords = (
                "customers also love", "how about", "want to add",
                "instead", "also try", "upsell"
            )
            if any(kw in last_bot_msg for kw in upsell_keywords):
                result.primary_intent = "reject_upsell"
                result.confidence = 0.95
                return result
                
            if session_state == "awaiting_confirmation":
                result.primary_intent = "cancel_order"
                result.confidence = 0.95
                return result

            if session_state == "awaiting_inquiry_confirmation":
                result.primary_intent = "cancel_inquiry"
                result.confidence = 0.95
                return result

            # FAIL 4.5: awaiting_inquiry_or_menu state — menu option
            if session_state == "awaiting_inquiry_or_menu":
                result.primary_intent = "inquiry_menu_choice"
                result.entities["choice"] = "menu"
                result.confidence = 0.95
                return result
                
            if session_state in ("shopping", "cart_active", "idle", "browsing"):
                result.primary_intent = "no_problem"
                result.confidence = 0.90
                return result

        # Context-aware 'yes' handling
        if low == "yes":
            # If the state is awaiting_yes_no, we usually let the handler handle it, 
            # but we can force specific intents here if needed.
            pass

        # Rule 2: Message length heuristic
        words = low.split()
        if len(words) == 1 and not cart and session_state == "shopping":
            # Just a word, empty cart -> likely product search
            pass

        return result
