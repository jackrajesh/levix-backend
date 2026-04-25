"""
hybrid_matcher.py  —  Levix S2 | Drop-in Hybrid Extraction + Matching
======================================================================
Place this file in:  app/services/hybrid_matcher.py

Usage in your route (webhooks.py or wherever handle_message lives):

    from .services.hybrid_matcher import hybrid_match_message

    result    = hybrid_match_message(message, db, shop.id)
    matched   = result["matched_products"]   # List[InventoryItem]
    unmatched = result["unmatched_terms"]    # List[str]
    pdata     = result["product_data"]       # plug into generate_human_reply()

This file:
  - Imports your existing functions exactly as they are
  - Does NOT rename or modify any existing function
  - Does NOT touch DB models, whatsapp_service.py, or ai_parser.py
  - Replaces only the match_multiple_products() call in your route
"""

import re
import logging
from typing import Optional, List, Dict, Tuple

from sqlalchemy.orm import Session

# ── Your existing imports (names unchanged) ───────────────────────────────────
from .product_service import (
    fuzzy_match_with_score,   # your existing: (query, db, shop_id) -> (item|None, float)
    get_product_status,       # your existing: (item) -> str
    normalize_product,        # your existing normalizer
    ALIAS_MAP,                # your existing alias map (briyani→biryani etc.)
)
from .ai_parser import (
    ai_extract_products,      # your existing: (message:str) -> List[str]|None
)
from .. import models

logger = logging.getLogger("levix.hybrid_matcher")


# ══════════════════════════════════════════════════════════════════════════════
# THRESHOLDS  —  change only here if you need to tune
# ══════════════════════════════════════════════════════════════════════════════

THRESHOLD_FULL_PHRASE  = 0.75   # whole cleaned message → instant return
THRESHOLD_AI_VALIDATED = 0.68   # AI term confirmed by your fuzzy function
THRESHOLD_FALLBACK     = 0.62   # system-only phrase fallback


# ══════════════════════════════════════════════════════════════════════════════
# FILLER WORDS  —  ONLY greetings/connectors, never food words
# ══════════════════════════════════════════════════════════════════════════════

FILLER_WORDS = {
    "hi", "hello", "hey", "bro", "anna", "da", "bhai", "sir", "madam",
    "please", "pls", "plz", "ok", "okay", "thanks", "thank", "you",
    "naan", "enaku", "venum", "vennum", "vendum", "kudunga", "kuduga",
    "send", "order", "want", "need", "get", "give", "enna", "yenna",
    "sollu", "poda", "po", "the", "a", "an", "i", "do", "does", "did",
    "have", "has", "had", "is", "are", "was", "were", "in", "your",
    "my", "me", "shop", "store", "available", "availability", "can",
    "will", "could", "would", "tell", "say", "know", "for", "any", "this",
    "that", "there", "some", "iruka", "iruku", "irukaa", "irukutha", "vachurkingala",
    "vachirkingala", "vachirukala", "vachirukingala"
}


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY SAFETY MAP
# "briyani" and "fried rice" are DIFFERENT categories → never cross-match
# ══════════════════════════════════════════════════════════════════════════════

CATEGORY_MAP: Dict[str, str] = {
    # Biryani
    "briyani": "biryani",  "biryani": "biryani",  "biriyani": "biryani",
    "biriani": "biryani",  "bryani":  "biryani",  "briyan":   "biryani",
    "biryan":  "biryani",

    # Fried Rice
    "fried rice":    "fried_rice",   "friedrice":      "fried_rice",
    "egg rice":      "fried_rice",   "veg rice":       "fried_rice",
    "schezwan rice": "fried_rice",

    # Noodles
    "noodle":  "noodles",  "noodles": "noodles",
    "noddle":  "noodles",  "noddles": "noodles",  "maggi": "noodles",

    # Chicken starters
    "chicken 65":        "chicken_starter",
    "chilli chicken":    "chicken_starter",
    "pepper chicken":    "chicken_starter",
    "chicken manchurian":"chicken_starter",

    # Parotta
    "parotta": "parotta",  "parrotta": "parotta",

    # Meals
    "meals": "meals",  "meal": "meals",  "sapad": "meals",  "lunch": "meals",

    # Drinks
    "tea": "drinks",    "chai":  "drinks",   "coffee": "drinks",
    "juice": "drinks",  "lassi": "drinks",   "milk":   "drinks",
    "paal": "drinks",   "cool drink": "drinks",
}


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_category(text: str) -> Optional[str]:
    t = text.lower().strip()
    for kw in sorted(CATEGORY_MAP, key=len, reverse=True):   # longest key first
        if kw in t:
            return CATEGORY_MAP[kw]
    return None


