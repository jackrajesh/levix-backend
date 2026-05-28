"""
flow_diagnostics.py — LEVIX Event-Driven Production Diagnostics
================================================================
Runtime observability service for detecting stuck flows, orphaned sessions,
SSE failures, webhook anomalies, and repeated confusion signals.

RULES:
- NO polling loops
- NO aggressive intervals
- All methods are event-driven on-demand calls
- All methods are read-only (except for marking alerts)
- NEVER blocks business logic
- NEVER raises to caller
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from ..database import SessionLocal
from .. import models

logger = logging.getLogger("levix.flow_diagnostics")

# Thresholds (tunable)
STUCK_FLOW_MINUTES     = 60    # Inquiry active but no message for N minutes
ORPHAN_SESSION_HOURS   = 24    # AIConversationSession with no update for N hours
CONFUSION_THRESHOLD    = 3     # Confusion events before escalation signal
MAX_WEBHOOK_ERROR_PCT  = 30    # Alert if error rate exceeds this %


class FlowDiagnosticsService:
    """
    On-demand production diagnostics. Called after events, not on a timer.
    All outputs are structured dicts — safe for API responses.
    """

    @staticmethod
    def get_active_flow_count(shop_id: str) -> dict:
        """Count of active inquiry sessions per shop."""
        db = None
        try:
            db = SessionLocal()
            active = db.query(models.ConversationSession).filter(
                models.ConversationSession.shop_id == shop_id,
                models.ConversationSession.inquiry_status == "ACTIVE",
            ).count()
            paused = db.query(models.ConversationSession).filter(
                models.ConversationSession.shop_id == shop_id,
                models.ConversationSession.inquiry_status == "PAUSED",
            ).count()
            waiting = db.query(models.ConversationSession).filter(
                models.ConversationSession.shop_id == shop_id,
                models.ConversationSession.inquiry_status.in_(["WAITING_SUPPORT", "WAITING_CUSTOMER"]),
            ).count()
            return {
                "shop_id": shop_id,
                "active": active,
                "paused": paused,
                "waiting": waiting,
                "total_open": active + paused + waiting,
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] get_active_flow_count failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def detect_stuck_flows(shop_id: str, timeout_minutes: int = STUCK_FLOW_MINUTES) -> dict:
        """
        Find inquiries that are ACTIVE but have had no message activity.
        Does NOT mutate state — only returns diagnostic data.
        """
        db = None
        try:
            db = SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
            stuck = db.query(models.ConversationSession).filter(
                models.ConversationSession.shop_id == shop_id,
                models.ConversationSession.inquiry_status == "ACTIVE",
                models.ConversationSession.last_message_at < cutoff,
            ).all()

            stuck_list = [
                {
                    "session_id": s.id,
                    "inquiry_number": s.inquiry_number,
                    "customer_phone": s.customer_phone,
                    "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
                    "minutes_idle": int((datetime.now(timezone.utc) - s.last_message_at).total_seconds() / 60)
                                    if s.last_message_at else None,
                }
                for s in stuck
            ]
            return {
                "shop_id": shop_id,
                "timeout_minutes": timeout_minutes,
                "stuck_count": len(stuck_list),
                "stuck_flows": stuck_list,
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] detect_stuck_flows failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def detect_orphaned_sessions(shop_id: str, timeout_hours: int = ORPHAN_SESSION_HOURS) -> dict:
        """
        Find AIConversationSessions marked active but never updated recently.
        These are 'ghost' sessions that weren't properly closed.
        """
        db = None
        try:
            db = SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
            orphans = db.query(models.AIConversationSession).filter(
                models.AIConversationSession.shop_id == shop_id,
                models.AIConversationSession.is_active == True,
                models.AIConversationSession.updated_at < cutoff,
            ).all()

            orphan_list = [
                {
                    "session_id": s.session_id,
                    "customer_phone": s.customer_phone,
                    "guided_state": (s.collected_fields or {}).get("guided_state", "unknown"),
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                    "hours_idle": int((datetime.now(timezone.utc) - s.updated_at).total_seconds() / 3600)
                                  if s.updated_at else None,
                }
                for s in orphans
            ]
            return {
                "shop_id": shop_id,
                "timeout_hours": timeout_hours,
                "orphan_count": len(orphan_list),
                "orphaned_sessions": orphan_list,
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] detect_orphaned_sessions failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def detect_repeated_confusion(shop_id: str, window_hours: int = 24) -> dict:
        """
        Find customers who have triggered confusion signals repeatedly.
        Used to detect customers who need human escalation.
        """
        db = None
        try:
            db = SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

            confusion_events = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.shop_id == shop_id,
                models.ConversationEventLog.event_type == "CONFUSION_SIGNAL_TRIGGERED",
                models.ConversationEventLog.created_at >= cutoff,
            ).all()

            # Group by customer_phone
            by_customer: dict = {}
            for ev in confusion_events:
                phone = ev.customer_phone or "unknown"
                by_customer.setdefault(phone, []).append(ev.session_id)

            escalation_needed = [
                {"customer_phone": phone, "confusion_count": len(sessions), "session_ids": list(set(sessions))}
                for phone, sessions in by_customer.items()
                if len(sessions) >= CONFUSION_THRESHOLD
            ]

            return {
                "shop_id": shop_id,
                "window_hours": window_hours,
                "total_confusion_events": len(confusion_events),
                "customers_needing_escalation": len(escalation_needed),
                "escalation_list": escalation_needed,
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] detect_repeated_confusion failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def get_webhook_health(shop_id: str, window_minutes: int = 60) -> dict:
        """
        Event-driven webhook health report for a shop.
        Triggers an admin alert if error rate exceeds threshold.
        """
        try:
            from .webhook_forensics import WebhookForensics
            stats = WebhookForensics.get_recent_failure_rate(shop_id, window_minutes)
            error_rate = stats.get("error_rate_pct", 0)
            alert_triggered = error_rate >= MAX_WEBHOOK_ERROR_PCT
            if alert_triggered:
                logger.warning(f"[DIAGNOSTICS] High webhook error rate for shop={shop_id}: {error_rate}%")
                FlowDiagnosticsService._create_admin_alert(
                    shop_id=shop_id,
                    alert_type="high_webhook_error_rate",
                    details=stats,
                )
            return {**stats, "alert_triggered": alert_triggered, "shop_id": shop_id}
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] get_webhook_health failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}

    @staticmethod
    def get_blocked_transitions(shop_id: str, window_hours: int = 24) -> dict:
        """Returns blocked transitions in the event log for this shop."""
        db = None
        try:
            db = SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
            blocked = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.shop_id == shop_id,
                models.ConversationEventLog.event_type == "STATE_TRANSITION_BLOCKED",
                models.ConversationEventLog.created_at >= cutoff,
            ).order_by(models.ConversationEventLog.created_at.desc()).limit(50).all()

            return {
                "shop_id": shop_id,
                "window_hours": window_hours,
                "blocked_count": len(blocked),
                "blocked_transitions": [
                    {
                        "event_id": e.event_id,
                        "session_id": e.session_id,
                        "previous_state": e.previous_state,
                        "next_state": e.next_state,
                        "reason": e.trigger_reason,
                        "actor_type": e.actor_type,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in blocked
                ],
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] get_blocked_transitions failed for {shop_id}: {exc}")
            return {"shop_id": shop_id, "error": str(exc)}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def get_crm_safe_metadata(session_id: str, shop_id: str) -> dict:
        """
        Safe CRM metadata for the dashboard — no internal exceptions, no DB schema,
        no confidence scores, no stack traces exposed.
        """
        db = None
        try:
            db = SessionLocal()
            conv_session = db.query(models.ConversationSession).filter(
                models.ConversationSession.id == session_id,
                models.ConversationSession.shop_id == shop_id,
            ).first()

            if not conv_session:
                return {"error": "session_not_found"}

            # Count recent events for this session
            event_count = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.session_id == session_id,
            ).count()

            last_event = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.session_id == session_id,
            ).order_by(models.ConversationEventLog.created_at.desc()).first()

            confusion_count = db.query(models.ConversationEventLog).filter(
                models.ConversationEventLog.session_id == session_id,
                models.ConversationEventLog.event_type == "CONFUSION_SIGNAL_TRIGGERED",
            ).count()

            return {
                "flow_id": session_id,
                "inquiry_number": conv_session.inquiry_number,
                "flow_state": conv_session.inquiry_status,
                "lifecycle_status": conv_session.status,
                "last_transition": last_event.event_type if last_event else None,
                "last_transition_at": last_event.created_at.isoformat() if last_event and last_event.created_at else None,
                "checkpoint_available": False,  # reserved for future checkpoint system
                "confusion_count": confusion_count,
                "recovery_available": conv_session.inquiry_status == "PAUSED",
                "total_events": event_count,
            }
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] get_crm_safe_metadata failed: {exc}")
            return {"error": "diagnostics_unavailable"}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def _create_admin_alert(shop_id: str, alert_type: str, details: dict) -> None:
        """Writes an AdminAlert — silently fails if DB unavailable."""
        db = None
        try:
            db = SessionLocal()
            existing = db.query(models.AdminAlert).filter(
                models.AdminAlert.shop_id == shop_id,
                models.AdminAlert.alert_type == alert_type,
                models.AdminAlert.resolved == False,
            ).first()
            if existing:
                existing.failure_count += 1
                existing.details = details
            else:
                db.add(models.AdminAlert(
                    shop_id=shop_id,
                    alert_type=alert_type,
                    details=details,
                    failure_count=1,
                ))
            db.commit()
        except Exception as exc:
            logger.error(f"[DIAGNOSTICS] _create_admin_alert failed: {exc}")
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
