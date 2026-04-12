import random
import re
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..services.ai_parser import parse_message_with_ai, generate_human_reply, ai_extract_products
from ..services.product_service import (
    fuzzy_match_product, 
    get_product_status,
    fuzzy_match_with_score,
    GENERIC_CATEGORIES
)
from ..utils import filter_filler_words, generate_reply, CUSTOMER_FILLER_WORDS, normalize_conversational_input

router = APIRouter(tags=["AI Parsing"])

# --- CACHE SYSTEM ---
MESSAGE_CACHE = {}

class AIRequest(BaseModel):
    message: str

class AIResponse(BaseModel):
    products: List[str]
    quantity: int
    intent: str

@router.post("/parse-message", response_model=AIResponse)
async def parse_message(request: AIRequest):
    result = parse_message_with_ai(request.message)
    return {
        "products": result.get("products", []),
        "quantity": result.get("quantity", 1),
        "intent": str(result.get("intent", "unknown"))
    }

class HandleMessageRequest(BaseModel):
    message: str
    shop_id: int

class HandleMessageResponse(BaseModel):
    reply: str

def extract_words_from_message(message: str) -> List[str]:
    """
    STRICT EXTRACTION: Normalize, filter stop words, remove junk, and enforce min length (3+).
    """
    clean_msg = normalize_conversational_input(message)
    words = clean_msg.split()
    
    blacklist = {
        "file", "word", "length", "each", "debug", "single", "something", "uh", "umm", "give", "take",
        "after", "before", "matching", "intent", "products", "tones"
    }
    
    tokens = []
    seen = set()
    for w in words:
        clean_w = w.strip("?,.!")
        if (clean_w not in CUSTOMER_FILLER_WORDS and 
            clean_w not in blacklist and 
            len(clean_w) >= 3 and 
            clean_w not in seen):
            tokens.append(clean_w)
            seen.add(clean_w)
            
    return tokens

