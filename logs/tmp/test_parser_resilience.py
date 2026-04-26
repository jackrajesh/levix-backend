import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import models

client = TestClient(app)

def verify_parser_resilience():
    print("--- 1. Testing AI Failure Fallback (Skip AI) ---")
    with patch("app.routes.messages.parse_message_with_ai", return_value=None):
        # Even if AI fails, we use the message "milk" for fuzzy matching
        resp = client.post("/handle-message", json={"message": "milk", "shop_id": 3})
        print(f"Response on AI Failure: {resp.json().get('reply')}")
        assert "check" in resp.json().get("reply").lower() or "yes" in resp.json().get("reply").lower()

    print("\n--- 2. Testing Backward Compatibility (product key) ---")
    mock_ai = {
        "intent": "check_availability",
        "products": [],
        "product": "Chicken Wings",
        "tone": "friendly"
    }
    with patch("app.routes.messages.parse_message_with_ai", return_value=mock_ai):
        resp = client.post("/handle-message", json={"message": "wins", "shop_id": 3})
        reply = resp.json().get("reply")
        print(f"Response with 'product' key: {reply}")
        assert "Chicken Wings" in reply

    print("\n--- 3. Testing Empty Products Fallback (Manual Keywords) ---")
    mock_ai_empty = {
        "intent": "unknown",
        "products": [],
        "tone": "casual"
    }
    with patch("app.routes.messages.parse_message_with_ai", return_value=mock_ai_empty):
        # "briyani" should be extracted from the string manually
        resp = client.post("/handle-message", json={"message": "is briyani there", "shop_id": 3})
        reply = resp.json().get("reply")
        print(f"Response on Empty Products: {reply}")
        assert "Briyani" in reply or "check" in reply

    print("\n--- 4. Testing No Hard Failure UI ---")
    # Even if absolutely nothing matches, we check with the owner
    mock_ai_nothing = {
        "intent": "unknown",
        "products": [],
        "tone": "polite"
    }
    with patch("app.routes.messages.parse_message_with_ai", return_value=mock_ai_nothing):
        resp = client.post("/handle-message", json={"message": "...", "shop_id": 3})
        reply = resp.json().get("reply")
        print(f"Response on Zero Info: {reply}")
        assert "check" in reply.lower()
        assert "sorry" not in reply.lower()

if __name__ == "__main__":
    os.environ["PYTHONPATH"] = "."
    verify_parser_resilience()
