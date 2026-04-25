import logging
import json
import re
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from .. import models
from .session_engine import SessionEngine
from ..core.ai_client import AIClient
from .hybrid_matcher import hybrid_match_message

logger = logging.getLogger("levix.ai_matcher")

from .intent_engine import IntentEngine

def _extract_constraints(message: str) -> Dict[str, Any]:
    """Extracts budget, people count, and spice preference from text using IntentEngine."""
    constraints = {
        "budget": IntentEngine.extract_budget(message),
        "people": IntentEngine.extract_people_count(message),
        "spice": IntentEngine.extract_preference(message),
        "category": None
    }
    
    # Broad Intent / Meal Category
    if any(k in message.lower() for k in ["dinner", "night"]):
        constraints["category"] = "dinner"
    elif any(k in message.lower() for k in ["lunch", "afternoon"]):
        constraints["category"] = "lunch"
    elif any(k in message.lower() for k in ["breakfast", "morning"]):
        constraints["category"] = "breakfast"
    elif any(k in message.lower() for k in ["snack", "snacks", "evening"]):
        constraints["category"] = "snacks"
        
    return {k: v for k, v in constraints.items() if v is not None}

def ai_match_products(message: str, db: Session, shop_id: int, session: models.AIConversationSession, profile: models.CustomerProfile) -> Dict:
    """Enhanced product matcher with constraint-aware inventory injection."""
    
    # 1. Detect Constraints and merge with session memory
    new_constraints = _extract_constraints(message)
    constraints = session.collected_fields.get("constraints", {})
    constraints.update(new_constraints)
    session.collected_fields["constraints"] = constraints
    db.commit()
    
    # Phase 2: Auto Memory Capture
    from .customer_memory import CustomerMemoryEngine
    CustomerMemoryEngine.update_from_message(db, profile, message, constraints)
    
    # 2. Build Inventory Context
    total_products = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == shop_id,
        models.InventoryItem.quantity > 0
    ).count()
    logger.info(f"PRODUCT_COUNT_LOADED: {total_products}")
    
    query = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == shop_id,
        models.InventoryItem.quantity > 0
    )
    
    # Basic budget filtering to reduce context window
    budget = constraints.get("budget")
    if budget:
        query = query.filter(models.InventoryItem.price <= budget)

    items = query.all()
    
    inventory_str = ""
    product_names = []
    for item in items:
        details = (item.product_details or "")[:50]
        inventory_str += f"- ID:{item.id} | {item.name} | ₹{int(item.price)} | {details}\n"
        product_names.append(item.name)
        
    logger.info(f"PRODUCT_NAMES: {', '.join(product_names)}")
    
    if not inventory_str:
        return {"source": "ai", "product_data": [], "constraints": constraints, "total_products": total_products}

    # 3. Strict LEVIX Matching Prompt
    system_prompt = f"""You are the Inventory Matcher for LEVIX.
Match customer msg to inventory IDs based on constraints.
Budget: {constraints.get('budget') or 'any'} | People: {constraints.get('people') or 'any'} | Category: {constraints.get('category', 'any')} | Spice: {constraints.get('spice', 'any')}

INVENTORY:
{inventory_str}

RULES:
1. Return JSON ONLY: {{"matched_ids": [id1, id2], "confidence": 0.9, "is_combo": true}}
2. Match items that fit constraints. If multiple items make a good combo for the number of people and budget, return all their IDs.
3. Only use IDs from the list above.
4. If no good match or combo is possible, return empty list for matched_ids.
"""

    try:
        raw_json = AIClient.generate_content(
            contents=f"Customer: {message}",
            system_instruction=system_prompt,
            config={'response_mime_type': 'application/json', 'temperature': 0.1}
        )
        
        if not raw_json or not raw_json.strip():
            logger.error("FAIL_PROVIDER: ai_match_products - Empty response from AIClient")
            return {"source": "fallback", "product_data": [], "constraints": constraints, "total_products": total_products}
            
        try:
            data = json.loads(raw_json)
        except Exception as e:
            logger.error(f"FAIL_PROVIDER: ai_match_products json parse error - {e}")
            return {"source": "fallback", "product_data": [], "constraints": constraints, "total_products": total_products}
            
        matched_ids = data.get("matched_ids", [])
        is_combo = data.get("is_combo", False)
        if is_combo:
            logger.info("COMBO_GENERATED")
        
        confirmed = []
        if matched_ids:
            # Re-query to get full data
            db_items = db.query(models.InventoryItem).filter(
                models.InventoryItem.id.in_(matched_ids),
                models.InventoryItem.shop_id == shop_id
            ).all()
            for item in db_items:
                confirmed.append({
                    "id": item.id,
                    "name": item.name,
                    "price": float(item.price),
                    "details": (item.product_details or "")[:100]
                })
        
        # Phase 1: Persist session fields
        if confirmed:
            session.matched_product_id = confirmed[0]["id"]
            session.matched_product_name = confirmed[0]["name"]
            session.collected_fields["last_price"] = confirmed[0]["price"]
            if is_combo:
                session.collected_fields["last_recommended_combo"] = confirmed
            else:
                session.collected_fields.pop("last_recommended_combo", None)
            db.commit()
            logger.info(f"SESSION_SAVED: Context updated for {session.customer_phone}")

        logger.info(f"INVENTORY_MATCHED: count={len(confirmed)}")
        return {"source": "ai", "product_data": confirmed, "constraints": constraints, "total_products": total_products}
    except Exception as e:
        logger.error(f"FAIL_PROVIDER: ai_match_products - {e}")
        return {"source": "fallback", "product_data": [], "constraints": constraints, "total_products": total_products}

