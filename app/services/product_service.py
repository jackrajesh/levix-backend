import re
import os
import difflib
from typing import Optional, List, Dict, Tuple
import logging
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from datetime import datetime
from .. import models
from .sse import broadcast_event

logger = logging.getLogger("levix.product_service")

ALLOWED_STATUSES = ["available", "out_of_stock", "coming_soon"]
LOW_STOCK_THRESHOLD = 5

# Expanded Alias Map for common misspellings and regional variations
ALIAS_MAP = {
    "paal": "milk",
    "chai": "tea",
    "briyani": "biryani",
    "biriyani": "biryani",
    "biryni": "biryani",
    "parotta": "parotta",
    "parrotta": "parotta",
    "chiken": "chicken",
    "ckn": "chicken",
    "leg pis": "leg piece",
    "leg pc": "leg piece",
    "leg piece": "leg piece",
    "wins": "wings",
    "wing": "wings",
    "coke": "coca cola",
    "cola": "coca cola",
    "pepsi": "pepsi cold drink"
}

STOP_WORDS = ["spicy", "hot", "fresh", "cool", "cold", "veg", "nonveg", "pure", "best", "special"]

def normalize_product(name: str) -> str:
    """
    Strict normalization for product names:
    - Lowercase
    - Removes punctuation
    - Removes units
    - Applies alias map to each word
    """
    if not name:
        return ""
    
    n = name.lower().strip()
    
    # 1. Clean special chars & punctuation
    n = re.sub(r'[^a-z0-9 ]', ' ', n)
    
    # 2. Strip Units
    units = [
        "packet", "pck", "pcs", "piece", "item", "kg", "gram", "gm", 
        "litre", "lit", "ml", "box", "set", "nos", "pks"
    ]
    pattern = r'\b(' + '|'.join(units) + r')\b'
    n = re.sub(pattern, ' ', n)
    
    # 3. Collapse spaces
    n = " ".join(n.split())
    
    # 4. Token-level alias mapping (synonyms)
    tokens = n.split()
    aliased_tokens = [ALIAS_MAP.get(t, t) for t in tokens]
    
    return " ".join(aliased_tokens)

def get_similarity(s1: str, s2: str) -> float:
    """Calculates Levenshtein-based similarity score."""
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

GENERIC_CATEGORIES = ["chicken", "juice", "rice", "biryani", "milk", "tea", "coffee", "mutton", "egg", "fish", "ckn"]

def fuzzy_match_with_score(query: str, db: Session, shop_id: int) -> Tuple[Optional[models.InventoryItem], float]:
    """
    STRICT MATCH MODE:
    1. Returns (Best Match Item, Similarity Score).
    2. Threshold required: 0.85 or perfect substring.
    """
    if not query:
        return None, 0.0
        
    # Replace common short-hands before normalizing
    query = re.sub(r'\bckn\b', 'chicken', query, flags=re.IGNORECASE)
        
    q_norm = normalize_product(query)
    if not q_norm:
        return None, 0.0
    
    is_generic = q_norm in GENERIC_CATEGORIES
    
    items = db.query(models.InventoryItem).options(
        joinedload(models.InventoryItem.aliases)
    ).filter(models.InventoryItem.shop_id == shop_id).all()
    
    best_match = None
    max_score = 0
    
    q_tokens = set(q_norm.split())
    for item in items:
        names_to_check = [item.name] + [a.alias for a in item.aliases]
        for name in names_to_check:
            n_norm = normalize_product(name)
            
            # 1. Exact Hit
            if q_norm == n_norm:
                logger.info(f"MATCH_CONFIDENCE: {q_norm} == {n_norm} -> 1.0")
                return item, 1.0
            
            score = get_similarity(q_norm, n_norm)
            
            # 2. Substring / Fuzzy Contains Boosting
            if q_norm in n_norm:
                score = max(score, 0.90) 
            elif n_norm in q_norm:
                score = max(score, 0.88)
            
            # 3. Token Match Boost
            n_tokens = set(n_norm.split())
            common = q_tokens.intersection(n_tokens)
            if common:
                token_score = len(common) / len(max(q_tokens, n_tokens, key=len))
                if token_score >= 0.8:
                    score = max(score, 0.85)
                elif token_score >= 0.5:
                    score = max(score, 0.75)

            # --- GENERIC GATE ---
            if is_generic and score < 0.95:
                score = score * 0.7 # Penalize heavily
            
            if score > max_score:
                max_score = score
                best_match = item

    if best_match:
        logger.info(f"MATCH_CONFIDENCE: '{query}' -> '{best_match.name}' = {max_score:.2f}")

    return best_match, max_score