@router.post("/handle-message", response_model=HandleMessageResponse)
async def handle_message(request: HandleMessageRequest, db: Session = Depends(get_db)):
    """
    FINAL PRODUCTION PIPELINE:
    1. Extract & Limit (Max 8)
    2. Backend Match Pass (Best Match Only)
    3. AI Rescue (Single Pass, High-Value Only)
    4. Fuzzy Boost Fallback (0.6 Recovery)
    5. Record Clean Analytics & Pending
    """
    user_msg = request.message
    shop_id = request.shop_id
    msg_clean = normalize_conversational_input(user_msg)
    
    # --- GREETING SHORT-CIRCUIT ---
    greeting_keywords = ["hi", "hello", "hey", "vanakkam", "vanakam", "namaste", "namaskaram"]
    if any(msg_clean == k or msg_clean.startswith(k + " ") for k in greeting_keywords):
        return {"reply": "Vanakkam! 😄 What are you looking for today?"}

    # --- 1. TOKEN EXTRACTION & LIMIT (MAX 8) ---
    tokens = extract_words_from_message(user_msg)
    ux_warning = ""
    if len(tokens) > 8:
        tokens = tokens[:8]
        ux_warning = "\n\n(Showing first 8 products only)"
    
    print(f"\n[STRICT MATCH MODE ACTIVE] Input: {user_msg}")
    print(f"[FINAL TOKENS]: {tokens}")

    # --- 2. BACKEND MATCH PASS (TIER 1) ---
    matched_items = []
    unmatched_tokens = []
    
    for token in tokens:
        item, score = fuzzy_match_with_score(token, db, shop_id)
        if item and score >= 0.75:
            matched_items.append({
                "item": item, "score": score, "requested": token, "source": "fuzzy"
            })
        else:
            unmatched_tokens.append(token)
    
    # --- 3. AI RESCUE GATE (TIER 2 - SINGLE PASS) ---
    ai_triggered = False
    ai_results = []
    
    high_value_unmatched = [
        t for t in unmatched_tokens 
        if len(t) >= 4 and t not in CUSTOMER_FILLER_WORDS
    ]
    
    if high_value_unmatched:
        print(f"[AI GATE] Triggering for: {high_value_unmatched}")
        ai_triggered = True
        ai_data = ai_extract_products(" ".join(high_value_unmatched))
        
        if ai_data:
            print(f"[AI USED] Extracted: {ai_data}")
            for p_name in ai_data:
                item, score = fuzzy_match_with_score(p_name, db, shop_id)
                if item and score >= 0.7:
                    matched_items.append({
                        "item": item, "score": score, "requested": p_name, "source": "ai"
                    })
                else:
                    ai_results.append(p_name)
    
    # --- 4. FUZZY BOOST FALLBACK (0.6 RECOVERY) ---
    # Triggered if AI fails, returns nothing, or was skipped despite unmatched tokens existing
    if unmatched_tokens and (not ai_triggered or not ai_results):
        print(f"[AI FAILED → FALLBACK] Attempting 0.6 recovery for tokens: {unmatched_tokens}")
        remaining = []
        for token in unmatched_tokens:
            item, score = fuzzy_match_with_score(token, db, shop_id)
            if item and score >= 0.6:
                print(f"[FUZZY BOOST USED] '{token}' -> '{item.name}' ({score:.2f})")
                matched_items.append({
                    "item": item, "score": score, "requested": token, "source": "fuzzy_boost"
                })
            else:
                remaining.append(token)
        unmatched_tokens = remaining

    # --- 5. MERGE & UNIQUE (BEST MATCH ONLY) ---
    final_matched_data = []
    seen_ids = set()
    for m in matched_items:
        if m['item'].id not in seen_ids:
            item = m['item']
            status = get_product_status(item)
            if 1 <= item.quantity <= 5: status = "low_stock"
            
            final_matched_data.append({
                "id": item.id,
                "name": item.name,
                "status": status,
                "price": float(item.price) if item.price else 0,
                "quantity": item.quantity,
                "requested_name": m['requested'],
                "source": m['source']
            })
            seen_ids.add(item.id)

    # --- 6. RECORD CLEAN DATA (STRICT) ---
    # Matched Analytics: Save ONLY matched product names
    for entry in final_matched_data:
        db.add(models.LogEntry(
            shop_id=shop_id,
            product_name=entry['name'],
            product_id=entry['id'],
            status=entry['status'],
            is_matched=True,
            match_source=entry['source']
        ))

    # Clean Pending: Skip minor typos, fillers, generic, short tokens
    pending_cands = list(set(unmatched_tokens + ai_results))
    
    # Specific noise blocklist
    NOISE_BLOCKLIST = ["mujhe", "aur", "bro", "venum", "something", "item", "product"]
    
    for cand in pending_cands:
        c_low = cand.lower().strip()
        
        # 1. Validation Logic
        is_invalid = False
        if len(c_low) < 4: is_invalid = True
        if c_low in CUSTOMER_FILLER_WORDS or c_low in GENERIC_CATEGORIES: is_invalid = True
        if c_low in NOISE_BLOCKLIST: is_invalid = True
        
        # 2. VOWEL CHECK (fragments like 'chkn', 'bryn' have no vowels)
        if not any(v in c_low for v in "aeiou"):
            is_invalid = True
            
        if is_invalid:
            print(f"[PENDING BLOCKED INVALID TOKEN]: {cand}")
            continue
            
        # 3. Similarity Filter (Skip if score > 0.6 to inventory)
        item, score = fuzzy_match_with_score(c_low, db, shop_id)
        if item and score >= 0.6:
            continue
            
        # 4. Already matched check
        if any(c_low in m['name'].lower() or m['requested_name'].lower() == c_low for m in final_matched_data):
            continue
            
        print(f"[PENDING SAVED VALID]: {cand}")
        db.add(models.PendingRequest(
            shop_id=shop_id,
            product_name=cand.capitalize(),
            customer_message=user_msg
        ))
        # Note: We do NOT save unmatched tokens to LogEntry anymore for analytics purity
        
    db.commit()

    # --- 7. RESPONSE ---
    template_reply = ""
    if final_matched_data:
        template_reply = "Yes, we have:"
        for match in final_matched_data:
            price_str = f" – ₹{int(match['price'])}" if match['price'] else ""
            status_emoji = "✅" if match['status'] in ("available", "low_stock") else "❌"
            if match['status'] == "low_stock": status_emoji = "⚠️ (Few left)"
            template_reply += f"\n• {match['name']}{price_str} {status_emoji}"
        template_reply += "\n\nAny other requirement?"
    else:
        template_reply = "I've noted your request and will check with the owner shortly. 👍" if tokens else "Vanakkam! How can I help you today?"

    # --- 7. RESPONSE (Template Only for Speed) ---
    final_reply = template_reply + ux_warning
    print(f"[LATENCY OPTIMIZED] Final response generated via template.")

    print(f"[FINAL RESPONSE]: {final_reply}")
    return {"reply": final_reply}
