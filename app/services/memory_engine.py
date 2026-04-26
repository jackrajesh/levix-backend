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

    # Pending YES/NO action (for upsell confirm, unknown-product request, clear-cart confirm)
    pending_action_type:  Optional[str] = None   # e.g. "log_missing_product"
    pending_payload:      Optional[dict] = None  # arbitrary payload for the action
    pending_created_at:   Optional[str] = None   # ISO timestamp

    # Gap 1: Rate Limiting
    message_timestamps:   list[float] = field(default_factory=list) # List of time.time() stamps

    # Gap 5: Failed Order Retry
    retry_payload:        Optional[dict] = None  # Stores data for re-attempting DB write
    retry_count:          int = 0

    # Gap 6: Ambiguous Product Clarification
    ambiguous_options:    list[dict] = field(default_factory=list) # List of candidate products

    # Gap 4: Last modified item tracking (for "add 2 more", "make it 5")
    last_item_id:         Optional[int] = None

    # Change 4: Onboarding Flow tracking
    onboarding_step:      Optional[str] = None # "collect_name" | "collect_phone"
    retry_phone_count:    int = 0

    # FAIL 2.2 / 6.2: Upsell tracking
    upsell_active:        bool = False
    upsell_product:       Optional[str] = None

    # FAIL 4.5: Pending inquiry tracking
    pending_inquiry_product: Optional[str] = None
    
    # FAIL 6.3: Shop category
    shop_category:        str = "General"

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
        # FAIL 1.7: Debug for returning customer lookup
        print(f"[ONBOARDING] Looking up phone={phone} shop_id={session.shop_id}")
        profile = CustomerProfileEngine.get_or_create(db, session.shop_id, phone)
        print(f"[ONBOARDING] Found profile: {profile.customer_name} (orders={profile.total_orders})")
        
        session_mem = SessionMemory.from_dict(session.collected_fields or {})
        
        # FAIL 6.3: Load shop category into session context
        shop = db.query(models.Shop).get(session.shop_id)
        if shop:
            session_mem.shop_category = getattr(shop, "shop_category", "General")
        
        # Change 4: Onboarding Flow initiation for new customers
        name = profile.customer_name or ""
        profile_phone = profile.customer_phone or ""
        
        needs_onboarding = (
            not name.strip() or 
            name.strip().lower() in ("vip", "customer", "unknown", "guest") or
            not profile_phone.strip() or 
            len(profile_phone.strip()) < 10
        )
        
        if needs_onboarding and session.category != "onboarding":
            session.category = "onboarding"
            session_mem.onboarding_step = "collect_name"
            
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

        # Safety sync
        if mem.session.customer_name and not mem.profile.customer_name:
            mem.profile.customer_name = mem.session.customer_name
        
        db.add(session)
        db.add(mem.profile)
        logger.info(f"[MEMORY] Flushing session={session.session_id} profile_name={mem.profile.customer_name} (phone={mem.profile.customer_phone})")
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