def _categories_conflict(query: str, product_name: str) -> bool:
    """Block match if query and product are in DIFFERENT known categories."""
    qc = _get_category(query)
    pc = _get_category(product_name)
    if qc is None or pc is None:
        return False
    return qc != pc


def _safe_fuzzy(
    query:     str,
    db:        Session,
    shop_id:   int,
    threshold: float,
) -> Tuple[Optional[models.InventoryItem], float]:
    """
    Calls YOUR existing fuzzy_match_with_score, then applies:
      1. Score threshold gate
      2. Category-conflict gate  (prevents biryani → fried rice etc.)
    """
    item, score = fuzzy_match_with_score(query, db, shop_id)

    if item is None or score < threshold:
        return None, 0.0

    if _categories_conflict(query, item.name):
        logger.warning(
            "[CATEGORY BLOCK] '%s' → '%s' (%.2f) blocked — category mismatch",
            query, item.name, score,
        )
        return None, 0.0

    return item, score


def _clean_tamil_suffixes(text: str) -> str:
    """Specialized cleaner for Tamil question suffixes to isolate the product name."""
    suffixes = [
        r"\biruka\b", r"\birukua\b", r"\biruku\b", r"\bvachurkingala\b",
        r"\bvachirukingala\b", r"\birukaa\b", r"\birugudha\b", r"\birukudha\b",
        r"\birruka\b", r"\birrukutha\b"
    ]
    for s in suffixes:
        text = re.sub(s, "", text, flags=re.IGNORECASE)
    return text.strip()


def _strip_filler(text: str) -> str:
    """Remove greeting/filler words and Tamil suffixes. Food words are NEVER removed."""
    # 1. Clean Tamil specific verbs first
    text = _clean_tamil_suffixes(text)
    
    # 2. Standard filler word removal
    return " ".join(
        t for t in text.split()
        if t.lower() not in FILLER_WORDS
    ).strip()


def _apply_aliases(text: str) -> str:
    """
    Apply your existing ALIAS_MAP:
      - Try whole phrase first
      - Then word-by-word
    """
    normed = normalize_product(text)
    if normed in ALIAS_MAP:
        return ALIAS_MAP[normed]
    tokens = normed.split()
    return " ".join(ALIAS_MAP.get(t, t) for t in tokens)


def _split_multi_product(message: str) -> List[str]:
    """
    Split "1 chicken biryani and 1 fried rice" → ["chicken biryani", "fried rice"]
    Handles: and / , / & / ; + leading quantities (1, 2x, x2)
    """
    text = re.sub(r"\band\b|[,;&/]", "|", message, flags=re.IGNORECASE)
    parts = [p.strip() for p in text.split("|") if p.strip()]

    cleaned: List[str] = []
    for part in parts:
        part = re.sub(r"^\d+\s*x?\s*", "", part, flags=re.IGNORECASE)
        part = re.sub(r"\s*x\s*\d+$",  "", part, flags=re.IGNORECASE)
        part = part.strip()
        if part:
            cleaned.append(part)

    return cleaned if cleaned else [message]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION  —  single call from your route
# ══════════════════════════════════════════════════════════════════════════════