def fuzzy_match_product(query: str, db: Session, shop_id: int) -> Optional[models.InventoryItem]:
    """Simplified wrapper with 0.85 Threshold."""
    logger.info(f"[STRICT MATCH MODE ACTIVE] Processing: {query}")
    item, score = fuzzy_match_with_score(query, db, shop_id)
    
    # Final gate
    if item and score >= 0.80:
        logger.info(f"[MATCH SUCCESS] '{query}' -> '{item.name}' ({score:.2f})")
        return item
    
    logger.info(f"[MATCH FAILED] '{query}' best score: {score:.2f}")
    return None
    """
    Overhauled matching logic:
    1. Normalize
    2. Alias Mapping
    3. Dynamic Threshold Fuzzy Match
    """
    if not query:
        return None
        
    # --- 1. NORMALIZE ---
    q_norm = normalize_product(query)
    if not q_norm:
        return None
        
    # --- 2. ALIAS MAPPING ---
    # Check if the query itself is a direct alias
    q_final = ALIAS_MAP.get(q_norm, q_norm)
    
    print(f"[MATCH] Query: '{query}' -> Norm: '{q_norm}' -> Final: '{q_final}'")
    
    # Fetch shop products with aliases
    items = db.query(models.InventoryItem).options(
        joinedload(models.InventoryItem.aliases)
    ).filter(models.InventoryItem.shop_id == shop_id).all()
    
    # Dynamic Threshold
    threshold = 0.85 if len(q_final) < 5 else 0.7
    
    best_match = None
    max_score = 0
    
    # Try Matching
    def attempt_match(target_query: str):
        nonlocal best_match, max_score
        target_norm = normalize_product(target_query)
        q_tokens = set(target_norm.split())
        
        for item in items:
            # Check primary name and aliases
            names_to_check = [item.name.lower()] + [a.alias.lower() for a in item.aliases]
            for name in names_to_check:
                n_norm = normalize_product(name)
                
                # Check 1: Direct Equality
                if target_norm == n_norm:
                    print(f"[MATCH] Exact Hit: {item.name}")
                    max_score = 1.0
                    best_match = item
                    return item
                    
                # Check 2: Fuzzy Similarity
                score = get_similarity(target_norm, n_norm)
                if score > max_score:
                    max_score = score
                    best_match = item
                    
                # Check 3: Multi-word Contains (Stronger than simple similarity)
                if target_norm in n_norm or n_norm in target_norm:
                    score_boost = 0.8  # Contains is a strong signal
                    if score_boost > max_score:
                        max_score = score_boost
                        best_match = item

                # Check 4: Word-level Matching (Bonus for important words)
                n_tokens = set(n_norm.split())
                common_tokens = q_tokens.intersection(n_tokens)
                if common_tokens:
                    # Score based on how many tokens from query were found
                    token_score = len(common_tokens) / len(q_tokens)
                    if token_score >= 0.7:
                        final_score = 0.75
                        if final_score > max_score:
                            max_score = final_score
                            best_match = item
        return None

    # First Attempt
    result = attempt_match(q_final)
    if result:
        return result
        
    # --- FALLBACK MATCH BOOST (Strip Stop Words) ---
    if max_score < threshold:
        print(f"[MATCH] Score {max_score:.2f} below threshold {threshold}. Trying fallback boost...")
        q_stripped = " ".join([w for w in q_final.split() if w not in STOP_WORDS])
        if q_stripped != q_final:
            result = attempt_match(q_stripped)
            if result:
                return result

    if max_score >= threshold:
        print(f"[MATCH SCORE]: '{q_final}' vs '{best_match.name}' -> {max_score:.2f} (Matched)")
        return best_match
        
    print(f"[MATCH] No match. Best score: {max_score:.2f} for '{best_match.name if best_match else 'None'}'")
    return None

