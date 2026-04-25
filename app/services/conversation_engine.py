"""
conversation_engine.py — LEVIX Conversation State Machine
==========================================================
The single source of truth for how a conversation progresses.

Responsibilities:
- Defines and enforces valid state transitions
- Maintains session conversation history (pruned ring buffer)
- Provides helpers for the RouterEngine to update state

States:
  idle              → bot has no context (fresh session)
  shopping          → customer browsing / asking questions
  cart_active       → items in cart, building order
  awaiting_delivery_mode → cart ready, need pickup/delivery choice
  awaiting_address  → delivery chosen, need address
  awaiting_confirmation → full order assembled, waiting for YES/NO
  completed         → order confirmed and written to DB
  cancelled         → customer cancelled

Transition rules are enforced but not blocking — invalid transitions
are logged as warnings and the state is updated anyway (permissive mode).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .. import models

logger = logging.getLogger("levix.conversation")


# ─── Valid state transitions ──────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str, set[str]] = {
    "idle":                      {"shopping", "cart_active", "idle"},
    "shopping":                  {"shopping", "cart_active", "completed", "idle"},
    "cart_active":               {"cart_active", "shopping", "awaiting_delivery_mode", "awaiting_confirmation", "awaiting_clear_confirm", "awaiting_yes_no", "cancelled", "idle"},
    "awaiting_delivery_mode":    {"cart_active", "awaiting_address", "awaiting_confirmation", "cancelled"},
    "awaiting_address":          {"awaiting_address", "awaiting_confirmation", "cart_active", "cancelled"},
    "awaiting_confirmation":     {"cart_active", "completed", "cancelled"},
    "awaiting_clear_confirm":    {"shopping", "cart_active", "cancelled"},
    "awaiting_yes_no":           {"shopping", "cart_active", "awaiting_address", "awaiting_confirmation", "idle"},
    "completed":                 {"idle", "shopping"},
    "cancelled":                 {"idle", "shopping"},
}

ALL_STATES = set(VALID_TRANSITIONS.keys())

SESSION_TIMEOUT_MINUTES = 30
HISTORY_MAX_TURNS = 6   # keep last N role/content pairs in DB


# ═══════════════════════════════════════════════════════════════════════════════
# ConversationEngine
# ═══════════════════════════════════════════════════════════════════════════════

class ConversationEngine:
    """
    Session lifecycle management and state machine.

    All methods are classmethods — no instance state.
    """

    # ── Session retrieval ─────────────────────────────────────────────────────

    @classmethod
    def get_session(
        cls,
        db:      Session,
        shop_id: int,
        phone:   str,
    ) -> models.AIConversationSession:
        """
        Return the active session for this phone, or create a new one.
        Expires sessions older than SESSION_TIMEOUT_MINUTES automatically.
        """
        timeout_threshold = datetime.now(timezone.utc) - timedelta(
            minutes=SESSION_TIMEOUT_MINUTES
        )

        session = (
            db.query(models.AIConversationSession)
            .filter_by(shop_id=shop_id, customer_phone=phone, is_active=True)
            .first()
        )

        if session:
            # Check expiry
            updated = session.updated_at
            if updated and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)

            if updated and updated < timeout_threshold:
                logger.info(f"[CONV] Session expired for {phone} — starting fresh")
                session.is_active = False
                db.commit()
                session = None

        if not session:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            session = models.AIConversationSession(
                shop_id=shop_id,
                session_id=session_id,
                customer_phone=phone,
                conversation_history=[],
                collected_fields={},
                category="idle",
                turn_count=0,
                is_active=True,
                source="whatsapp",
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            logger.info(f"[CONV] Session created: {session_id} for {phone}")
        else:
            logger.info(f"[CONV] Session restored: {session.session_id} for {phone}")

        return session

    # ── State transitions ─────────────────────────────────────────────────────

    @classmethod
    def transition(
        cls,
        db:         Session,
        session:    models.AIConversationSession,
        next_state: str,
    ) -> None:
        """
        Transition `session` to `next_state`.

        Logs a warning if the transition is not in the valid-transitions map,
        but applies it anyway (permissive) to avoid blocking real conversations.
        """
        current = session.category or "idle"

        if next_state not in ALL_STATES:
            logger.error(f"[CONV] Unknown state '{next_state}' — ignoring transition")
            return

        valid = VALID_TRANSITIONS.get(current, set())
        if next_state not in valid:
            logger.warning(
                f"[CONV] Unusual transition: {current} → {next_state} "
                f"(phone={session.customer_phone})"
            )

        session.category = next_state
        session.updated_at = datetime.now(timezone.utc)
        logger.info(f"[CONV] State: {current} → {next_state} ({session.customer_phone})")

    # ── History management ────────────────────────────────────────────────────

    @classmethod
    def append_history(
        cls,
        session:  models.AIConversationSession,
        role:     str,       # "user" | "assistant"
        content:  str,
    ) -> None:
        """
        Append a turn to conversation history. Prunes to HISTORY_MAX_TURNS.
        """
        history = list(session.conversation_history or [])
        history.append({
            "role":    role,
            "content": content,
            "at":      datetime.now(timezone.utc).isoformat(),
        })
        # Keep last N pairs (each pair = 2 entries = 1 turn)
        max_entries = HISTORY_MAX_TURNS * 2
        if len(history) > max_entries:
            history = history[-max_entries:]
        session.conversation_history = history
        session.turn_count = (session.turn_count or 0) + (1 if role == "user" else 0)
        session.updated_at = datetime.now(timezone.utc)

    @classmethod
    def get_history_for_prompt(
        cls,
        session: models.AIConversationSession,
        max_turns: int = 4,
    ) -> list[dict[str, str]]:
        """
        Return last `max_turns` turn pairs formatted for an LLM prompt.
        [{role: str, content: str}, ...]
        """
        history = session.conversation_history or []
        # Trim to last max_turns*2 entries, exclude "at" key
        trimmed = history[-(max_turns * 2):]
        return [{"role": h["role"], "content": h["content"]} for h in trimmed]

    # ── Intent tracking ───────────────────────────────────────────────────────

    @classmethod
    def set_last_intent(
        cls,
        db:      Session,
        session: models.AIConversationSession,
        intent:  str,
        confidence: float = 0.0,
    ) -> None:
        session.last_intent = intent
        session.intent_confidence = round(confidence, 2)
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)

    # ── Session close ─────────────────────────────────────────────────────────

    @classmethod
    def close_session(
        cls,
        db:      Session,
        session: models.AIConversationSession,
    ) -> None:
        session.is_active = False
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

    # ── Flush (persist all pending changes) ───────────────────────────────────

    @classmethod
    def flush(cls, db: Session, session: models.AIConversationSession) -> None:
        db.add(session)
        db.commit()
