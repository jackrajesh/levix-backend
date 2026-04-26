import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal, engine
from app import models
from app.routes import webhooks
from datetime import datetime
from fastapi.testclient import TestClient
from fastapi import FastAPI
import time
from unittest.mock import patch

# Create a test app
app = FastAPI()
app.include_router(webhooks.router)
client = TestClient(app)

# Create tables
models.Base.metadata.create_all(bind=engine)

@patch("requests.post")
def test_spam_detection(mock_post):
    mock_post.return_value.status_code = 200
    db = SessionLocal()
    # Clear existing logs for a test sender
    test_sender = "919999999999"
    db.query(models.MessageLog).filter(models.MessageLog.sender == test_sender).delete()
    db.commit()

    # Send 5 messages quickly
    for i in range(5):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "WHATSAPP_BUSINESS_ACCOUNT_ID", "changes": [{"value": {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "16505551111", "phone_number_id": "123451234512345"}, "contacts": [{"profile": {"name": "Test User"}, "wa_id": test_sender}], "messages": [{"from": test_sender, "id": f"wamid.{i}", "timestamp": "1700000000", "text": {"body": "test message"}, "type": "text"}]}}]}]
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    # 6th message should be blocked as spam
    print("Sending 6th message (should be spam blocked)...")
    payload_6 = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WHATSAPP_BUSINESS_ACCOUNT_ID", "changes": [{"value": {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "16505551111", "phone_number_id": "123451234512345"}, "contacts": [{"profile": {"name": "Test User"}, "wa_id": test_sender}], "messages": [{"from": test_sender, "id": "wamid.6", "timestamp": "1700000000", "text": {"body": "test message 6"}, "type": "text"}]}}]}]
    }
    response_6 = client.post("/webhook", json=payload_6)
    
    # Check if the DB logged 5 messages correctly
    logs = db.query(models.MessageLog).filter(models.MessageLog.sender == test_sender).all()
    count = len(logs)
    print(f"Messages logged in DB: {count}")
    for log in logs:
        print(f"Log timestamp: {log.timestamp}")
        
    ten_seconds_ago = datetime.now(timezone.utc) - timedelta(seconds=10)
    print(f"Ten seconds ago: {ten_seconds_ago}")
    
    assert count == 5, "DB should contain exactly 5 message logs for test sender"
    
    print("Spam Detection Test: PASSED")
    db.close()

if __name__ == "__main__":
    try:
        from datetime import timezone, timedelta
        test_spam_detection()
    except Exception as e:
        print(f"Test failed: {e}")
