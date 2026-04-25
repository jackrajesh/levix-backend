"""
memory_engine.py — LEVIX Two-Layer Memory System
=================================================
Provides a clean, unified interface over BOTH:

Layer 1 — Session Memory   (in-flight, per-conversation, stored in DB JSON)
Layer 2 — Long-Term Memory (CustomerProfile, persisted across all sessions)

Design:
- SessionMemory:  typed wrapper around session.collected_fields JSON blob.
- LongTermMemory: thin façade over CustomerProfileEngine.
- MemoryEngine:   orchestration class used by ConversationEngine & RouterEngine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from .. import models
from .customer_profile_engine import CustomerProfileEngine

logger = logging.getLogger("levix.memory")


# ═══════════════════════════════════════════════════════════════════════════════
# Session Memory — typed view over collected_fields
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SessionMemory:
    """
    Typed representation of everything the bot knows *in this conversation*.

    Serialises cleanly to/from the session.collected_fields JSON dict.
    """
    # Cart state
    cart:             list[dict]   = field(default_factory=list)
    delivery_mode:    Optional[str] = None        # "delivery" | "pickup"
    delivery_address: Optional[str] = None

    # Customer info collected inline
    customer_name:    Optional[str] = None
    customer_phone:   Optional[str] = None

    # Preferences extracted this session
    budget:           Optional[float] = None
    group_size:       Optional[int]   = None
    spice_level:      Optional[str]   = None
    veg_preference:   Optional[str]   = None

    # Idempotency guards
    last_order_time:  Optional[str] = None    # ISO timestamp
    last_order_id:    Optional[int] = None

    # Abandoned-cart tracking
    abandoned_reminder_sent: bool = False

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != [] and v is not False}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionMemory":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in (d or {}).items() if k in known}
        return cls(**filtered)

    # ── Cart helpers ──────────────────────────────────────────────────────────

    @property
    def cart_total(self) -> float:
        return round(
            sum(i.get("unit_price", 0) * i.get("quantity", 0) for i in self.cart), 2
        )

    @property
    def cart_is_empty(self) -> bool:
        return len(self.cart) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# MemoryEngine — orchestration
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryEngine:
    """
    Unified memory API used by ConversationEngine.

    Usage pattern:
        mem = MemoryEngine.load(db, session, profile)
        mem.session.cart = updated_cart
        ...
        MemoryEngine.flush(db, session, profile, mem)
    """

    def __init__(
        self,
        session_mem: SessionMemory,
        profile:     models.CustomerProfile,
    ):
        self.session  = session_mem
        self.profile  = profile
        self._dirty   = False   # set True when caller mutates session

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        db:       Session,
        session:  models.AIConversationSession,
        phone:    str,
    ) -> "MemoryEngine":
        """
        Load both layers from the DB. Creates the CustomerProfile if needed.
        """
        profile = CustomerProfileEngine.get_or_create(db, session.shop_id, phone)
        session_mem = SessionMemory.from_dict(session.collected_fields or {})
        return cls(session_mem, profile)

    # ── Persist ───────────────────────────────────────────────────────────────

    @classmethod
    def flush(
        cls,
        db:      Session,
        session: models.AIConversationSession,
        mem:     "MemoryEngine",
    ) -> None:
        """
        Write session memory back to the DB session object.
        Also triggers passive preference learning.
        """
        new_fields = mem.session.to_dict()
        session.collected_fields = new_fields

        # Passive learning: push session signals into long-term profile
        CustomerProfileEngine.learn_from_session(db, mem.profile, new_fields)

        db.add(session)
        db.commit()

    # ── Convenience mutators ──────────────────────────────────────────────────

    def note_order_completed(self, order_id: int) -> None:
        """Record that an order just went through — for idempotency."""
        self.session.last_order_time = datetime.now(timezone.utc).isoformat()
        self.session.last_order_id = order_id
        self.session.cart = []

    def note_preference(
        self,
        *,
        budget:         Optional[float] = None,
        group_size:     Optional[int] = None,
        spice_level:    Optional[str] = None,
        veg_preference: Optional[str] = None,
    ) -> None:
        """Update session-level preferences discovered mid-conversation."""
        if budget is not None:
            self.session.budget = budget
        if group_size is not None:
            self.session.group_size = group_size
        if spice_level is not None:
            self.session.spice_level = spice_level
        if veg_preference is not None:
            self.session.veg_preference = veg_preference

    # ── Long-term helpers (convenience wrappers) ──────────────────────────────

    def record_order(
        self,
        db:         Session,
        cart_items: list[dict],
        total:      float,
    ) -> None:
        CustomerProfileEngine.record_order(db, self.profile, cart_items, total)

    def record_complaint(self, db: Session, note: str) -> None:
        CustomerProfileEngine.record_complaint(db, self.profile, note)

    def welcome_back_message(self) -> str:
        return CustomerProfileEngine.welcome_back_message(self.profile)

    def memory_context_for_prompt(self) -> str:
        return CustomerProfileEngine.build_memory_context(self.profile)

    # ── Query helpers ─────────────────────────────────────────────────────────

    @property
    def is_returning_customer(self) -> bool:
        return (self.profile.total_orders or 0) > 0

    @property
    def top_favourite(self) -> Optional[str]:
        favs = self.profile.favorite_products or {}
        if not favs:
            return None
        return max(favs, key=favs.get)  # type: ignore[arg-type]

    @property
    def last_order_summary(self) -> Optional[str]:
        return self.profile.last_order_summary

    @property
    def estimated_budget(self) -> Optional[float]:
        """Session budget takes priority over profile average."""
        return self.session.budget or self.profile.avg_budget
