import sys
import os
import pytest
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from sqlalchemy import text
from app.database import SessionLocal, engine
from app import models
from app.services.flow_controller import FlowController, TransitionRequest
from app.services.event_logger import ConversationEventLogger, EventType
from app.services.webhook_forensics import WebhookForensics
from app.services.flow_diagnostics import FlowDiagnosticsService
from app.services.flow_replay import FlowReplay

def setup_test_shop(db):
    shop_id = "observability_test_shop"
    
    # Clean up existing test data
    db.execute(text(f"DELETE FROM conversation_event_log WHERE shop_id = '{shop_id}'"))
    db.execute(text(f"DELETE FROM webhook_audit_log WHERE shop_id = '{shop_id}'"))
    db.execute(text(f"DELETE FROM conversation_sessions WHERE shop_id = '{shop_id}'"))
    db.execute(text(f"DELETE FROM ai_conversation_sessions WHERE shop_id = '{shop_id}'"))
    db.execute(text(f"DELETE FROM shops WHERE id = '{shop_id}'"))
    db.commit()
    
    shop = models.Shop(id=shop_id, shop_name="Observability Test Shop", email="obs_test@example.com")
    db.add(shop)
    db.commit()
    return shop_id

def test_observability_layer():
    print("\n=== STARTING OBSERVABILITY LAYER TESTS ===")
    db = SessionLocal()
    shop_id = setup_test_shop(db)
    phone = "919999999990"
    session_id = "test_sess_001"
    
    # --- 1. TEST FLOW CONTROLLER & TRANSITIONS ---
    print("\n1. Testing FlowController Transition Validations...")
    
    # 1.1 Valid Transition
    req1 = TransitionRequest(
        current_state="ACTIVE", requested_state="PAUSED", 
        flow_type="inquiry", actor="customer", trigger_source="command",
        session_id=session_id, shop_id=shop_id
    )
    res1 = FlowController.validate_transition(req1)
    assert res1.allowed == True, "ACTIVE to PAUSED should be allowed"
    
    # 1.2 Illegal Transition
    req2 = TransitionRequest(
        current_state="ACTIVE", requested_state="INVALID_STATE", 
        flow_type="inquiry", actor="customer", trigger_source="command",
        session_id=session_id, shop_id=shop_id
    )
    res2 = FlowController.validate_transition(req2)
    assert res2.allowed == False, "ACTIVE to INVALID_STATE should be rejected"
    
    # 1.3 Terminal State Enforcement
    req3 = TransitionRequest(
        current_state="CANCELLED", requested_state="ACTIVE", 
        flow_type="inquiry", actor="customer", trigger_source="command",
        session_id=session_id, shop_id=shop_id
    )
    res3 = FlowController.validate_transition(req3)
    assert res3.allowed == False, "CANCELLED to ACTIVE should be rejected"
    assert res3.severity == "critical"
    
    # 1.4 AI Transition Rejection (AI cannot directly force RESOLVED)
    req4 = TransitionRequest(
        current_state="ACTIVE", requested_state="RESOLVED", 
        flow_type="inquiry", actor="ai", trigger_source="ai",
        session_id=session_id, shop_id=shop_id
    )
    res4 = FlowController.validate_transition(req4)
    assert res4.allowed == False, "AI directly resolving should be blocked"
    assert res4.reason == "ai_cannot_directly_terminate: requires controller validation"

    print("✅ FlowController validations passed")
    
    # --- 2. TEST EVENT LOGGER ---
    print("\n2. Testing Conversation Event Logger...")
    
    evt1 = ConversationEventLogger.log_flow_created(session_id, shop_id, phone)
    assert evt1 is not None, "Flow creation event log failed"
    
    evt2 = ConversationEventLogger.log_flow_paused(session_id, shop_id, phone, previous_state="ACTIVE")
    assert evt2 is not None, "Flow paused event log failed"
    
    evt3 = ConversationEventLogger.log_confusion_signal(session_id, shop_id, phone, confusion_count=3)
    assert evt3 is not None, "Confusion signal log failed"
    
    # Fetch events
    events = db.query(models.ConversationEventLog).filter(models.ConversationEventLog.session_id == session_id).all()
    assert len(events) == 3, "Expected 3 events in DB"
    
    print("✅ Event Logger passed")

    # --- 3. TEST WEBHOOK FORENSICS & IDEMPOTENCY ---
    print("\n3. Testing Webhook Forensics & Idempotency...")
    
    wa_id_1 = "wamid.1234567890"
    
    # 3.1 Record new webhook
    audit_id_1 = WebhookForensics.record_received(
        wa_message_id=wa_id_1, sender_phone=phone, phone_number_id="123",
        message_type="text", raw_message_text="Hello", raw_body=b"{\"test\": 1}",
        shop_id=shop_id, is_duplicate=False
    )
    assert audit_id_1 is not None, "Failed to record webhook"
    
    # 3.2 Update result
    WebhookForensics.update_result(audit_id_1, processing_result="success", processing_latency_ms=120)
    
    # 3.3 Test Idempotency (should be duplicate now)
    is_dup = WebhookForensics.is_db_duplicate(wa_id_1)
    assert is_dup == True, "Webhook should be flagged as DB duplicate"
    
    # 3.4 Record Duplicate
    audit_id_2 = WebhookForensics.record_received(
        wa_message_id=wa_id_1, sender_phone=phone, phone_number_id="123",
        message_type="text", raw_message_text="Hello", raw_body=b"{\"test\": 1}",
        shop_id=shop_id, is_duplicate=True
    )
    WebhookForensics.update_result(audit_id_2, processing_result="duplicate")
    
    wh_logs = db.query(models.WebhookAuditLog).filter(models.WebhookAuditLog.wa_message_id == wa_id_1).all()
    assert len(wh_logs) == 2, "Expected 2 webhook logs for this wa_id"
    assert wh_logs[0].processing_result == "success"
    assert wh_logs[1].processing_result == "duplicate"
    
    print("✅ Webhook Forensics passed")

    # --- 4. TEST FLOW DIAGNOSTICS ---
    print("\n4. Testing Flow Diagnostics...")
    
    # Set up some session data for diagnostics
    s1 = models.ConversationSession(id="diag_s1", shop_id=shop_id, customer_phone=phone, inquiry_status="ACTIVE", last_message_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    s2 = models.ConversationSession(id="diag_s2", shop_id=shop_id, customer_phone=phone, inquiry_status="PAUSED")
    db.add(s1)
    db.add(s2)
    db.commit()
    
    # 4.1 Stuck Flows
    stuck_result = FlowDiagnosticsService.detect_stuck_flows(shop_id, timeout_minutes=60)
    assert stuck_result["stuck_count"] >= 1, "Should detect at least 1 stuck flow"
    
    # 4.2 Webhook Health
    wh_health = FlowDiagnosticsService.get_webhook_health(shop_id)
    assert wh_health["total"] >= 2, "Webhook health should reflect recent webhooks"
    
    # 4.3 Confusion Escalation
    confusion_result = FlowDiagnosticsService.detect_repeated_confusion(shop_id, window_hours=24)
    assert confusion_result["customers_needing_escalation"] == 0, "No customer should have >= 3 distinct sessions with confusion yet"
    
    print("✅ Flow Diagnostics passed")
    
    # --- 5. TEST FLOW REPLAY ---
    print("\n5. Testing Flow Replay Integrity...")
    
    replay = FlowReplay.replay_flow_timeline(session_id)
    assert replay["session_id"] == session_id
    assert len(replay["events"]) == 3
    assert replay["summary"]["total_events"] == 3
    
    current_state_info = FlowReplay.get_session_current_state(session_id)
    assert current_state_info["last_known_state"] == "PAUSED" # from evt2
    
    print("✅ Flow Replay passed")
    
    # Cleanup
    setup_test_shop(db)
    db.close()
    
    print("\n=== ALL OBSERVABILITY TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    test_observability_layer()
