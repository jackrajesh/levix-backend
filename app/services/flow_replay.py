"""
flow_replay.py — LEVIX Flow Timeline Replay Service
=====================================================
READ-ONLY forensic reconstruction of any conversation flow's history.

Purpose:
- Debug failures and corrupted states
- Inspect webhook duplication events
- Analyze recovery checkpoints
- Audit AI transition decisions
- Support customer dispute resolution

ABSOLUTE RULE: This service NEVER mutates live state.
               It opens READ-ONLY queries only.
               It NEVER writes to the event log or any session.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from ..database import SessionLocal
from .. import models

logger = logging.getLogger("levix.flow_replay")


class FlowReplay:
    """
    Read-only forensic replay of conversation flows.
    All methods return structured dictionaries — never ORM objects.
    """

    @staticmethod
    def replay_flow_timeline(
        session_id: str,
        include_webhooks: bool = True,
        include_messages: bool = True,
    ) -> dict:
        """
        Reconstruct the full event timeline for a given conversation session.

        Returns:
            {
              "session_id": ...,
              "events": [...],        # ConversationEventLog entries
              "messages": [...],      # ConversationMessage entries (if include_messages)
              "webhooks": [...],      # WebhookAuditLog entries (if include_webhooks)
              "summary": {...},       # Counts and key stats
              "error": None or str    # Set if reconstruction partially failed
            }
        """
        db = None
        result = {
            "session_id": session_id,
            "events": [],
            "messages": [],
            "webhooks": [],
            "summary": {},
            "error": None,
            "replayed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            db = SessionLocal()

            # ── 1. Event log entries (primary timeline)
            try:
                events = db.query(models.ConversationEventLog).filter(
                    models.ConversationEventLog.session_id == session_id
                ).order_by(models.ConversationEventLog.created_at.asc()).all()

                result["events"] = [
                    {
                        "event_id": e.event_id,
                        "event_type": e.event_type,
                        "previous_state": e.previous_state,
                        "next_state": e.next_state,
                        "trigger_source": e.trigger_source,
                        "trigger_reason": e.trigger_reason,
                        "actor_type": e.actor_type,
                        "actor_id": e.actor_id,
                        "recovery_type": e.recovery_type,
                        "checkpoint_id": e.checkpoint_id,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                        "metadata": e.metadata_json or {},
                    }
                    for e in events
                ]
            except Exception as exc:
                logger.error(f"[FLOW_REPLAY] Failed to fetch events for session={session_id}: {exc}")
                result["error"] = f"event_fetch_failed: {exc}"

            # ── 2. Conversation messages
            if include_messages:
                try:
                    # ConversationSession might have a different id vs session_id string
                    # Try both: direct session.id match and event_log session_id
                    conv_session = db.query(models.ConversationSession).filter(
                        models.ConversationSession.id == session_id
                    ).first()
                    if not conv_session:
                        # Try via inquiry number
                        conv_session = db.query(models.ConversationSession).filter(
                            models.ConversationSession.inquiry_number == session_id
                        ).first()

                    if conv_session:
                        msgs = db.query(models.ConversationMessage).filter(
                            models.ConversationMessage.session_id == conv_session.id
                        ).order_by(models.ConversationMessage.timestamp.asc()).all()

                        result["messages"] = [
                            {
                                "id": m.id,
                                "sender_type": m.sender_type,
                                "message": m.message,
                                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                                "whatsapp_message_id": m.whatsapp_message_id,
                            }
                            for m in msgs
                        ]
                except Exception as exc:
                    logger.error(f"[FLOW_REPLAY] Failed to fetch messages for session={session_id}: {exc}")

            # ── 3. Webhook audit log entries
            if include_webhooks:
                try:
                    # Match webhooks that mention this session's customer phone
                    # First get the customer phone from event log
                    customer_phone = None
                    if result["events"]:
                        for ev in result["events"]:
                            pass  # already have dict — get from event objects
                    # Re-query for phone
                    first_event = db.query(models.ConversationEventLog).filter(
                        models.ConversationEventLog.session_id == session_id,
                        models.ConversationEventLog.customer_phone.isnot(None),
                    ).first()
                    if first_event:
                        customer_phone = first_event.customer_phone

                    if customer_phone:
                        # Get shop_id too for scoped query
                        shop_id = first_event.shop_id
                        wh_entries = db.query(models.WebhookAuditLog).filter(
                            models.WebhookAuditLog.sender_phone == customer_phone,
                            models.WebhookAuditLog.shop_id == shop_id,
                        ).order_by(models.WebhookAuditLog.created_at.asc()).all()

                        result["webhooks"] = [
                            {
                                "webhook_event_id": w.webhook_event_id,
                                "wa_message_id": w.wa_message_id,
                                "message_type": w.message_type,
                                "is_duplicate": w.is_duplicate,
                                "processing_result": w.processing_result,
                                "route_target": w.route_target,
                                "response_status": w.response_status,
                                "processing_latency_ms": w.processing_latency_ms,
                                "error_summary": w.error_summary,
                                "created_at": w.created_at.isoformat() if w.created_at else None,
                            }
                            for w in wh_entries
                        ]
                except Exception as exc:
                    logger.error(f"[FLOW_REPLAY] Failed to fetch webhooks for session={session_id}: {exc}")

            # ── 4. Summary
            result["summary"] = {
                "total_events": len(result["events"]),
                "total_messages": len(result["messages"]),
                "total_webhooks": len(result["webhooks"]),
                "duplicate_webhooks": sum(1 for w in result["webhooks"] if w.get("is_duplicate")),
                "blocked_transitions": sum(1 for e in result["events"] if e["event_type"] == "STATE_TRANSITION_BLOCKED"),
                "flow_errors": sum(1 for e in result["events"] if e["event_type"] in ("FLOW_ERROR", "FLOW_CORRUPTED")),
                "recoveries": sum(1 for e in result["events"] if e["event_type"] in ("FLOW_RECOVERED", "FLOW_CHECKPOINT_RESTORED")),
                "state_journey": [
                    {"from": e["previous_state"], "to": e["next_state"], "at": e["created_at"]}
                    for e in result["events"]
                    if e["previous_state"] and e["next_state"] and e["previous_state"] != e["next_state"]
                ],
            }

        except Exception as exc:
            logger.error(f"[FLOW_REPLAY] Critical failure for session={session_id}: {exc}")
            result["error"] = f"replay_failed: {exc}"
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

        return result

    @staticmethod
    def get_session_current_state(session_id: str) -> dict:
        """
        Read current state from the last event log entry.
        Safe diagnostic read — no mutations.
        """
        db = None
        try:
            db = SessionLocal()
            last_event = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.session_id == session_id,
                models.ConversationEventLog.next_state.isnot(None),
            ).order_by(models.ConversationEventLog.created_at.desc()).first()

            if last_event:
                return {
                    "session_id": session_id,
                    "last_known_state": last_event.next_state,
                    "last_event_type": last_event.event_type,
                    "last_transition_at": last_event.created_at.isoformat() if last_event.created_at else None,
                }
            return {"session_id": session_id, "last_known_state": None, "last_event_type": None}
        except Exception as exc:
            logger.error(f"[FLOW_REPLAY] get_session_current_state failed: {exc}")
            return {"session_id": session_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
