"""
inbox.py — Levix AI Leads Inbox + AI Chat API
==============================================
Routes:
  POST /ai/chat               — Main customer chat endpoint
  GET  /ai/leads              — Owner inbox: all AI leads
  GET  /ai/leads/{id}         — Single lead detail
  PATCH /ai/leads/{id}/accept — Accept lead → send auto-reply
  PATCH /ai/leads/{id}/reject — Reject lead → send auto-reply
  PATCH /ai/leads/{id}/request-info — Request more info (resumes AI)
  GET  /ai/analytics          — Funnel analytics
  GET  /ai/sessions/{session_id} — Full session transcript
"""

import uuid
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from .. import models
from ..database import get_db
from .auth import require_permission, UserIdentity
from ..services.ai_assistant import process_customer_message
from ..services.sse import broadcast_event

router = APIRouter(prefix="/ai", tags=["AI Assistant"])
logger = logging.getLogger("levix.inbox")


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class AIChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    customer_phone: Optional[str] = None
    source: Optional[str] = "web"
    shop_id: Optional[int] = None   # Widget may pass this; auth validates


class AIChatResponse(BaseModel):
    reply: str
    intent: str
    confidence: float
    matched_product: dict
    collected_fields: dict
    missing_fields: list
    lead_ready: bool
    lead_created: bool
    next_question: str
    session_id: str


class LeadActionRequest(BaseModel):
    note: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# CHAT ENDPOINT (called by widget + WhatsApp relay)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(
    request: AIChatRequest,
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db),
):
    """
    Primary AI chat endpoint (Dashboard Widget).
    Now powered by the 4-Layer AIRouter.
    """
    shop_id = identity.shop.id
    customer_phone = request.customer_phone or f"dash_{identity.user_id}"
    
    from ..services.ai_router import AIRouter
    reply = AIRouter.process_message(db, shop_id, customer_phone, request.message)
    
    # Fetch session to get metadata
    from ..services.session_engine import SessionEngine
    session = SessionEngine.get_session(db, shop_id, customer_phone)

    return {
        "reply": reply,
        "intent": session.last_intent or "unknown",
        "confidence": 0.9,
        "matched_product": {"name": session.matched_product_name} if session.matched_product_name else {},
        "collected_fields": session.collected_fields or {},
        "missing_fields": session.missing_fields or [],
        "lead_ready": session.lead_created,
        "lead_created": session.lead_created,
        "next_question": "",
        "session_id": session.session_id
    }


@router.post("/chat/public", response_model=AIChatResponse)
async def ai_chat_public(
    shop_id: int,
    request: AIChatRequest,
    db: Session = Depends(get_db),
):
    """
    Unauthenticated endpoint for embedded customer widget.
    Now powered by the 4-Layer AIRouter.
    """
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    customer_phone = request.customer_phone or "public_user"
    
    from ..services.ai_router import AIRouter
    reply = AIRouter.process_message(db, shop_id, customer_phone, request.message)
    
    from ..services.session_engine import SessionEngine
    session = SessionEngine.get_session(db, shop_id, customer_phone)

    return {
        "reply": reply,
        "intent": session.last_intent or "unknown",
        "confidence": 0.9,
        "matched_product": {"name": session.matched_product_name} if session.matched_product_name else {},
        "collected_fields": session.collected_fields or {},
        "missing_fields": session.missing_fields or [],
        "lead_ready": session.lead_created,
        "lead_created": session.lead_created,
        "next_question": "",
        "session_id": session.session_id
    }


# ══════════════════════════════════════════════════════════════════════════════
# LEADS INBOX
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/leads")
def get_leads(
    status: Optional[str] = Query(None, description="Filter: new|accepted|rejected|info_requested"),
    intent: Optional[str] = Query(None, description="Filter by intent"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db),
):
    """Return AI leads inbox for the shop, newest first."""
    shop_id = identity.shop.id
    q = db.query(models.AILead).filter(models.AILead.shop_id == shop_id)
    if status:
        q = q.filter(models.AILead.status == status)
    if intent:
        q = q.filter(models.AILead.intent == intent)

    total = q.count()
    leads = q.order_by(models.AILead.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "leads": [_serialize_lead(lead) for lead in leads],
    }


