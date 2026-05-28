"""
event_logger.py — LEVIX Conversation Event Logging Service
============================================================
Append-only, fail-safe event audit trail for all conversation lifecycle events.

RULES:
- NEVER blocks the business flow on failure
- NEVER mutates existing state
- NEVER raises exceptions to caller
- All writes are isolated in their own DB transaction
- If logging fails, business flow MUST continue
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
from ..database import SessionLocal
from .. import models

logger = logging.getLogger("levix.event_logger")

# ─────────────────────────────────────────────────────────────────────────────
# EVENT TYPE CONSTANTS
# Single authoritative definition of all valid event types.
# ─────────────────────────────────────────────────────────────────────────────

class EventType:
    FLOW_CREATED               = "FLOW_CREATED"
    FLOW_PAUSED                = "FLOW_PAUSED"
    FLOW_RESUMED               = "FLOW_RESUMED"
    FLOW_CANCELLED             = "FLOW_CANCELLED"
    FLOW_COMPLETED             = "FLOW_COMPLETED"
    FLOW_TIMED_OUT             = "FLOW_TIMED_OUT"
    FLOW_RECOVERED             = "FLOW_RECOVERED"
    FLOW_ERROR                 = "FLOW_ERROR"
    FLOW_CORRUPTED             = "FLOW_CORRUPTED"
    FLOW_CHECKPOINT_CREATED    = "FLOW_CHECKPOINT_CREATED"
    FLOW_CHECKPOINT_RESTORED   = "FLOW_CHECKPOINT_RESTORED"
    WEBHOOK_RECEIVED           = "WEBHOOK_RECEIVED"
    WEBHOOK_DUPLICATE_BLOCKED  = "WEBHOOK_DUPLICATE_BLOCKED"
    MESSAGE_RECEIVED           = "MESSAGE_RECEIVED"
    MESSAGE_SENT               = "MESSAGE_SENT"
    COMMAND_INTERCEPTED        = "COMMAND_INTERCEPTED"
    CONFUSION_SIGNAL_TRIGGERED = "CONFUSION_SIGNAL_TRIGGERED"
    SSE_BROADCAST              = "SSE_BROADCAST"
    STATE_TRANSITION_BLOCKED   = "STATE_TRANSITION_BLOCKED"
    AI_TRANSITION_REQUESTED    = "AI_TRANSITION_REQUESTED"
    AI_TRANSITION_REJECTED     = "AI_TRANSITION_REJECTED"
    AI_TRANSITION_APPROVED     = "AI_TRANSITION_APPROVED"
    AGENT_HANDOFF_STARTED      = "AGENT_HANDOFF_STARTED"
    AGENT_HANDOFF_COMPLETED    = "AGENT_HANDOFF_COMPLETED"

    _ALL = {
        FLOW_CREATED, FLOW_PAUSED, FLOW_RESUMED, FLOW_CANCELLED, FLOW_COMPLETED,
        FLOW_TIMED_OUT, FLOW_RECOVERED, FLOW_ERROR, FLOW_CORRUPTED,
        FLOW_CHECKPOINT_CREATED, FLOW_CHECKPOINT_RESTORED,
        WEBHOOK_RECEIVED, WEBHOOK_DUPLICATE_BLOCKED,
        MESSAGE_RECEIVED, MESSAGE_SENT, COMMAND_INTERCEPTED,
        CONFUSION_SIGNAL_TRIGGERED, SSE_BROADCAST, STATE_TRANSITION_BLOCKED,
        AI_TRANSITION_REQUESTED, AI_TRANSITION_REJECTED, AI_TRANSITION_APPROVED,
        AGENT_HANDOFF_STARTED, AGENT_HANDOFF_COMPLETED,
    }

    @classmethod
    def is_valid(cls, event_type: str) -> bool:
        return event_type in cls._ALL


# ─────────────────────────────────────────────────────────────────────────────
# EVENT LOGGER
# ─────────────────────────────────────────────────────────────────────────────

class ConversationEventLogger:
    """
    Fail-safe, non-blocking event logger for conversation lifecycle events.
    Uses its own isolated DB session to avoid polluting caller transactions.
    """

    @staticmethod
    def log(
        event_type: str,
        session_id: Optional[str] = None,
        flow_id: Optional[str] = None,
        shop_id: Optional[str] = None,
        customer_phone: Optional[str] = None,
        previous_state: Optional[str] = None,
        next_state: Optional[str] = None,
        trigger_source: Optional[str] = None,    # "webhook", "command", "system", "ai", "owner"
        trigger_reason: Optional[str] = None,
        message_id: Optional[str] = None,
        webhook_id: Optional[str] = None,
        actor_type: Optional[str] = None,        # "customer", "owner", "system", "ai"
        actor_id: Optional[str] = None,
        recovery_type: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Write a single event to the audit log.
        Returns the event_id on success, None on failure.
        NEVER raises — failure is silently logged and swallowed.
        """
        if not EventType.is_valid(event_type):
            logger.warning(f"[EVENT_LOGGER] Unknown event_type '{event_type}' — skipping log.")
            return None

        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        db = None
        try:
            db = SessionLocal()
            entry = models.ConversationEventLog(
                event_id=event_id,
                session_id=session_id,
                flow_id=flow_id or session_id,
                shop_id=shop_id,
                customer_phone=customer_phone,
                event_type=event_type,
                previous_state=previous_state,
                next_state=next_state,
                trigger_source=trigger_source,
                trigger_reason=trigger_reason,
                message_id=message_id,
                webhook_id=webhook_id,
                actor_type=actor_type,
                actor_id=actor_id,
                recovery_type=recovery_type,
                checkpoint_id=checkpoint_id,
                metadata_json=metadata or {},
                created_at=datetime.now(timezone.utc),
            )
            db.add(entry)
            db.commit()
            logger.debug(f"[EVENT_LOGGER] {event_type} logged as {event_id} for session={session_id}")
            return event_id
        except Exception as exc:
            # CRITICAL: log failure but NEVER propagate to caller
            logger.error(f"[EVENT_LOGGER] Failed to write event {event_type}: {exc}")
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            return None
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @classmethod
    def log_flow_created(cls, session_id: str, shop_id: str, customer_phone: str, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_CREATED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="system", actor_type="system",
            metadata=metadata,
        )

    @classmethod
    def log_flow_paused(cls, session_id: str, shop_id: str, customer_phone: str,
                        previous_state: str, actor_type: str = "customer",
                        actor_id: str = None, trigger_source: str = "command",
                        trigger_reason: str = None, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_PAUSED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            previous_state=previous_state, next_state="PAUSED",
            trigger_source=trigger_source, trigger_reason=trigger_reason,
            actor_type=actor_type, actor_id=actor_id,
            metadata=metadata,
        )

    @classmethod
    def log_flow_resumed(cls, session_id: str, shop_id: str, customer_phone: str,
                         previous_state: str, actor_type: str = "customer",
                         actor_id: str = None, trigger_source: str = "command",
                         trigger_reason: str = None, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_RESUMED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            previous_state=previous_state, next_state="ACTIVE",
            trigger_source=trigger_source, trigger_reason=trigger_reason,
            actor_type=actor_type, actor_id=actor_id,
            metadata=metadata,
        )

    @classmethod
    def log_flow_cancelled(cls, session_id: str, shop_id: str, customer_phone: str,
                           previous_state: str, actor_type: str = "customer",
                           actor_id: str = None, trigger_source: str = "command",
                           trigger_reason: str = None, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_CANCELLED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            previous_state=previous_state, next_state="CANCELLED",
            trigger_source=trigger_source, trigger_reason=trigger_reason,
            actor_type=actor_type, actor_id=actor_id,
            metadata=metadata,
        )

    @classmethod
    def log_flow_completed(cls, session_id: str, shop_id: str, customer_phone: str,
                           previous_state: str, actor_type: str = "system",
                           trigger_source: str = "command", metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_COMPLETED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            previous_state=previous_state, next_state="RESOLVED",
            trigger_source=trigger_source,
            actor_type=actor_type,
            metadata=metadata,
        )

    @classmethod
    def log_command_intercepted(cls, session_id: str, shop_id: str, customer_phone: str,
                                command: str, inq_num: str, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.COMMAND_INTERCEPTED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="command", trigger_reason=f"command={command} inq={inq_num}",
            actor_type="customer", actor_id=customer_phone,
            metadata=metadata or {"command": command, "inquiry_number": inq_num},
        )

    @classmethod
    def log_state_transition_blocked(cls, session_id: str, shop_id: str,
                                     current_state: str, requested_state: str,
                                     reason: str, actor_type: str = "system",
                                     metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.STATE_TRANSITION_BLOCKED,
            session_id=session_id, shop_id=shop_id,
            previous_state=current_state, next_state=requested_state,
            trigger_source="controller",
            trigger_reason=reason,
            actor_type=actor_type,
            metadata=metadata,
        )

    @classmethod
    def log_webhook_received(cls, shop_id: str, customer_phone: str,
                              wa_message_id: str, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.WEBHOOK_RECEIVED,
            shop_id=shop_id, customer_phone=customer_phone,
            message_id=wa_message_id,
            trigger_source="webhook", actor_type="customer",
            metadata=metadata,
        )

    @classmethod
    def log_webhook_duplicate_blocked(cls, shop_id: str, customer_phone: str,
                                       wa_message_id: str, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.WEBHOOK_DUPLICATE_BLOCKED,
            shop_id=shop_id, customer_phone=customer_phone,
            message_id=wa_message_id,
            trigger_source="webhook", actor_type="system",
            trigger_reason="duplicate_wa_message_id",
            metadata=metadata,
        )

    @classmethod
    def log_agent_handoff(cls, session_id: str, shop_id: str, customer_phone: str,
                          started: bool = True, metadata: dict = None) -> Optional[str]:
        event_type = EventType.AGENT_HANDOFF_STARTED if started else EventType.AGENT_HANDOFF_COMPLETED
        return cls.log(
            event_type=event_type,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="system", actor_type="system",
            metadata=metadata,
        )

    @classmethod
    def log_confusion_signal(cls, session_id: str, shop_id: str, customer_phone: str,
                              confusion_count: int, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.CONFUSION_SIGNAL_TRIGGERED,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="system", actor_type="system",
            trigger_reason=f"confusion_count={confusion_count}",
            metadata=metadata or {"confusion_count": confusion_count},
        )

    @classmethod
    def log_flow_error(cls, session_id: str, shop_id: str, customer_phone: str,
                       error_summary: str, metadata: dict = None) -> Optional[str]:
        return cls.log(
            event_type=EventType.FLOW_ERROR,
            session_id=session_id, shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="system", actor_type="system",
            trigger_reason=error_summary[:500],
            metadata=metadata,
        )

    @classmethod
    def log_template_message(cls, shop_id: str, customer_phone: str, template_name: str, status: str, error_details: str = None, session_id: str = None, metadata: dict = None) -> Optional[str]:
        merged_meta = {"template_name": template_name, "delivery_status": status}
        if error_details:
            merged_meta["error"] = error_details
        if metadata:
            merged_meta.update(metadata)
        return cls.log(
            event_type=EventType.MESSAGE_SENT,
            session_id=session_id,
            shop_id=shop_id,
            customer_phone=customer_phone,
            trigger_source="system",
            actor_type="system",
            trigger_reason=f"template={template_name} status={status}",
            metadata=merged_meta,
        )
