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
from ..services.whatsapp_service import send_whatsapp_message, send_whatsapp_button_message, send_whatsapp_list_message
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
    shop_id: Optional[str] = None


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
        
    return await sse_events_handler(request, shop_id)


@router.get("/webhook")
async def verify_webhook(request: Request):
    print("\n" + "="*50)
    print("[WEBHOOK HIT] GET /webhook received")
    print(f"[WEBHOOK HEADERS] {request.headers}")
    print("="*50 + "\n", flush=True)

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK] Verification successful")
        return PlainTextResponse(content=challenge)

    return PlainTextResponse(content="Verification failed")


@router.post("/webhook")
async def webhook_endpoint(request: Request, db: Session = Depends(get_db)):
    """
    Unified WhatsApp Webhook Handler.
    Now fully powered by the 4-Layer AIRouter + WebhookGuard.
    """
    print("\n" + "="*50)
    print("[WEBHOOK HIT] POST /webhook received")
    print(f"[WEBHOOK HEADERS] {request.headers}")
    
    # Forensic timer — non-blocking
    _audit_id = None
    _wh_start_ms = None
    try:
        import time as _time
        _wh_start_ms = _time.monotonic()
    except Exception:
        pass

    # 1. Parse Payload
    try:
        raw_body = await request.body()
        print(f"[WEBHOOK PAYLOAD] {raw_body.decode('utf-8')}")
        print("="*50 + "\n", flush=True)
        
        data = await request.json()
        logger.info(f"[WEBHOOK] Raw payload parsed (keys): {list(data.keys())}")
    except Exception as e:
        print(f"[WEBHOOK ERROR] Failed to parse JSON payload: {e}", flush=True)
        logger.warning("[WEBHOOK] Failed to parse JSON payload")
        return {"status": "invalid_json"}

    # 2. Webhook Guard (Deduplication & Validation)
    from ..core.webhook_guard import WebhookGuard
    if not WebhookGuard.validate_payload(data):
        logger.info("[WEBHOOK] Payload failed validation or ignored by guard.")
        return {"status": "ignored"}

    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        # Handle Status Updates
        if "statuses" in value:
            logger.info("[WEBHOOK] Status update received.")
            return {"status": "ok"}

        # Extract Message Details
        if "messages" not in value:
            logger.info("[WEBHOOK] No messages in payload changes.")
            return {"status": "ok"}
            
        msg = value["messages"][0]
        if isinstance(msg, str):
            logger.error("[WEBHOOK] Expected dict for message but got string.")
            return {"status": "error", "message": "Invalid message structure"}
            
        wa_id = msg["id"]
        sender = msg["from"]
        metadata = value.get("metadata", {})
        phone_number_id = metadata.get("phone_number_id")

        logger.info(f"[WEBHOOK] Processing message ID: {wa_id} from: {sender} (Phone ID: {phone_number_id})")

        if not phone_number_id:
            logger.warning("[WEBHOOK] Missing phone_number_id in metadata.")
            return {"status": "no_phone_id"}

        # Extract Text (before audit record so we can log it)
        raw_message = ""
        msg_type = msg.get("type", "unknown")
        if msg_type == "text":
            raw_message = msg["text"]["body"]
        elif msg_type == "button":
            raw_message = msg["button"]["text"]
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            logger.info(f"[WEBHOOK] Interactive type: {interactive.get('type')}")
            if interactive.get("type") == "button_reply":
                raw_message = interactive.get("button_reply", {}).get("id")
                logger.info(f"[WEBHOOK] Button reply ID: {raw_message}")
            elif interactive.get("type") == "list_reply":
                raw_message = interactive.get("list_reply", {}).get("id")
                logger.info(f"[WEBHOOK] List reply ID: {raw_message}")
        
        logger.info(f"[WEBHOOK] Message type: {msg_type}, Content: '{raw_message}'")

        # ── WEBHOOK FORENSICS AUDIT RECORD (surgical addition) ───────────
        _is_duplicate_in_mem = WebhookGuard.is_duplicate(wa_id)
        try:
            from ..services.webhook_forensics import WebhookForensics
            _audit_id = WebhookForensics.record_received(
                wa_message_id=wa_id,
                sender_phone=sender,
                phone_number_id=phone_number_id or "",
                message_type=msg_type,
                raw_message_text=raw_message or "",
                raw_body=raw_body,
                shop_id=None,           # resolved below; updated via update_result
                is_duplicate=_is_duplicate_in_mem,
            )
            from ..services.event_logger import ConversationEventLogger
            ConversationEventLogger.log_webhook_received(
                shop_id=None, customer_phone=sender,
                wa_message_id=wa_id,
                metadata={"phone_number_id": phone_number_id, "msg_type": msg_type},
            )
        except Exception as _fa_err:
            logger.debug(f"[WEBHOOK] Forensics record failed (non-blocking): {_fa_err}")
        # ── END WEBHOOK FORENSICS ─────────────────────────────────────────

        # In-memory deduplication (existing guard)
        if _is_duplicate_in_mem:
            logger.info(f"[WEBHOOK] Duplicate message ID ignored: {wa_id}")
            try:
                from ..services.event_logger import ConversationEventLogger
                ConversationEventLogger.log_webhook_duplicate_blocked(
                    shop_id=None, customer_phone=sender, wa_message_id=wa_id,
                )
            except Exception:
                pass
            return {"status": "duplicate"}

        if not raw_message:
            logger.warning(f"[WEBHOOK] Empty or unsupported message type: {msg_type}")
            return {"status": "no_text"}

        # 3. Resolve Shop
        shop = get_shop_by_phone_number_id(phone_number_id, db)
        if not shop:
            logger.error(f"[WEBHOOK] No shop found for phone_id: {phone_number_id}")
            try:
                from ..services.webhook_forensics import WebhookForensics
                if _audit_id:
                    WebhookForensics.update_result(_audit_id, "no_shop")
            except Exception:
                pass
            return {"status": "no_shop"}

        logger.info(f"[WEBHOOK] Resolved Shop: {shop.id} ({shop.shop_name})")

        # 4. Process via RouterEngine
        reply = None
        _route_target = "router_engine"
        try:
            logger.info(f"[WEBHOOK] Invoking RouterEngine for {sender}")
            reply = RouterEngine.process_message(db, shop.id, sender, raw_message)
            reply_type = type(reply).__name__
            reply_len = len(reply) if isinstance(reply, str) else (len(reply.get("body", "")) if isinstance(reply, dict) else 0)
            logger.info(f"[WEBHOOK] RouterEngine returned reply. Type={reply_type}, BodyLen={reply_len}")
        except Exception as ai_err:
            import traceback
            logger.error(f"[WEBHOOK] Router failed: {ai_err}\n{traceback.format_exc()}")
            reply = "Vanakkam! We've received your message and our team will get back to you shortly."
            _route_target = "fallback"
            # Log the flow error event
            try:
                from ..services.event_logger import ConversationEventLogger
                ConversationEventLogger.log_flow_error(
                    session_id=None, shop_id=shop.id,
                    customer_phone=sender,
                    error_summary=str(ai_err)[:500],
                )
            except Exception:
                pass

        # 5. Send Reply
        _response_status = "no_reply"
        if reply:
            logger.info(f"[WEBHOOK] Sending WhatsApp reply to {sender}")
            try:
                if isinstance(reply, str):
                    send_whatsapp_message(shop, sender, reply)
                elif isinstance(reply, dict):
                    msg_type_out = reply.get("type", "text")
                    if msg_type_out == "text":
                        send_whatsapp_message(shop, sender, reply.get("body"))
                    elif msg_type_out == "button":
                        send_whatsapp_button_message(
                            shop, sender, 
                            body_text=reply.get("body"), 
                            buttons=reply.get("buttons"), 
                            header_text=reply.get("header"), 
                            footer_text=reply.get("footer")
                        )
                    elif msg_type_out == "list":
                        send_whatsapp_list_message(
                            shop, sender, 
                            body_text=reply.get("body"), 
                            button_text=reply.get("button_text"), 
                            sections=reply.get("sections"), 
                            header_text=reply.get("header"), 
                            footer_text=reply.get("footer")
                        )
                _response_status = "sent"
            except Exception as _send_err:
                logger.error(f"[WEBHOOK] WhatsApp send failed: {_send_err}")
                _response_status = "send_failed"
            
            # 6. Real-time Dashboard Update
            broadcast_event(shop.id, "pending_updated")
            broadcast_event(shop.id, "conversation_updated")
            
            logger.info(f"[WEBHOOK] Broadcasts sent for Shop {shop.id}")

        # ── FORENSICS RESULT UPDATE (surgical addition) ───────────────────
        try:
            from ..services.webhook_forensics import WebhookForensics
            _latency_ms = None
            if _wh_start_ms is not None:
                import time as _time2
                _latency_ms = int((_time2.monotonic() - _wh_start_ms) * 1000)
            if _audit_id:
                WebhookForensics.update_result(
                    audit_id=_audit_id,
                    processing_result="success",
                    route_target=_route_target,
                    response_status=_response_status,
                    processing_latency_ms=_latency_ms,
                    shop_id=shop.id if shop else None,
                )
        except Exception as _fu_err:
            logger.debug(f"[WEBHOOK] Forensics update failed (non-blocking): {_fu_err}")
        # ── END FORENSICS RESULT UPDATE ───────────────────────────────────

    except Exception as e:
        import traceback
        logger.error(f"[WEBHOOK CRITICAL ERROR] {e}\n{traceback.format_exc()}")
        # ── FORENSICS ERROR RECORD ────────────────────────────────────────
        try:
            from ..services.webhook_forensics import WebhookForensics
            if _audit_id:
                WebhookForensics.update_result(
                    audit_id=_audit_id,
                    processing_result="error",
                    error_summary=str(e)[:500],
                )
        except Exception:
            pass
        # ── END FORENSICS ERROR RECORD ────────────────────────────────────
    
    return {"status": "success"}


