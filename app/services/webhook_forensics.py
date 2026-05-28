"""
webhook_forensics.py — LEVIX Webhook Forensic Audit Service
=============================================================
Records a full audit trail for every inbound webhook event.
Enhanced deduplication backed by DB persistence (survives process restarts).
Tracks latency, retries, routing, and processing outcomes.

RULES:
- NEVER blocks webhook processing on failure
- NEVER raises to caller
- Uses isolated DB sessions
- Idempotent: same wa_message_id always returns same audit entry
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ..database import SessionLocal
from .. import models

logger = logging.getLogger("levix.webhook_forensics")


class WebhookForensics:
    """
    Forensic audit service for inbound WhatsApp webhook events.
    """

    @staticmethod
    def _hash_payload(raw_body: bytes) -> str:
        """SHA-256 hash of raw body for forensic fingerprinting."""
        try:
            return hashlib.sha256(raw_body).hexdigest()[:64]
        except Exception:
            return "hash_failed"

    @staticmethod
    def record_received(
        wa_message_id: str,
        sender_phone: str,
        phone_number_id: str,
        message_type: str,
        raw_message_text: str,
        raw_body: bytes,
        shop_id: Optional[str] = None,
        is_duplicate: bool = False,
    ) -> Optional[int]:
        """
        Create a WebhookAuditLog entry when a webhook is first received.
        Returns the DB row id for later update, or None on failure.
        """
        db = None
        try:
            db = SessionLocal()
            entry = models.WebhookAuditLog(
                shop_id=shop_id,
                wa_message_id=wa_message_id,
                sender_phone=sender_phone,
                phone_number_id=phone_number_id,
                payload_hash=WebhookForensics._hash_payload(raw_body),
                message_type=message_type,
                raw_message_text=(raw_message_text or "")[:500],   # truncate for safety
                is_duplicate=is_duplicate,
                processing_result="received",
                created_at=datetime.now(timezone.utc),
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            audit_id = entry.id
            logger.debug(f"[WH_FORENSICS] Audit entry created: id={audit_id} wa_id={wa_message_id}")
            return audit_id
        except Exception as exc:
            logger.error(f"[WH_FORENSICS] Failed to record webhook receipt: {exc}")
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

    @staticmethod
    def update_result(
        audit_id: int,
        processing_result: str,          # "success", "error", "ignored", "no_shop", "duplicate"
        route_target: Optional[str] = None,
        response_status: Optional[str] = None,
        outbound_wa_id: Optional[str] = None,
        processing_latency_ms: Optional[int] = None,
        error_summary: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> bool:
        """
        Update processing outcome on an existing WebhookAuditLog row.
        Returns True on success, False on failure (non-blocking).
        """
        if not audit_id:
            return False
        db = None
        try:
            db = SessionLocal()
            entry = db.query(models.WebhookAuditLog).filter(models.WebhookAuditLog.id == audit_id).first()
            if not entry:
                logger.warning(f"[WH_FORENSICS] Audit entry id={audit_id} not found for update.")
                return False
            entry.processing_result = processing_result
            if route_target:
                entry.route_target = route_target
            if response_status:
                entry.response_status = response_status
            if outbound_wa_id:
                entry.outbound_wa_id = outbound_wa_id
            if processing_latency_ms is not None:
                entry.processing_latency_ms = processing_latency_ms
            if error_summary:
                entry.error_summary = error_summary[:1000]
            if shop_id and not entry.shop_id:
                entry.shop_id = shop_id
            db.commit()
            logger.debug(f"[WH_FORENSICS] Audit entry id={audit_id} updated → result={processing_result}")
            return True
        except Exception as exc:
            logger.error(f"[WH_FORENSICS] Failed to update audit entry id={audit_id}: {exc}")
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            return False
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def is_db_duplicate(wa_message_id: str) -> bool:
        """
        DB-backed duplicate check (survives restarts, unlike in-memory cache).
        Returns True if this wa_message_id was already successfully processed.
        """
        if not wa_message_id:
            return False
        db = None
        try:
            db = SessionLocal()
            existing = db.query(models.WebhookAuditLog).filter(
                models.WebhookAuditLog.wa_message_id == wa_message_id,
                models.WebhookAuditLog.processing_result == "success",
            ).first()
            return existing is not None
        except Exception as exc:
            logger.error(f"[WH_FORENSICS] DB duplicate check failed for {wa_message_id}: {exc}")
            # Fail open — let the webhook through if we can't check
            return False
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def get_recent_failure_rate(shop_id: str, window_minutes: int = 60) -> dict:
        """
        Returns webhook failure statistics for a shop in the last N minutes.
        Used by diagnostics — never blocks webhook processing.
        """
        db = None
        try:
            db = SessionLocal()
            from sqlalchemy import func as sa_func
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
            rows = db.query(
                models.WebhookAuditLog.processing_result,
                sa_func.count(models.WebhookAuditLog.id).label("cnt")
            ).filter(
                models.WebhookAuditLog.shop_id == shop_id,
                models.WebhookAuditLog.created_at >= cutoff,
            ).group_by(models.WebhookAuditLog.processing_result).all()

            stats = {r.processing_result: r.cnt for r in rows}
            total = sum(stats.values())
            errors = stats.get("error", 0) + stats.get("no_shop", 0)
            return {
                "total": total,
                "success": stats.get("success", 0),
                "error": errors,
                "duplicate": stats.get("duplicate", 0),
                "ignored": stats.get("ignored", 0),
                "error_rate_pct": round(errors / total * 100, 1) if total > 0 else 0,
            }
        except Exception as exc:
            logger.error(f"[WH_FORENSICS] Failed to get failure rate for shop {shop_id}: {exc}")
            return {"error": "stats_unavailable"}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass


class WebhookTimer:
    """Lightweight context manager to measure processing latency."""
    def __init__(self):
        self._start = None

    def start(self):
        self._start = time.monotonic()
        return self

    def elapsed_ms(self) -> int:
        if self._start is None:
            return 0
        return int((time.monotonic() - self._start) * 1000)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        pass
