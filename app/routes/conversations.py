from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, or_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from .. import models
from ..database import get_db
from .auth import get_current_shop, UserIdentity, require_permission
from ..services.sse import broadcast_event

router = APIRouter(tags=["conversations"])

class SendReplyRequest(BaseModel):
    message: str

class CategoryCreateRequest(BaseModel):
    name: str
    color: Optional[str] = "#3b82f6"

class AssignCategoryRequest(BaseModel):
    category_id: Optional[str] = None

class UpdateStatusRequest(BaseModel):
    status: str

@router.get("/conversations")
def get_conversations(
    status: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    query = db.query(models.ConversationSession).filter(
        models.ConversationSession.shop_id == current_shop.id
    )
    
    # Filter by status and soft-delete state
    if status == "DELETED":
        query = query.filter(models.ConversationSession.is_deleted == True)
    else:
        query = query.filter(or_(models.ConversationSession.is_deleted == False, models.ConversationSession.is_deleted == None))
        
        if status:
            if status == "ACTIVE":
                query = query.filter(models.ConversationSession.inquiry_status == "ACTIVE")
            elif status == "PAUSED":
                query = query.filter(models.ConversationSession.inquiry_status == "PAUSED")
            elif status == "WAITING":
                query = query.filter(models.ConversationSession.inquiry_status.in_(["WAITING_SUPPORT", "WAITING_CUSTOMER"]))
            elif status == "RESOLVED":
                query = query.filter(models.ConversationSession.inquiry_status == "RESOLVED")
            elif status == "CANCELLED":
                query = query.filter(models.ConversationSession.inquiry_status == "CANCELLED")
            else:
                query = query.filter(models.ConversationSession.status == status)
        else:
            # Default active statuses (not resolved or cancelled)
            query = query.filter(
                models.ConversationSession.inquiry_status.in_(["ACTIVE", "PAUSED", "WAITING_SUPPORT", "WAITING_CUSTOMER"]) |
                (models.ConversationSession.inquiry_status == None) & models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER", "PAUSED"])
            )
        
    if category_id:
        if category_id == "none":
            query = query.filter(models.ConversationSession.category_id == None)
        else:
            query = query.filter(models.ConversationSession.category_id == category_id)
            
    sessions = query.order_by(models.ConversationSession.last_message_at.desc()).all()
    
    def safe_isoformat(dt):
        if not dt: return None
        if isinstance(dt, str): return dt
        return dt.isoformat()

    result = []
    for s in sessions:
        last_msg = db.query(models.ConversationMessage).filter(
            models.ConversationMessage.session_id == s.id
        ).order_by(models.ConversationMessage.timestamp.desc()).first()
        
        result.append({
            "id": s.id,
            "inquiry_number": s.inquiry_number or "INQ-00000",
            "customer_name": s.customer_name or "Unknown",
            "customer_phone": s.customer_phone,
            "status": s.status,
            "inquiry_status": s.inquiry_status or "ACTIVE",
            "category_id": s.category_id,
            "conversation_type": s.conversation_type or "INQUIRY",
            "is_deleted": bool(s.is_deleted),
            "category": {
                "id": s.category.id,
                "name": s.category.name,
                "color": s.category.color
            } if s.category else None,
            "created_at": safe_isoformat(s.created_at),
            "updated_at": safe_isoformat(s.updated_at),
            "last_message_at": safe_isoformat(s.last_message_at),
            "completed_at": safe_isoformat(s.completed_at),
            "paused_at": safe_isoformat(s.paused_at),
            "resumed_at": safe_isoformat(s.resumed_at),
            "cancelled_at": safe_isoformat(s.cancelled_at),
            "last_message": last_msg.message if last_msg else "No messages"
        })
        
    return result

@router.get("/conversations/{session_id}/messages")
def get_conversation_messages(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    messages = db.query(models.ConversationMessage).filter(
        models.ConversationMessage.session_id == session.id
    ).order_by(models.ConversationMessage.timestamp.asc()).all()
    
    def safe_isoformat(dt):
        if not dt: return None
        if isinstance(dt, str): return dt
        return dt.isoformat()

    return [{
        "id": m.id,
        "sender_type": m.sender_type,
        "message": m.message,
        "timestamp": safe_isoformat(m.timestamp)
    } for m in messages]

@router.post("/conversations/{session_id}/reply")
def send_conversation_reply(
    session_id: str,
    req: SendReplyRequest,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    if session.status in ["RESOLVED", "ARCHIVED"]:
        raise HTTPException(status_code=400, detail="Cannot reply to a completed/archived conversation")

    # Generate Inquiry number on demand if not present for some reason
    if not session.inquiry_number:
        session.inquiry_number = models.ConversationSession.generate_unique_number(db)
        db.flush()

    # Wrap reply in professional CRM template
    shop_name = getattr(current_shop, "shop_name", None) or getattr(current_shop, "name", "Support")
    formatted_msg = (
        "━━━━━━━━━━━━━━━\n"
        f"📩 {shop_name} Support Reply\n"
        f"Inquiry No: {session.inquiry_number}\n\n"
        f"{req.message}\n\n"
        "Thank you,\n"
        f"{shop_name} Support\n"
        "━━━━━━━━━━━━━━━"
    )

    # Send WhatsApp message
    try:
        from ..services.whatsapp_service import send_whatsapp_message
        send_whatsapp_message(current_shop, session.customer_phone, formatted_msg)
    except Exception as e:
        import logging
        logging.getLogger("levix.conversations").error(f"Failed to send whatsapp message: {e}")
        raise HTTPException(status_code=500, detail="Failed to send message via WhatsApp")

    # Save to DB
    new_msg = models.ConversationMessage(
        session_id=session.id,
        sender_type="OWNER",
        message=formatted_msg
    )
    db.add(new_msg)
    
    # Transition status to WAITING_CUSTOMER
    session.status = "WAITING_CUSTOMER"
    session.inquiry_status = "WAITING_CUSTOMER"
    session.updated_at = sa_func.now()
    session.last_message_at = sa_func.now()
    db.commit()
    
    # Broadcast update to client SSE
    broadcast_event(current_shop.id, "conversation_updated")
    
    return {"status": "success", "id": new_msg.id, "message": formatted_msg}

@router.post("/conversations/{session_id}/complete")
def complete_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    session.status = "RESOLVED"
    session.inquiry_status = "RESOLVED"
    session.completed_at = sa_func.now()
    session.updated_at = sa_func.now()
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    
    return {"status": "success"}

# --- CATEGORY ENDPOINTS ---

@router.get("/conversations/categories")
def get_categories(
    identity: UserIdentity = Depends(require_permission("inbox_view")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    categories = db.query(models.ConversationCategory).filter(
        models.ConversationCategory.shop_id == current_shop.id
    ).order_by(models.ConversationCategory.name.asc()).all()
    
    return [{
        "id": c.id,
        "name": c.name,
        "color": c.color
    } for c in categories]

@router.post("/conversations/categories")
def create_category(
    req: CategoryCreateRequest,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    
    # Check if duplicate name in the same shop
    existing = db.query(models.ConversationCategory).filter(
        models.ConversationCategory.shop_id == current_shop.id,
        models.ConversationCategory.name == req.name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category name already exists")
        
    new_cat = models.ConversationCategory(
        shop_id=current_shop.id,
        name=req.name,
        color=req.color
    )
    db.add(new_cat)
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "id": new_cat.id, "name": new_cat.name, "color": new_cat.color}

@router.put("/conversations/categories/{category_id}")
def update_category(
    category_id: str,
    req: CategoryCreateRequest,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    cat = db.query(models.ConversationCategory).filter(
        models.ConversationCategory.id == category_id,
        models.ConversationCategory.shop_id == current_shop.id
    ).first()
    
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
        
    # Check name uniqueness if changed
    if cat.name != req.name:
        existing = db.query(models.ConversationCategory).filter(
            models.ConversationCategory.shop_id == current_shop.id,
            models.ConversationCategory.name == req.name
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Category name already exists")
            
    cat.name = req.name
    cat.color = req.color
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success"}

@router.delete("/conversations/categories/{category_id}")
def delete_category(
    category_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    cat = db.query(models.ConversationCategory).filter(
        models.ConversationCategory.id == category_id,
        models.ConversationCategory.shop_id == current_shop.id
    ).first()
    
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
        
    db.delete(cat)
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success"}

@router.post("/conversations/{session_id}/category")
def assign_category(
    session_id: str,
    req: AssignCategoryRequest,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    if req.category_id:
        # Verify category exists in this shop
        cat = db.query(models.ConversationCategory).filter(
            models.ConversationCategory.id == req.category_id,
            models.ConversationCategory.shop_id == current_shop.id
        ).first()
        if not cat:
            raise HTTPException(status_code=400, detail="Invalid category_id")
        
        session.category_id = req.category_id
        
        # Type Migration Trigger
        cat_name_upper = cat.name.upper()
        if "ORDER" in cat_name_upper:
            session.conversation_type = "ORDER"
            # Migrate inquiry_number prefix if needed
            if session.inquiry_number and session.inquiry_number.startswith("INQ-"):
                session.inquiry_number = session.inquiry_number.replace("INQ-", "ORD-")
            elif not session.inquiry_number:
                session.inquiry_number = models.ConversationSession.generate_unique_order_number(db)
        elif "INQUIRY" in cat_name_upper:
            session.conversation_type = "INQUIRY"
            # Migrate inquiry_number prefix if needed
            if session.inquiry_number and session.inquiry_number.startswith("ORD-"):
                session.inquiry_number = session.inquiry_number.replace("ORD-", "INQ-")
            elif not session.inquiry_number:
                session.inquiry_number = models.ConversationSession.generate_unique_number(db)
    else:
        session.category_id = None
        
    session.updated_at = sa_func.now()
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "conversation_type": session.conversation_type, "inquiry_number": session.inquiry_number}

@router.post("/conversations/{session_id}/status")
def update_session_status(
    session_id: str,
    req: UpdateStatusRequest,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    valid_statuses = ["NEW", "ONGOING", "WAITING_CUSTOMER", "RESOLVED", "ARCHIVED"]
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {valid_statuses}")
        
    session.status = req.status
    if req.status in ["RESOLVED", "ARCHIVED"]:
        session.inquiry_status = "RESOLVED"
        session.completed_at = sa_func.now()
    elif req.status == "WAITING_CUSTOMER":
        session.inquiry_status = "WAITING_CUSTOMER"
    elif req.status == "ONGOING":
        session.inquiry_status = "ACTIVE"
    elif req.status == "PAUSED":
        session.inquiry_status = "PAUSED"
        session.paused_at = sa_func.now()
    else:
        session.completed_at = None
        
    session.updated_at = sa_func.now()
    db.commit()
    
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success"}

# --- HARDENING ACTIONS (SOFT DELETE, HARD DELETE, LIFECYCLE CONTROLS) ---

@router.post("/conversations/{session_id}/delete")
def soft_delete_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    session.is_deleted = True
    session.deleted_at = sa_func.now()
    db.commit()
    
    # Broadcast event
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Conversation moved to Trash"}

@router.post("/conversations/{session_id}/restore")
def restore_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    session.is_deleted = False
    session.deleted_at = None
    db.commit()
    
    # Broadcast event
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Conversation restored to Inbox"}

@router.delete("/conversations/{session_id}/hard-delete")
def hard_delete_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    db.delete(session)
    db.commit()
    
    # Broadcast event
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Conversation permanently deleted"}

@router.post("/conversations/{session_id}/pause")
def pause_bot_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    from ..services.flow_controller import FlowController, TransitionRequest
    # Enforce paused via FlowController
    try:
        FlowController.transition_state(db, TransitionRequest(
            current_state=session.inquiry_status or "ACTIVE",
            requested_state="PAUSED",
            flow_type="inquiry",
            actor="owner",
            trigger_source="command",
            session_id=session.id,
            shop_id=current_shop.id,
            customer_phone=session.customer_phone
        ))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Bot paused"}

@router.post("/conversations/{session_id}/resume")
def resume_bot_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    from ..services.flow_controller import FlowController, TransitionRequest
    try:
        FlowController.transition_state(db, TransitionRequest(
            current_state=session.inquiry_status or "PAUSED",
            requested_state="ACTIVE",
            flow_type="inquiry",
            actor="owner",
            trigger_source="command",
            session_id=session.id,
            shop_id=current_shop.id,
            customer_phone=session.customer_phone
        ))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Bot resumed"}

@router.post("/conversations/{session_id}/cancel")
def cancel_conversation(
    session_id: str,
    identity: UserIdentity = Depends(require_permission("inbox_reply")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    session = db.query(models.ConversationSession).filter(
        models.ConversationSession.id == session_id,
        models.ConversationSession.shop_id == current_shop.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    from ..services.flow_controller import FlowController, TransitionRequest
    try:
        FlowController.transition_state(db, TransitionRequest(
            current_state=session.inquiry_status or "ACTIVE",
            requested_state="CANCELLED",
            flow_type="inquiry",
            actor="owner",
            trigger_source="command",
            session_id=session.id,
            shop_id=current_shop.id,
            customer_phone=session.customer_phone
        ))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    broadcast_event(current_shop.id, "conversation_updated")
    return {"status": "success", "message": "Conversation cancelled"}
