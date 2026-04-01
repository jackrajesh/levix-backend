import os
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from .. import models
from ..database import get_db
from ..services.sse import sse_events_handler, broadcast_event
from ..services.shop_service import get_shop_by_phone_number_id
from ..services.whatsapp_service import send_whatsapp_message
from ..services.product_service import (
    normalize_message,
    get_greeting_response,
    add_log_db,
    filter_filler_words,
    get_product_state,
    match_multiple_products,
)
from ..utils import generate_reply

VERIFY_TOKEN = "levix123"

router = APIRouter(tags=["webhooks"])


class WebhookRequest(BaseModel):
    customer_message: str
    shop_id: Optional[int] = None


@router.get("/events")
async def events_endpoint(request: Request):
    return await sse_events_handler(request)


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
    # ── 0. Request ID for end-to-end log tracing ─────────────────────────────
    req_id = str(uuid.uuid4())[:8]

    # ── 1. Parse payload ──────────────────────────────────────────────────────
    raw_message = None
    sender = None
    phone_number_id = None

    try:
        data = await request.json()
        print(f"[{req_id}] Webhook received payload")

        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # Extract phone_number_id for shop routing
        metadata = value.get("metadata", {})
        phone_number_id = metadata.get("phone_number_id")
        print(f"[{req_id}] phone_number_id: {phone_number_id}")

        if "messages" not in value:
            return {"status": "ok"}

        message_obj = value["messages"][0]
        raw_message = message_obj.get("text", {}).get("body", "").strip()
        sender = message_obj.get("from")

        print(f"[{req_id}] Incoming message from {sender}: {raw_message}")

    except Exception as e:
        print(f"[{req_id}] Error parsing payload: {e}")
        return {"status": "ok"}

    if not raw_message or not sender:
        return {"status": "ok"}

    # ── 2. Resolve shop by phone_number_id ────────────────────────────────────
    shop = get_shop_by_phone_number_id(phone_number_id, db)

    if not shop:
        print(f"[{req_id}] No shop found for phone_number_id: {phone_number_id}. Ignoring message.")
        return {"status": "ok"}

    print(f"[{req_id}] Matched shop: {shop.shop_name} (id={shop.id})")
    shop_id = shop.id

    # ── 3. Greeting check ─────────────────────────────────────────────────────
    greeting = get_greeting_response(raw_message)
    if greeting:
        print("Greeting detected:", greeting)
        send_whatsapp_message(shop, sender, greeting)
        return {"status": "ok"}

    # ── 4. Normalize and match products ───────────────────────────────────────
    normalized = normalize_message(raw_message)
    if not normalized:
        return {"status": "ok"}

    cleaned_message = filter_filler_words(normalized)

    matched_items, unknowns, limit_exceeded = match_multiple_products(cleaned_message, db, shop_id)

    if limit_exceeded:
        reply = "⚠️ Limit reached. Please ask under 12 products."
        print("Limit exceeded, sending warning.")
        send_whatsapp_message(shop, sender, reply)
        return {"status": "ok"}

    # ── 5. Build reply ────────────────────────────────────────────────────────
    reply = ""
    if matched_items:
        if len(matched_items) == 1:
            item = matched_items[0]
            add_log_db(db, shop_id, item.name, item.status, item.id)
            print("DEBUG PRODUCT MATCH:", item.name)
            state = getattr(item, "state", get_product_state(item))
            reply = generate_reply(item, state)
        else:
            reply = "LEVIX ⚡\n"
            for item in matched_items:
                add_log_db(db, shop_id, item.name, item.status, item.id)
                reply += f"{item.name} - ₹{item.price}\n"
            reply += "\nAnything else you need?"

    # ── 6. Handle unknown products ────────────────────────────────────────────
    if unknowns:
        for unknown in unknowns:
            p_name = unknown.capitalize()
            exists = db.query(models.PendingRequest).filter(
                models.PendingRequest.shop_id == shop_id,
                models.PendingRequest.product_name == p_name,
            ).first()

            if not exists:
                db.add(models.PendingRequest(
                    shop_id=shop_id,
                    product_name=p_name,
                    customer_message=raw_message,
                    request_type="customer",
                ))
                add_log_db(db, shop_id, p_name, "pending")

        db.commit()
        broadcast_event("pending_created")

        unknown_msg = f"\n\nWe will check availability for: {', '.join([u.capitalize() for u in unknowns])}"
        if not reply:
            reply = "Thanks for asking. Let me check and get back to you soon."
        reply += unknown_msg

    if reply:
        print("Generated reply:", reply)
        send_whatsapp_message(shop, sender, reply)
        return {"status": "ok"}

    # ── 7. Fallback: generic short/unrecognised messages ─────────────────────
    pending_product = cleaned_message.capitalize()
    common_short_words = ["this", "that", "there", "where", "what", "which", "some", "any", "vanakam", "vanakkam"]
    if pending_product.lower() in common_short_words:
        send_whatsapp_message(shop, sender, "Please wait, checking with the owner.")
        return {"status": "ok"}

    db.add(models.PendingRequest(
        shop_id=shop_id,
        product_name=pending_product,
        customer_message=raw_message,
        request_type="customer",
    ))
    db.commit()
    add_log_db(db, shop_id, pending_product, "pending")
    broadcast_event("pending_created")
    send_whatsapp_message(shop, sender, "Thanks for asking.\n\nLet me check with the shop owner and get back to you soon.")

    return {"status": "ok"}
