"""
messages.py — Refactored for OMEGA EXECUTION
============================================
Migrated to unified AIRouter to eliminate duplicate AI logic.
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from .auth import UserIdentity, require_permission
from .. import models
from ..services.ai_router import AIRouter
from ..services.session_engine import SessionEngine

router = APIRouter(tags=["AI Messaging"])
logger = logging.getLogger("levix.messages")

class HandleMessageRequest(BaseModel):
    message: str
    customer_phone: Optional[str] = "dashboard"

class HandleMessageResponse(BaseModel):
    reply: str
    intent: str
    probability: int

@router.post("/handle-message", response_model=HandleMessageResponse)
async def handle_message(
    request: HandleMessageRequest, 
    identity: UserIdentity = Depends(require_permission("inbox_reply")), 
    db: Session = Depends(get_db)
):
    """
    Unified entry point for Dashboard Chat.
    Uses the 5-Layer OMEGA Brain.
    """
    shop_id = identity.shop.id
    customer_phone = request.customer_phone or "dashboard_user"
    
    # Process through the main brain
    reply = AIRouter.process_message(db, shop_id, customer_phone, request.message)
    
    # Get session for metadata
    session = SessionEngine.get_session(db, shop_id, customer_phone)
    
    # Get probability from the latest lead created (if any)
    latest_lead = db.query(models.AILead).filter(
        models.AILead.session_id == session.session_id
    ).order_by(models.AILead.created_at.desc()).first()
    
    prob = 50
    if latest_lead and latest_lead.collected_data:
        prob = latest_lead.collected_data.get("probability", 50)

    return {
        "reply": reply,
        "intent": session.last_intent or "unknown",
        "probability": prob
    }

@router.get("/chat-history/{phone}")
async def get_chat_history(
    phone: str,
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db)
):
    session = SessionEngine.get_session(db, identity.shop.id, phone)
    return {
        "history": session.conversation_history or [],
        "status": session.category
    }
