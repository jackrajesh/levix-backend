import re
import os
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from datetime import datetime
from .. import models
from ..utils import filter_filler_words
from .sse import broadcast_event

ALLOWED_STATUSES = ["available", "out_of_stock", "coming_soon"]
LOW_STOCK_THRESHOLD = 5

def normalize_message(message: str) -> str:
    msg = message.lower().strip()
    msg = re.sub(r'[?!.]', ' ', msg)
    fillers = [
        'iruka', 'irukaa', 'irukuma', 'venum', 'venuma', 
        'vechirukingala', 'available', 'ah', 'bro', 'anna', 'please'
    ]
    pattern = r'\b(' + '|'.join(fillers) + r')\b'
    msg = re.sub(pattern, ' ', msg)
    msg = " ".join(msg.split())
    return msg

def get_greeting_response(message: str) -> Optional[str]:
    if re.search(r'^\b(hi|hello|hey|vanakkam|vanakam)\b', message, re.IGNORECASE):
        return "Vanakkam! How can I help you?"
    return None

def match_product_db(cleaned_message: str, db: Session, shop_id: int):
    """Match a product from the DB inventory using regex search ordered by alias length."""
    items = db.query(models.InventoryItem).options(
        joinedload(models.InventoryItem.aliases)
    ).filter(models.InventoryItem.shop_id == shop_id).all()
    
    matches = []
    
    for item in items:
        for alias_obj in item.aliases:
            alias = alias_obj.alias.lower()
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, cleaned_message, re.IGNORECASE):
                matches.append((alias, item))
                
    if not matches:
        return None
        
    matches.sort(key=lambda x: len(x[0]), reverse=True)
    return matches[0][1]

def add_log_db(db: Session, shop_id: int, product_name: str, status: str, product_id: Optional[int] = None):
    new_entry = models.LogEntry(
        shop_id=shop_id,
        product_name=product_name,
        product_id=product_id,
        status=status,
    )
    db.add(new_entry)
    db.commit()

def sync_stock_status(item: models.InventoryItem, db: Session):
    """Automation logic to sync status based on quantity."""
    if item.status != "coming_soon":
        if item.quantity > 0:
            if item.status == "out_of_stock":
                item.status = "available"
            item.stock_warning_active = False
        elif item.quantity <= 0:
            if item.status == "available" and not item.stock_warning_active:
                # Trigger OOS Warning request
                new_warning = models.PendingRequest(
                    shop_id=item.shop_id,
                    product_id=item.id,
                    product_name=item.name,
                    customer_message=f"Product {item.name} has reached 0 stock. Switch to Out Of Stock?",
                    request_type="oos_warning"
                )
                db.add(new_warning)
                item.stock_warning_active = True
                db.flush()
                broadcast_event("pending_created")

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

def get_product_state(item):
    if getattr(item, 'status', None) == 'coming_soon':
        return 'coming_soon'
    if getattr(item, 'status', None) == 'manual' or getattr(item, 'price', None) is None:
        return 'owner_check'
    if getattr(item, 'status', None) == 'out_of_stock' or item.quantity == 0:
        return 'out_of_stock'
    if 1 <= item.quantity <= 5:
        return 'low_stock'
    return 'available'

def match_multiple_products(message: str, db: Session, shop_id: int):
    # STEP 1: Normalize message
    msg = message.lower()
    
    # STEP 2: Split into segments using separators
    segments = re.split(r'\band\b|,|&', msg)
    segments = [s.strip() for s in segments if s.strip()]
    
    # STEP 2.5: Normalize products (once for all segments)
    products = db.query(models.InventoryItem).options(
        joinedload(models.InventoryItem.aliases)
    ).filter(models.InventoryItem.shop_id == shop_id).all()
    
    product_map = []
    for p in products:
        names = [p.name.lower()]
        if p.aliases:
            names += [a.alias.lower() for a in p.aliases]
        product_map.append((p, names))
        
    FILLER_WORDS = set(['pa','iruka','da','bro','hello','hey','pls','please', 'with', 'for', 'the', 'this', 'that'])
    
    final_matched = []
    final_unknown = []
    
    # STEP 4: Process each segment independently
    for segment in segments:
        # Clean segment from punctuations
        s_clean = re.sub(r'[^a-zA-Z0-9 ]', '', segment).strip()
        if not s_clean:
            continue
            
        words = s_clean.split()
        if not words:
            continue
            
        if len(words) > 12:
            return [], [], True
            
        matched = []
        used_indices = set()
        
        # Phrase match
        for i in range(len(words)-1):
            if i in used_indices or i+1 in used_indices:
                continue
            phrase = words[i] + ' ' + words[i+1]
            for product, names in product_map:
                if phrase in names:
                    matched.append(product)
                    used_indices.add(i)
                    used_indices.add(i+1)
                    break
        
        # Single word match
        for i, word in enumerate(words):
            if i in used_indices:
                continue
            for product, names in product_map:
                if word in names:
                    matched.append(product)
                    used_indices.add(i)
                    break
        
        # Unknown per segment
        segment_unknown_words = []
        for i, word in enumerate(words):
            if i in used_indices:
                continue
            if len(word) <= 2 or word in FILLER_WORDS:
                continue
            segment_unknown_words.append(word)
            
        if segment_unknown_words:
            # Join unknown words in this segment into one phrase
            final_unknown.append(" ".join(segment_unknown_words))
            
        final_matched.extend(matched)
        
    # STEP 5: Remove duplicates
    final_matched = list({p.id: p for p in final_matched}.values())
    final_unknown = list(dict.fromkeys(final_unknown))
    
    return final_matched, final_unknown, False