@router.get("/leads/{lead_id}")
def get_lead(
    lead_id: int,
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db),
):
    lead = _get_lead_or_404(db, lead_id, identity.shop.id)
    return _serialize_lead(lead, detailed=True)


@router.patch("/leads/{lead_id}/accept")
def accept_lead(
    lead_id: int,
    body: LeadActionRequest = LeadActionRequest(),
    identity: UserIdentity = Depends(require_permission("orders_edit")),
    db: Session = Depends(get_db),
):
    """Mark lead as accepted and broadcast confirmation reply."""
    lead = _get_lead_or_404(db, lead_id, identity.shop.id)
    lead.status = "accepted"
    db.commit()

    auto_reply = (
        "✅ Your request has been accepted! "
        "Our team will contact you shortly to confirm the details."
    )
    broadcast_event(identity.shop.id, "lead_accepted", json.dumps({
        "lead_id": lead_id,
        "session_id": lead.session_id,
        "auto_reply": auto_reply,
    }))
    logger.info("[INBOX] Lead #%d accepted by %s", lead_id, identity.name)
    return {"status": "success", "message": "Lead accepted", "auto_reply": auto_reply}


@router.patch("/leads/{lead_id}/reject")
def reject_lead(
    lead_id: int,
    body: LeadActionRequest = LeadActionRequest(),
    identity: UserIdentity = Depends(require_permission("orders_cancel")),
    db: Session = Depends(get_db),
):
    """Mark lead as rejected and broadcast polite decline."""
    lead = _get_lead_or_404(db, lead_id, identity.shop.id)
    lead.status = "rejected"
    db.commit()

    auto_reply = (
        "Sorry, this item or service is unavailable right now. "
        "Feel free to ask us about other options anytime! 🙏"
    )
    broadcast_event(identity.shop.id, "lead_rejected", json.dumps({
        "lead_id": lead_id,
        "session_id": lead.session_id,
        "auto_reply": auto_reply,
    }))
    logger.info("[INBOX] Lead #%d rejected by %s", lead_id, identity.name)
    return {"status": "success", "message": "Lead rejected", "auto_reply": auto_reply}


@router.patch("/leads/{lead_id}/request-info")
def request_more_info(
    lead_id: int,
    body: LeadActionRequest = LeadActionRequest(),
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db),
):
    """Ask customer for more info — AI resumes collecting missing fields."""
    lead = _get_lead_or_404(db, lead_id, identity.shop.id)
    lead.status = "info_requested"
    db.commit()

    note = body.note or "Could you share a few more details so we can process your request?"
    broadcast_event(identity.shop.id, "lead_info_requested", json.dumps({
        "lead_id": lead_id,
        "session_id": lead.session_id,
        "note": note,
    }))
    return {"status": "success", "message": "More info requested", "note": note}