def generate_ai_reply(product_data: List[Dict], message: str, shop_name: str, intent: str, constraints: Dict, session: models.AIConversationSession, profile: models.CustomerProfile) -> str:
    """
    STRICT LEVIX IDENTITY REPLY GENERATOR.
    Forces AI to act as a shop salesman using only provided products.
    """
    import random
    from .customer_memory import CustomerMemoryEngine
    
    constraints = constraints or {}
    
    inventory_ctx = ""
    if product_data:
        for p in product_data:
            inventory_ctx += f"Product: {p['name']}, Price: ₹{p['price']}, Info: {p.get('details', '')}\n"
    else:
        inventory_ctx = "NO PRODUCTS IN INVENTORY MATCHING THIS REQUEST."

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 2: THE STRICT LEVIX PROMPT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    from ..core.prompt_builder import build_levix_prompt
    memory_ctx = CustomerMemoryEngine.build_memory_context(profile)
    
    # Pre-generate a token so AI can natively include it
    suggested_token = str(random.randint(10, 99))
    prompt = build_levix_prompt(shop_name, inventory_ctx, constraints, memory_ctx, suggested_token)

    try:
        logger.info(f"PROMPT_USED: len={len(prompt)} | inventory={len(product_data)}")
        
        # Format history properly for AIClient if needed, or just include last messages
        history_text = "\n".join([f"{h['role']}: {h['content']}" for h in (session.conversation_history or [])[-4:]])
        contents = f"Recent History:\n{history_text}\n\nCustomer: {message}"
        
        reply = AIClient.generate_content(
            contents=contents, 
            system_instruction=prompt,
            config={'temperature': 0.4}
        )
        
        # Check if AI offered an order token. If yes, save it.
        if "ORDER" in reply.upper() and suggested_token in reply:
            session.collected_fields["last_order_token"] = suggested_token
            from ..database import SessionLocal
            db = SessionLocal()
            db.add(session)
            db.commit()
            db.close()
            logger.info(f"TOKEN_CREATED_BY_AI: {suggested_token}")
        elif product_data and "ORDER" not in reply.upper():
            # Fallback if AI forgot to append it
            session.collected_fields["last_order_token"] = suggested_token
            from ..database import SessionLocal
            db = SessionLocal()
            db.add(session)
            db.commit()
            db.close()
            
            if len(product_data) > 1:
                reply += f"\n\nWant to book this combo? Reply *ORDER {suggested_token}* 🍛"
            else:
                reply += f"\n\nWant me to reserve one? Reply *ORDER {suggested_token}* 🍽️"
        
        logger.info(f"SUCCESS_PROVIDER: reply generated")
        logger.info("MEMORY_USED_IN_REPLY")
        return reply
    except Exception as e:
        logger.error(f"FAIL_PROVIDER: generate_ai_reply - {e}")
        return "I'm checking our stock for you! 😊 One moment please."
