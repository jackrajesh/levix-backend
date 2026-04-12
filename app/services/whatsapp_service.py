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


def send_whatsapp_message(shop, to_number: str, message: str) -> None:
    """
    Send a WhatsApp message using the given shop's credentials.
    Handles both encrypted and plain tokens safely.
    """
    shop_name = getattr(shop, "shop_name", "<unknown>")

    # Guard: missing phone_number_id
    phone_number_id = getattr(shop, "whatsapp_phone_number_id", None)
    if not phone_number_id:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_phone_number_id. Skipping send.")
        return

    # Guard: missing access token
    stored_token = getattr(shop, "whatsapp_access_token", None)
    if not stored_token:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_access_token. Skipping send.")
        return

    if not message:
        return

    # 🔥 FIX: safe decrypt (handles both encrypted + plain tokens)
    access_token = safe_decrypt(stored_token)

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
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