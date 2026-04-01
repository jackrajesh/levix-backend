import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.database import Base, get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import models
from app.utils.encryption import decrypt

TEST_DB_URL = "sqlite:///./tmp/test_admin.db"
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
    shop = models.Shop(
        shop_name="Test Shop",
        owner_name="Owner",
        email="admin_test@shop.com",
        password_hash="hashed",
    )
    db.add(shop)
    db.commit()
    db.refresh(shop)
    
    yield shop
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

def test_connect_whatsapp_valid(setup_db):
    shop = setup_db
    payload = {
        "shop_id": shop.id,
        "phone_number_id": "999888777",
        "access_token": "RAW_SUPER_SECRET_TOKEN",
        "business_account_id": "BIZ123"
    }
    response = client.post("/admin/connect-whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "WhatsApp connected successfully"}
    
    # Check DB to ensure it's encrypted
    db = TestingSessionLocal()
    db_shop = db.query(models.Shop).filter(models.Shop.id == shop.id).first()
    
    assert db_shop.whatsapp_phone_number_id == "999888777"
    assert db_shop.whatsapp_business_account_id == "BIZ123"
    assert db_shop.whatsapp_access_token.startswith("gAAAA")
    
    # Check decryption works
    decrypted_token = decrypt(db_shop.whatsapp_access_token)
    assert decrypted_token == "RAW_SUPER_SECRET_TOKEN"
    db.close()

def test_connect_whatsapp_invalid_shop():
    payload = {
        "shop_id": 9999,
        "phone_number_id": "111",
        "access_token": "TOKEN"
    }
    response = client.post("/admin/connect-whatsapp", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_integration_webhook_routing_after_connect(setup_db):
    shop = setup_db
    # 1. Connect whatsapp
    connect_payload = {
        "shop_id": shop.id,
        "phone_number_id": "ROUTING_TEST_ID",
        "access_token": "ROUTING_TOKEN"
    }
    response = client.post("/admin/connect-whatsapp", json=connect_payload)
    assert response.status_code == 200

    # 2. Test webhook routing
    with patch("app.services.whatsapp_service.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        
        webhook_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "ROUTING_TEST_ID"},
                        "messages": [{"from": "911234567890", "text": {"body": "hello"}}]
                    }
                }]
            }]
        }
        
        webhook_res = client.post("/webhook", json=webhook_payload)
        assert webhook_res.status_code == 200
        assert webhook_res.json() == {"status": "ok"}
        
        # Verify it routed properly and decrypted the token for sending
        mock_post.assert_called_once()
        call_headers = mock_post.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer ROUTING_TOKEN"
