import requests
from ..utils.encryption import decrypt


def send_whatsapp_message(shop, to_number: str, message: str) -> None:
    """
    Send a WhatsApp message using the given shop's credentials.

    The access token is stored encrypted; it is decrypted here at send-time
    and never logged. All failure modes are handled gracefully.
    """
    shop_name = getattr(shop, "shop_name", "<unknown>")

    # Guard: missing phone_number_id
    phone_number_id = getattr(shop, "whatsapp_phone_number_id", None)
    if not phone_number_id:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_phone_number_id. Skipping send.")
        return

    # Guard: missing access token
    encrypted_token = getattr(shop, "whatsapp_access_token", None)
    if not encrypted_token:
        print(f"[WhatsApp] Shop '{shop_name}' has no whatsapp_access_token. Skipping send.")
        return

    if not message:
        return

    # Decrypt token — returns None on failure, never raises
    access_token = decrypt(encrypted_token)
    if access_token is None:
        print(f"[WhatsApp] Token decryption failed for shop '{shop_name}'. Skipping send.")
        return

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
