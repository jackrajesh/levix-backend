import os
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

import json
import datetime
import traceback
from .auth import get_current_shop
from .. import models
from ..database import get_db
from ..services.sse import sse_events_handler, broadcast_event
from ..services.shop_service import get_shop_by_phone_number_id
from ..services.whatsapp_service import send_whatsapp_message
from ..services.product_service import (
    normalize_message,
    get_greeting_response,
    add_log_db,
    get_product_state,
)
from ..services.ai_matcher import ai_match_products, generate_ai_reply
from ..services.ai_router import AIRouter
from ..services.router_engine import RouterEngine
from ..services.order_controller import (
    get_or_create_customer_session, 
    handle_order_flow, 
    update_customer_session,
    generate_booking_id,
    generate_order_id
)
from ..utils import generate_reply, filter_filler_words

import logging
VERIFY_TOKEN = "levix123"

router = APIRouter(tags=["webhooks"])
logger = logging.getLogger("levix.webhooks")


class WebhookRequest(BaseModel):
    customer_message: str
    shop_id: Optional[int] = None


from jose import jwt
from ..auth import SECRET_KEY, ALGORITHM

from fastapi import Query

@router.get("/events")
async def events_endpoint(request: Request, token: str = Query(None)):
    """
    Server-Sent Events endpoint for real-time dashboard updates.
    Optimized to avoid holding a DB session open during the long-running stream.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token missing")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        shop_id = payload.get("shop_id")
        
        if not shop_id:
            # Fallback for older tokens (use sub/email)
            email = payload.get("sub")
            if not email:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            from ..database import SessionLocal
            from .. import models
            db = SessionLocal()
            try:
                # Handle team member emails if they are prefixed
                email_str = str(email)
                if email_str.startswith("tm_"):
                    member = db.query(models.TeamMember).filter(models.TeamMember.email == email_str).first()
                    shop_id = member.shop_id if member else None
                else:
                    shop = db.query(models.Shop).filter(models.Shop.email == email_str).first()
                    shop_id = shop.id if shop else None
            finally:
                db.close()

        if not shop_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
            
    except Exception as e:
        print(f"[SSE] Auth Failure: {e}")
        raise HTTPException(status_code=401, detail="Auth Failed")
        
    return await sse_events_handler(request, int(shop_id))


@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    return PlainTextResponse(content="Verification failed")


@router.post("/webhook")
async def webhook_endpoint(request: Request, db: Session = Depends(get_db)):
    """
    Unified WhatsApp Webhook Handler.
    Now fully powered by the 4-Layer AIRouter + WebhookGuard.
    """
    # 1. Parse Payload
    try:
        data = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    # 2. Webhook Guard (Deduplication & Validation)
    from ..core.webhook_guard import WebhookGuard
    if not WebhookGuard.validate_payload(data):
        return {"status": "ignored"}

    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        # Handle Status Updates
        if "statuses" in value:
            return {"status": "ok"}

        # Extract Message Details
        if "messages" not in value:
            return {"status": "ok"}
            
        msg = value["messages"][0]
        wa_id = msg["id"]
        sender = msg["from"]
        metadata = value.get("metadata", {})
        phone_number_id = metadata.get("phone_number_id")

        if not phone_number_id:
            return {"status": "no_phone_id"}

        # 2. Webhook Guard (Deduplication)
        if WebhookGuard.is_duplicate(wa_id):
            return {"status": "duplicate"}

        # Extract Text
        raw_message = ""
        if msg["type"] == "text":
            raw_message = msg["text"]["body"]
        elif msg["type"] == "button":
            raw_message = msg["button"]["text"]

        if not raw_message:
            return {"status": "no_text"}

        # 3. Resolve Shop
        shop = get_shop_by_phone_number_id(phone_number_id, db)
        if not shop:
            logger.error(f"[WEBHOOK] No shop found for phone_id: {phone_number_id}")
            return {"status": "no_shop"}

        # 4. Process via AIRouter (Phases 1-8)
        # Timeout protection wrapped inside AIRouter or here
        import asyncio
        try:
            reply = RouterEngine.process_message(db, shop.id, sender, raw_message)
        except Exception as ai_err:
            logger.error(f"[WEBHOOK] Router failed: {ai_err}")
            reply = "Vanakkam! 🙏 We've received your message and our team will get back to you shortly."

        # 5. Send Reply
        if reply:
            send_whatsapp_message(shop, sender, reply)
            
            # 6. Real-time Dashboard Update
            # Phase 2: Mandatory Logs
            broadcast_event(shop.id, "pending_updated")
            broadcast_event(shop.id, "new_ai_lead")
            
            logger.info(f"[INBOX] Lead rendered for Shop {shop.id} - Broadcast sent")

    except Exception as e:
        import traceback
        logger.error(f"[WEBHOOK CRITICAL ERROR] {e}\n{traceback.format_exc()}")
    
    return {"status": "success"}