# ══════════════════════════════════════════════════════════════════════════════
# SESSION TRANSCRIPT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/sessions/{session_id}")
def get_session_transcript(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db),
):
    """Return the full conversation transcript for a session."""
    session = (
        db.query(models.AIConversationSession)
        .filter(
            models.AIConversationSession.session_id == session_id,
            models.AIConversationSession.shop_id == identity.shop.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "customer_phone": session.customer_phone,
        "source": session.source,
        "turn_count": session.turn_count,
        "last_intent": session.last_intent,
        "intent_confidence": float(session.intent_confidence) if session.intent_confidence else 0.0,
        "category": session.category,
        "matched_product": session.matched_product_name,
        "collected_fields": session.collected_fields or {},
        "missing_fields": session.missing_fields or [],
        "lead_created": session.lead_created,
        "conversation_history": session.conversation_history or [],
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics")
def get_ai_analytics(
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db),
):
    """Return AI funnel analytics for the shop."""
    shop_id = identity.shop.id

    # Chat sessions
    total_sessions = (
        db.query(sa_func.count(models.AIConversationSession.id))
        .filter(models.AIConversationSession.shop_id == shop_id)
        .scalar() or 0
    )

    # Leads
    total_leads = (
        db.query(sa_func.count(models.AILead.id))
        .filter(models.AILead.shop_id == shop_id)
        .scalar() or 0
    )
    accepted_leads = (
        db.query(sa_func.count(models.AILead.id))
        .filter(models.AILead.shop_id == shop_id, models.AILead.status == "accepted")
        .scalar() or 0
    )

    # Avg messages to lead
    avg_turns_row = (
        db.query(sa_func.avg(models.AIConversationSession.turn_count))
        .filter(
            models.AIConversationSession.shop_id == shop_id,
            models.AIConversationSession.lead_created == True,
        )
        .scalar()
    )
    avg_turns = round(float(avg_turns_row), 1) if avg_turns_row else 0.0

    # Top products requested
    top_products = (
        db.query(models.AILead.product_name, sa_func.count(models.AILead.id).label("count"))
        .filter(models.AILead.shop_id == shop_id, models.AILead.product_name.isnot(None))
        .group_by(models.AILead.product_name)
        .order_by(sa_func.count(models.AILead.id).desc())
        .limit(5)
        .all()
    )

    # Intent breakdown
    intent_rows = (
        db.query(models.AILead.intent, sa_func.count(models.AILead.id).label("count"))
        .filter(models.AILead.shop_id == shop_id)
        .group_by(models.AILead.intent)
        .all()
    )

    # Event counts from analytics table
    event_rows = (
        db.query(models.AIAnalyticsEvent.event_type, sa_func.count(models.AIAnalyticsEvent.id).label("count"))
        .filter(models.AIAnalyticsEvent.shop_id == shop_id)
        .group_by(models.AIAnalyticsEvent.event_type)
        .all()
    )
    event_counts = {row.event_type: row.count for row in event_rows}

    conversion_rate = round((accepted_leads / total_leads * 100), 1) if total_leads > 0 else 0.0

    return {
        "chats_started":        event_counts.get("chat_started", 0),
        "messages_processed":   event_counts.get("message_processed", 0),
        "leads_created":        total_leads,
        "leads_accepted":       accepted_leads,
        "conversion_rate_pct":  conversion_rate,
        "avg_messages_to_lead": avg_turns,
        "top_products_requested": [{"product": r.product_name, "count": r.count} for r in top_products],
        "intent_breakdown":     [{"intent": r.intent, "count": r.count} for r in intent_rows],
        "total_sessions":       total_sessions,
        "ai_handoff_rate_pct":  round((event_counts.get("lead_created", 0) / max(total_sessions, 1)) * 100, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_lead_or_404(db: Session, lead_id: int, shop_id: int) -> models.AILead:
    lead = (
        db.query(models.AILead)
        .filter(models.AILead.id == lead_id, models.AILead.shop_id == shop_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _serialize_lead(lead: models.AILead, detailed: bool = False) -> dict:
    """OMEGA: Revenue-aware serialization."""
    data = lead.collected_data or {}
    
    # Extract metrics from Revenue Brain (Layer 4)
    probability = data.get("probability", 50)
    urgency = data.get("urgency", "LOW")
    signals = data.get("signals", [])
    
    # Additional logic for display scoring
    if lead.status == "accepted": probability = 99
    elif lead.status == "rejected": probability = 5
    
    base = {
        "id": lead.id,
        "session_id": lead.session_id,
        "customer_name": lead.customer_name or "Valued Customer",
        "phone": lead.phone,
        "product_name": lead.product_name or "Inquiry",
        "category": lead.category,
        "intent": lead.intent,
        "summary": lead.summary,
        "status": lead.status,
        "source": lead.source,
        "urgency": urgency,
        "signals": signals,
        "conversion_probability": int(probability),
        "confidence": float(lead.confidence) if lead.confidence else 0.0,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }
    if detailed:
        base["collected_data"] = data
    return base