def hybrid_match_message(
    raw_message: str,
    db:          Session,
    shop_id:     int,
    skip_ai:     bool = False,
) -> Dict:
    """
    AI-first (60%) + System validation (40%) pipeline.

    Returns:
    {
        "matched_products": List[InventoryItem],
        "unmatched_terms":  List[str],
        "confidence_map":   {item.id: float},
        "product_data":     [{"name":..., "price":..., "status":...}]
                            ↑ plug directly into generate_human_reply()
    }
    """
    matched_products: List[models.InventoryItem] = []
    unmatched_terms:  List[str]                  = []
    confidence_map:   Dict[int, float]           = {}
    seen_ids:         set                        = set()

    # ── Step 0: Basic clean (mirrors your normalize_message) ─────────────────
    msg = raw_message.lower().strip()
    msg = re.sub(r'[?!.]', ' ', msg)
    msg = " ".join(msg.split())

    # ── Step 1 & 2: Full phrase shortcut & Split detection ─────────────────────
    full_stripped = _strip_filler(msg)
    full_aliased  = _apply_aliases(full_stripped)
    phrase_parts = _split_multi_product(full_stripped)
    logger.debug("[PHRASE PARTS] %s", phrase_parts)

    # Only exit on full phrase if it's literally not a multi-product query
    if len(phrase_parts) <= 1:
        item, score = _safe_fuzzy(full_aliased, db, shop_id, THRESHOLD_FULL_PHRASE)
        if item and item.id not in seen_ids:
            logger.info("[FULL PHRASE HIT] '%s' → '%s' (%.2f)", full_aliased, item.name, score)
            seen_ids.add(item.id)
            confidence_map[item.id] = score
            matched_products.append(item)
            return _build_result(matched_products, unmatched_terms, confidence_map)

    # ── Step 3: AI extraction — full raw message, no pre-filtering ───────────
    ai_terms: List[str] = []
    if not skip_ai:
        try:
            raw_ai = ai_extract_products(raw_message)        # YOUR existing function
            if isinstance(raw_ai, list):
                ai_terms = [str(t).strip() for t in raw_ai if t and str(t).strip()]
            logger.info("[AI EXTRACTED] %s", ai_terms)
        except Exception as exc:
            logger.error("[AI FAILED] %s", exc)

    # ── Step 4: Validate AI terms with fuzzy + category check ────────────────
    for term in ai_terms:
        term_aliased = _apply_aliases(term)
        item, score  = _safe_fuzzy(term_aliased, db, shop_id, THRESHOLD_AI_VALIDATED)

        if item and item.id not in seen_ids:
            logger.info("[AI+FUZZY MATCH] '%s' → '%s' (%.2f)", term, item.name, score)
            seen_ids.add(item.id)
            confidence_map[item.id] = score
            matched_products.append(item)
        elif item is None:
            logger.debug("[AI TERM UNVALIDATED] '%s'", term)

    # ── Step 5: System fallback on phrase_parts AI missed ────────────────────
    matched_names_lower = {p.name.lower() for p in matched_products}

    for phrase in phrase_parts:
        phrase_aliased = _apply_aliases(phrase)

        # Skip if already covered by AI step
        if phrase_aliased in matched_names_lower:
            continue

        item, score = _safe_fuzzy(phrase_aliased, db, shop_id, THRESHOLD_FALLBACK)

        if item and item.id not in seen_ids:
            logger.info("[SYS FALLBACK] '%s' → '%s' (%.2f)", phrase, item.name, score)
            seen_ids.add(item.id)
            confidence_map[item.id] = score
            matched_products.append(item)
        elif item is None:
            clean = re.sub(r'[^a-z0-9 ]', '', phrase).strip()
            if len(clean) > 2 and phrase not in unmatched_terms:
                unmatched_terms.append(phrase)

    # ── Step 6: Clean unmatched list ─────────────────────────────────────────
    final_names = {p.name.lower() for p in matched_products}
    unmatched_terms = [
        t for t in unmatched_terms
        if t.lower() not in final_names and _strip_filler(t)
    ]

    return _build_result(matched_products, unmatched_terms, confidence_map)


# ── Result builder ────────────────────────────────────────────────────────────

def _build_result(
    matched:    List[models.InventoryItem],
    unmatched:  List[str],
    confidence: Dict[int, float],
) -> Dict:
    matched_dicts = [
        {
            "id":       item.id,
            "name":     item.name,
            "price":    float(item.price) if item.price is not None else 0,
            "quantity": item.quantity,
            "status":   get_product_status(item),
        }
        for item in matched
    ]
    return {
        "matched_products": matched_dicts,
        "unmatched_terms":  unmatched,
        "confidence_map":   confidence,
        "product_data":     matched_dicts,
    }
