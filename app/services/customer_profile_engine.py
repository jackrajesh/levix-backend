"""
customer_profile_engine.py — LEVIX Customer Profile & Long-Term Memory
=======================================================================
Upgraded replacement for customer_memory.py.

Handles:
- Profile creation / retrieval
- Session-to-profile preference learning
- Order history recording
- VIP tier management
- Prompt-ready memory context generation
- Welcome-back message personalisation

Backward-compatible: same models.CustomerProfile schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy.orm import Session

from .. import models

logger = logging.getLogger("levix.customer_profile")


# ═══════════════════════════════════════════════════════════════════════════════
# CustomerProfileEngine
# ═══════════════════════════════════════════════════════════════════════════════

class CustomerProfileEngine:
    """
    Long-term customer memory layer.

    All methods are classmethods / staticmethods — no instance state.
    The `db` session is always passed in so this module is thread-safe.
    """

    # ── Profile retrieval ─────────────────────────────────────────────────────

    @classmethod
    def get_or_create(
        cls,
        db:      Session,
        shop_id: int,
        phone:   str,
    ) -> models.CustomerProfile:
        """
        Return an existing profile or create a new one.
        Also increments visit counter and updates last_seen_at.
        """
        profile = (
            db.query(models.CustomerProfile)
            .filter_by(shop_id=shop_id, customer_phone=phone)
            .first()
        )

        if not profile:
            profile = models.CustomerProfile(
                shop_id=shop_id,
                customer_phone=phone,
                favorite_products={},
                favorite_categories={},
                last_5_orders=[],
                notes={},
                visit_count=1,
                message_count=0,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            logger.info(f"[PROFILE] Created: {phone}")
        else:
            profile.visit_count = (profile.visit_count or 0) + 1
            profile.last_seen_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"[PROFILE] Restored: {phone} (visits={profile.visit_count})")

        return profile

    # ── Learning from session ─────────────────────────────────────────────────

    @classmethod
    def learn_from_session(
        cls,
        db:          Session,
        profile:     models.CustomerProfile,
        session_fields: dict[str, Any],
    ) -> None:
        """
        Extract preference signals from the current session's collected_fields
        and persist them to the long-term profile.

        Call this after each session update for passive learning.
        """
        changed = False

        # Budget
        budget = session_fields.get("budget")
        if budget:
            try:
                b = float(budget)
                if profile.avg_budget:
                    # Exponential moving average (α=0.3)
                    profile.avg_budget = round(0.3 * b + 0.7 * profile.avg_budget, 2)
                else:
                    profile.avg_budget = b
                if not profile.max_budget or b > profile.max_budget:
                    profile.max_budget = b
                changed = True
            except (TypeError, ValueError):
                pass

        # Group size
        people = session_fields.get("group_size") or session_fields.get("people")
        if people:
            profile.usual_people_count = int(people)
            changed = True

        # Spice
        spice = session_fields.get("spice_level")
        if spice:
            profile.preferred_spice_level = str(spice)
            changed = True

        # Veg preference
        veg = session_fields.get("veg_preference")
        if veg:
            profile.veg_preference = str(veg)
            changed = True

        # Customer name (if captured during checkout)
        name = session_fields.get("customer_name")
        if name and not profile.customer_name:
            profile.customer_name = str(name)
            changed = True

        if changed:
            db.commit()
            logger.info(f"[PROFILE] Preferences updated: {profile.customer_phone}")

    # ── Order recording ───────────────────────────────────────────────────────

    @classmethod
    def record_order(
        cls,
        db:            Session,
        profile:       models.CustomerProfile,
        cart_items:    list[dict],
        total:         float,
    ) -> None:
        """
        Record a completed order into long-term memory.

        - Increments total_orders
        - Updates favorite_products counts
        - Maintains last_5_orders ring buffer
        - Updates VIP tier
        - Raises conversion score
        """
        profile.total_orders = (profile.total_orders or 0) + 1

        favs = dict(profile.favorite_products or {})
        for item in cart_items:
            name = item.get("name", "")
            favs[name] = favs.get(name, 0) + item.get("qty", 1)
            cat = item.get("category", "")
            if cat:
                cats = dict(profile.favorite_categories or {})
                cats[cat] = cats.get(cat, 0) + 1
                profile.favorite_categories = cats
        profile.favorite_products = favs

        # Summarise for last_order_summary (human readable)
        summary_parts = [
            f"{i['qty']}x {i['name']}" for i in cart_items
        ]
        summary = ", ".join(summary_parts)
        profile.last_order_summary = summary
        profile.last_order_at = datetime.now(timezone.utc)

        # Ring buffer — keep last 5
        history = list(profile.last_5_orders or [])
        history.insert(0, {
            "summary": summary,
            "total":   total,
            "date":    datetime.now(timezone.utc).isoformat(),
        })
        profile.last_5_orders = history[:5]

        # Conversion score
        profile.conversion_score = min((profile.conversion_score or 0) + 10, 100)

        # VIP tier
        cls._refresh_tier(profile)

        db.commit()
        logger.info(
            f"[PROFILE] Order recorded: {profile.customer_phone} "
            f"(total_orders={profile.total_orders}, tier={profile.vip_tier})"
        )

    # ── Complaint signal ──────────────────────────────────────────────────────

    @classmethod
    def record_complaint(
        cls,
        db:      Session,
        profile: models.CustomerProfile,
        note:    str,
    ) -> None:
        notes = dict(profile.notes or {})
        complaints = notes.get("complaints", [])
        complaints.append({"note": note, "at": datetime.now(timezone.utc).isoformat()})
        notes["complaints"] = complaints[-10:]  # keep last 10 only
        profile.notes = notes
        db.commit()

    # ── Memory context for prompts ────────────────────────────────────────────

    @classmethod
    def build_memory_context(cls, profile: models.CustomerProfile) -> str:
        """
        Produce a short, structured memory snippet for the AI system prompt.
        Typically 3–6 lines.
        """
        parts: list[str] = []

        parts.append(f"Customer tier: {profile.vip_tier or 'NEW'}")
        if profile.total_orders:
            parts.append(f"Total orders: {profile.total_orders}")
        if profile.avg_budget:
            parts.append(f"Usual budget: ₹{int(profile.avg_budget)}")
        if profile.preferred_spice_level:
            parts.append(f"Spice preference: {profile.preferred_spice_level}")
        if profile.veg_preference:
            parts.append(f"Food type: {profile.veg_preference}")
        if profile.usual_people_count:
            parts.append(f"Usually orders for: {profile.usual_people_count} people")

        favs = profile.favorite_products or {}
        if favs:
            top = sorted(favs.items(), key=lambda x: -x[1])[:3]
            parts.append(f"Favourites: {', '.join(n for n, _ in top)}")

        if profile.last_order_summary:
            parts.append(f"Last order: {profile.last_order_summary}")

        return "\n".join(parts)

    # ── Welcome-back message ──────────────────────────────────────────────────

    @classmethod
    def welcome_back_message(cls, profile: models.CustomerProfile) -> str:
        """
        Return a personalised welcome-back string (empty string for first visit).
        Designed to be prepended to the greeting reply.
        """
        if (profile.visit_count or 0) <= 1 and (profile.total_orders or 0) == 0:
            return ""

        tier = profile.vip_tier or "NEW"

        favs = profile.favorite_products or {}
        top_fav: Optional[str] = None
        if favs:
            top_fav = max(favs, key=favs.get)  # type: ignore[arg-type]

        if tier == "VIP":
            prefix = "Welcome back, VIP! ⭐ "
        elif tier == "REGULAR":
            prefix = "Welcome back 😊 "
        else:
            prefix = "Hi again! "

        if top_fav and (profile.total_orders or 0) > 0:
            return f"{prefix}Ready for your usual *{top_fav}* today? Or something different?"
        elif profile.avg_budget:
            return f"{prefix}I have some great combos around ₹{int(profile.avg_budget)} for you!"
        else:
            return f"{prefix}Good to see you! What can I get for you today?"

    # ── Lead counter ──────────────────────────────────────────────────────────

    @classmethod
    def record_lead(cls, db: Session, profile: models.CustomerProfile) -> None:
        profile.total_leads = (profile.total_leads or 0) + 1
        db.commit()

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _refresh_tier(profile: models.CustomerProfile) -> None:
        """Update VIP tier based on total orders."""
        old = profile.vip_tier
        if (profile.total_orders or 0) >= 8:
            profile.vip_tier = "VIP"
        elif (profile.total_orders or 0) >= 3:
            profile.vip_tier = "REGULAR"
        else:
            profile.vip_tier = "NEW"
        if old != profile.vip_tier:
            logger.info(
                f"[PROFILE] Tier changed: {profile.customer_phone} → {profile.vip_tier}"
            )


# ── Backward-compat alias ─────────────────────────────────────────────────────
# Old code imports CustomerMemoryEngine — this keeps it alive without a crash.
CustomerMemoryEngine = CustomerProfileEngine