def normalize_message(message: str) -> str:
    """Compatibility wrapper for webhooks.py"""
    msg = message.lower().strip()
    msg = re.sub(r'[?!.]', ' ', msg)
    return msg

def get_greeting_response(message: str) -> Optional[str]:
    """Compatibility for webhooks.py"""
    if re.search(r'^\b(hi|hello|hey|vanakkam|vanakam)\b', message, re.IGNORECASE):
        return "Vanakkam! How can I help you?"
    return None

def get_product_status(item: models.InventoryItem) -> str:
    """Standardized product status."""
    if getattr(item, 'status', None) == 'coming_soon':
        return 'coming_soon'
    if getattr(item, 'status', None) == 'out_of_stock' or item.quantity <= 0:
        return 'out_of_stock'
    if 1 <= item.quantity <= 5:
        return 'low_stock'
    return 'available'

def get_product_state(item: models.InventoryItem) -> str:
    """Alias for get_product_status for compatibility."""
    return get_product_status(item)

def match_multiple_products(message: str, db: Session, shop_id: int) -> Tuple[List[models.InventoryItem], List[str], bool]:
    """Modernized multi-product logic using tiered matching."""
    segments = re.split(r'\band\b|,|&', message.lower())
    segments = [s.strip() for s in segments if s.strip()]
    
    final_matched = []
    final_unknown = []
    
    for segment in segments:
        if len(segment.split()) > 12:
            return [], [], True
            
        product = fuzzy_match_product(segment, db, shop_id)
        if product:
            final_matched.append(product)
        else:
            clean_s = re.sub(r'[^a-z0-9 ]', '', segment).strip()
            if len(clean_s) > 2:
                final_unknown.append(segment)
                
    unique_matched = []
    seen_ids = set()
    for p in final_matched:
        if p.id not in seen_ids:
            unique_matched.append(p)
            seen_ids.add(p.id)
            
    return unique_matched, final_unknown, False

def sync_stock_status(item: models.InventoryItem, db: Session):
    """Automation logic to sync status based on quantity."""
    if item.status != "coming_soon":
        if item.quantity > 0:
            if item.status == "out_of_stock":
                item.status = "available"
            item.stock_warning_active = False
        elif item.quantity <= 0:
            item.status = "out_of_stock"
            item.stock_warning_active = False

def handle_low_stock_log(item: models.InventoryItem, db: Session):
    """Logs a low stock entry if threshold is hit."""
    if item.quantity <= LOW_STOCK_THRESHOLD and not item.stock_warning_active:
        new_log = models.LogEntry(
            shop_id=item.shop_id, 
            product_name=item.name, 
            product_id=item.id, 
            status="low_stock"
        )
        db.add(new_log)
        item.stock_warning_active = True
    elif item.quantity > LOW_STOCK_THRESHOLD:
        item.stock_warning_active = False

def add_log_db(db: Session, shop_id: int, product_name: str, status: str, product_id: Optional[int] = None, is_matched: bool = True, match_source: Optional[str] = None, performed_by: Optional[str] = None, user_type: Optional[str] = None):
    # Scrub internal system strings from analytics
    blocked = ["unknowns", "append", "join", "matchmultipleproducts"]
    name_low = product_name.lower()
    if any(k in name_low for k in blocked):
        return

    new_entry = models.LogEntry(
        shop_id=shop_id,
        product_name=product_name,
        product_id=product_id,
        status=status,
        is_matched=is_matched,
        match_source=match_source,
        performed_by=performed_by,
        user_type=user_type
    )
    db.add(new_entry)
    db.commit()
