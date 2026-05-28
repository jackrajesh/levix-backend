import requests
from cryptography.fernet import Fernet, InvalidToken
import os


# Initialize Fernet (same key used everywhere)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None


def safe_decrypt(token: str) -> str:
    """
    Try to decrypt token. If it's already plain text, return as-is.
    """
    if not fernet:
        return token

    try:
        return fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        # Token is not encrypted (old DB data)
        return token


def _send_whatsapp_payload(shop, to_number: str, payload: dict) -> None:
    """
    Base function to send any WhatsApp payload.
    """
    shop_name = getattr(shop, "shop_name", "<unknown>")
    phone_number_id = getattr(shop, "whatsapp_phone_number_id", None)
    stored_token = getattr(shop, "whatsapp_access_token", None)

    if not phone_number_id:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_phone_number_id. Skipping send.")
        return

    if not stored_token:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_access_token. Skipping send.")
        return

    access_token = safe_decrypt(stored_token)
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        print(f"[WhatsApp] Sent to {to_number} via shop '{shop_name}' — HTTP {response.status_code}")

        if response.status_code != 200:
            print(f"[WhatsApp] API error response: {response.text}")

    except requests.exceptions.Timeout:
        print(f"[WhatsApp] Request timed out for shop '{shop_name}'")

    except Exception as e:
        print(f"[WhatsApp] Failed to send message for shop '{shop_name}': {e}")


def resolve_branding(text: str, shop) -> str:
    if not text:
        return text
    shop_name = getattr(shop, "shop_name", None)
    if not shop_name:
        # Fallback to shop.name if shop_name is not set
        shop_name = getattr(shop, "name", "Our Store")
    # Replace placeholders and hardcoded Levix default text
    text = text.replace("{shop.name}", shop_name)
    text = text.replace("LEVIX Support", f"{shop_name} Support")
    text = text.replace("LEVIX Support Reply", f"{shop_name} Support Reply")
    text = text.replace("LEVIX", shop_name)
    text = text.replace("Levix", shop_name)
    return text


def send_whatsapp_message(shop, to_number: str, message: str) -> None:
    """
    Send a standard text message.
    """
    if not message:
        return

    message = resolve_branding(message, shop)
    
    # Log outbound message event to event logger
    try:
        from .event_logger import ConversationEventLogger
        ConversationEventLogger.log_template_message(
            shop_id=getattr(shop, "id", None),
            customer_phone=to_number,
            template_name="TEXT_MESSAGE",
            status="SENT",
            metadata={"body": message}
        )
    except Exception:
        pass

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }
    _send_whatsapp_payload(shop, to_number, payload)


def send_whatsapp_button_message(shop, to_number: str, body_text: str, buttons: list, header_text: str = None, footer_text: str = None) -> None:
    """
    Send an interactive reply button message (max 3 buttons).
    buttons is a list of strings.
    """
    body_text = resolve_branding(body_text, shop)
    if header_text:
        header_text = resolve_branding(header_text, shop)
    if footer_text:
        footer_text = resolve_branding(footer_text, shop)

    # Log button message event
    try:
        from .event_logger import ConversationEventLogger
        ConversationEventLogger.log_template_message(
            shop_id=getattr(shop, "id", None),
            customer_phone=to_number,
            template_name="BUTTON_MESSAGE",
            status="SENT",
            metadata={"body": body_text, "buttons": buttons}
        )
    except Exception:
        pass

    if not buttons:
        return send_whatsapp_message(shop, to_number, body_text)

    # WhatsApp allows max 3 buttons
    buttons = buttons[:3]

    interactive_buttons = []
    for btn in buttons:
        if isinstance(btn, dict):
            btn_id = btn.get("id")
            btn_title = btn.get("title")
        else:
            btn_id = btn
            btn_title = btn
            
        btn_title = resolve_branding(str(btn_title), shop)
        interactive_buttons.append({
            "type": "reply",
            "reply": {
                "id": str(btn_id)[:256],
                "title": btn_title[:20]
            }
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": interactive_buttons}
        }
    }

    if header_text:
        payload["interactive"]["header"] = {"type": "text", "text": header_text}
    if footer_text:
        payload["interactive"]["footer"] = {"text": footer_text}

    _send_whatsapp_payload(shop, to_number, payload)


def send_whatsapp_list_message(shop, to_number: str, body_text: str, button_text: str, sections: list, header_text: str = None, footer_text: str = None) -> None:
    """
    Send an interactive list message.
    sections is a list of dicts: [{"title": "Section Title", "rows": [{"id": "1", "title": "Row Title", "description": "Desc"}]}]
    """
    body_text = resolve_branding(body_text, shop)
    button_text = resolve_branding(button_text, shop)
    if header_text:
        header_text = resolve_branding(header_text, shop)
    if footer_text:
        footer_text = resolve_branding(footer_text, shop)

    # Log list message event
    try:
        from .event_logger import ConversationEventLogger
        ConversationEventLogger.log_template_message(
            shop_id=getattr(shop, "id", None),
            customer_phone=to_number,
            template_name="LIST_MESSAGE",
            status="SENT",
            metadata={"body": body_text, "button_text": button_text, "sections_count": len(sections)}
        )
    except Exception:
        pass

    # Resolve branding inside sections
    for sec in sections:
        sec["title"] = resolve_branding(sec.get("title", ""), shop)
        for row in sec.get("rows", []):
            row["title"] = resolve_branding(row.get("title", ""), shop)[:24]
            if "description" in row and row["description"]:
                row["description"] = resolve_branding(row["description"], shop)[:72]

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],  # Max 20 chars
                "sections": sections
            }
        }
    }

    if header_text:
        payload["interactive"]["header"] = {"type": "text", "text": header_text}
    if footer_text:
        payload["interactive"]["footer"] = {"text": footer_text}

    _send_whatsapp_payload(shop, to_number, payload)