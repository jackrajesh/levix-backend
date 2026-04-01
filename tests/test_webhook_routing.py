"""
Integration tests for per-shop WhatsApp webhook routing.

Tests:
  1. Happy path  — known phone_number_id → shop resolved, send called with correct creds
  2. Unknown id  — unknown phone_number_id → returns ok, no crash
  3. Missing id  — no metadata → returns ok, no crash
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app import models
from app.utils.encryption import encrypt

# ─── In-memory test database ─────────────────────────────────────────────────
TEST_DB_URL = "sqlite:///./tmp/test_webhook.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Create a test shop with encrypted token
    shop = models.Shop(
        shop_name="Test Shop",
        owner_name="Owner",
        email="test@shop.com",
        password_hash="hashed",
        whatsapp_phone_number_id="TEST_PHONE_ID",
        whatsapp_access_token=encrypt("FAKE_TOKEN_123"),
    )
    db.add(shop)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)

WEBHOOK_PAYLOAD_TEMPLATE = {
    "entry": [{
        "changes": [{
            "value": {
                "metadata": {"phone_number_id": "{phone_id}"},
                "messages": [{
                    "from": "911234567890",
                    "text": {"body": "hello"}
                }]
            }
        }]
    }]
}


def build_payload(phone_id: str) -> dict:
    import json
    raw = json.dumps(WEBHOOK_PAYLOAD_TEMPLATE).replace('"{phone_id}"', f'"{phone_id}"')
    return json.loads(raw)


# ─── Test 1: Happy path ───────────────────────────────────────────────────────
def test_known_phone_number_id_resolves_shop():
    """Webhook with a known phone_number_id should match the shop and attempt send."""
    with patch("app.services.whatsapp_service.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "TEST_PHONE_ID"},
                        "messages": [{"from": "911234567890", "text": {"body": "hello"}}]
                    }
                }]
            }]
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        # Ensure WhatsApp API was called
        mock_post.assert_called_once()
        call_headers = mock_post.call_args.kwargs["headers"]
        assert "Bearer FAKE_TOKEN_123" == call_headers["Authorization"]


# ─── Test 2: Unknown phone_number_id ─────────────────────────────────────────
def test_unknown_phone_number_id_returns_ok():
    """Webhook with an unknown phone_number_id should return ok without crashing."""
    with patch("app.services.whatsapp_service.requests.post") as mock_post:
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "UNKNOWN_ID_999"},
                        "messages": [{"from": "911234567890", "text": {"body": "rice"}}]
                    }
                }]
            }]
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_post.assert_not_called()  # No send attempted


# ─── Test 3: Missing metadata ─────────────────────────────────────────────────
def test_missing_metadata_returns_ok():
    """Payload with no metadata key should not crash."""
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{"from": "911234567890", "text": {"body": "hello"}}]
                }
            }]
        }]
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
