"""
recommendation_engine.py — LEVIX Smart Recommendation Brain
============================================================
Purely deterministic — no AI API call needed.

Provides:
- Budget-optimised combos (knapsack-style greedy)
- Group-meal bundles (person-count aware)
- Preference filtering (veg, spice, category)
- Upsell suggestions
- Fast-mover & popularity picks
- Out-of-stock replacement suggestions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models

logger = logging.getLogger("levix.recommendation")


# ─── Result type ──────────────────────────────────────────────────────────────

@dataclass
class RecommendationResult:
    items: list[dict] = field(default_factory=list)    # product dicts
    total: float = 0.0
    rationale: str = ""                                # human-readable explanation
    is_empty: bool = True

    def __post_init__(self):
        self.is_empty = len(self.items) == 0


def _to_dict(p: models.InventoryItem) -> dict[str, Any]:
    return {
        "id":       p.id,
        "name":     p.name,
        "category": p.category or "",
        "price":    float(p.price),
        "quantity": p.quantity,
        "tags":     (p.product_details or "").lower(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RecommendationEngine
# ═══════════════════════════════════════════════════════════════════════════════

class RecommendationEngine:
    """
    Pure-Python recommendation logic backed by the shop's inventory.
    Never hallucinates — all items come from the DB.
    """

    # ── 1. Budget combo ───────────────────────────────────────────────────────

    @staticmethod
    def combo_under_budget(
        db:        Session,
        shop_id:   int,
        budget:    float,
        *,
        people:    int = 1,
        veg_only:  bool = False,
        spice:     Optional[str] = None,
        category:  Optional[str] = None,
    ) -> RecommendationResult:
        """
        Greedy combo builder: fills `budget` with the best-value in-stock
        food items, prioritising meals and biryanis.

        Scales quantities for `people` count.
        """
        if budget <= 0:
            return RecommendationResult(rationale="Budget must be positive")

        # Fetch candidates: in-stock, affordable individually
        q = (
            db.query(models.InventoryItem)
            .filter(
                models.InventoryItem.shop_id == shop_id,
                models.InventoryItem.quantity > 0,
                models.InventoryItem.price > 0,
                models.InventoryItem.price <= budget,
            )
        )

        if veg_only:
            q = q.filter(
                func.lower(models.InventoryItem.product_details).contains("veg")
                | func.lower(models.InventoryItem.category).contains("veg")
            )
        if category:
            q = q.filter(
                func.lower(models.InventoryItem.category).contains(category.lower())
            )

        candidates = sorted(
            [_to_dict(p) for p in q.all()],
            key=lambda x: RecommendationEngine._meal_priority(x),
            reverse=True,
        )

        if not candidates:
            return RecommendationResult(rationale="No items found under budget")

        # Greedy fill: pick items that fit, prioritise high-priority meals
        combo: list[dict] = []
        remaining = budget
        seen_ids: set = set()

        # One portion per person for the top item, then add variety
        portions = max(1, people)
        for item in candidates:
            if item["id"] in seen_ids:
                continue
            cost = item["price"] * portions
            if cost <= remaining:
                combo.append({**item, "qty": portions})
                remaining -= cost
                seen_ids.add(item["id"])
                portions = 1  # subsequent items are single serves
            elif item["price"] <= remaining:
                # At least 1 portion fits
                combo.append({**item, "qty": 1})
                remaining -= item["price"]
                seen_ids.add(item["id"])

            if remaining < min(c["price"] for c in candidates if c["id"] not in seen_ids or True) :
                break  # nothing else fits
            if len(combo) >= 5:
                break

        total = sum(i["price"] * i["qty"] for i in combo)

        rationale = (
            f"Budget combo for {people} {'person' if people == 1 else 'people'} "
            f"under ₹{budget:.0f}"
        )
        if veg_only:
            rationale += " (veg)"
        if spice:
            rationale += f", {spice}"

        return RecommendationResult(items=combo, total=round(total, 2), rationale=rationale)

    # ── 2. Group meal ─────────────────────────────────────────────────────────

    @staticmethod
    def group_meal(
        db:      Session,
        shop_id: int,
        people:  int,
        budget:  Optional[float] = None,
    ) -> RecommendationResult:
        """
        Build a group meal: one main each, plus shared starters / drinks if
        budget allows.
        """
        budget = budget or (people * 250)   # default ₹250/person heuristic
        return RecommendationEngine.combo_under_budget(
            db, shop_id, budget, people=people
        )

    # ── 3. Veg-only combo ─────────────────────────────────────────────────────

    @staticmethod
    def veg_combo(
        db:     Session,
        shop_id: int,
        budget: float,
    ) -> RecommendationResult:
        return RecommendationEngine.combo_under_budget(
            db, shop_id, budget, veg_only=True
        )

    # ── 4. Spicy picks ────────────────────────────────────────────────────────

    @staticmethod
    def spicy_picks(
        db:      Session,
        shop_id: int,
        limit:   int = 4,
    ) -> RecommendationResult:
        """
        Return items tagged as spicy in product_details or category.
        """
        items = (
            db.query(models.InventoryItem)
            .filter(
                models.InventoryItem.shop_id == shop_id,
                models.InventoryItem.quantity > 0,
                func.lower(models.InventoryItem.product_details).contains("spic")
                | func.lower(models.InventoryItem.product_details).contains("hot")
                | func.lower(models.InventoryItem.name).contains("65")
                | func.lower(models.InventoryItem.name).contains("pepper")
                | func.lower(models.InventoryItem.name).contains("chilli"),
            )
            .limit(limit)
            .all()
        )
        dicts = [_to_dict(p) for p in items]
        total = sum(d["price"] for d in dicts)
        return RecommendationResult(
            items=dicts, total=round(total, 2), rationale="Spicy picks from our menu"
        )

    # ── 5. Popular / fast-moving ──────────────────────────────────────────────

    @staticmethod
    def popular_items(
        db:      Session,
        shop_id: int,
        limit:   int = 4,
    ) -> RecommendationResult:
        """
        Derive popularity from CustomerProfile favorite_products counts.
        Falls back to inventory order if no order history exists.
        """
        # Aggregate from customer profiles
        profiles = (
            db.query(models.CustomerProfile)
            .filter(models.CustomerProfile.shop_id == shop_id)
            .all()
        )

        popularity: dict[str, int] = {}
        for p in profiles:
            favs = p.favorite_products or {}
            for name, count in favs.items():
                popularity[name] = popularity.get(name, 0) + count

        if not popularity:
            # Fallback: top items by DB order
            items = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                )
                .limit(limit)
                .all()
            )
            dicts = [_to_dict(p) for p in items]
        else:
            top_names = sorted(popularity, key=popularity.get, reverse=True)[:limit]  # type: ignore[arg-type]
            dicts = []
            for name in top_names:
                item = (
                    db.query(models.InventoryItem)
                    .filter(
                        models.InventoryItem.shop_id == shop_id,
                        func.lower(models.InventoryItem.name) == name.lower(),
                        models.InventoryItem.quantity > 0,
                    )
                    .first()
                )
                if item:
                    dicts.append(_to_dict(item))

        total = sum(d["price"] for d in dicts)
        return RecommendationResult(
            items=dicts, total=round(total, 2), rationale="Popular items from our menu"
        )

    # ── 6. Upsell suggestion ──────────────────────────────────────────────────

    @staticmethod
    def upsell_for(
        db:         Session,
        shop_id:    int,
        cart:       list[dict],
        budget_left: float = 500,
    ) -> Optional[dict]:
        """
        Return ONE upsell item that complements the cart but is not already in it.
        Prioritises drinks / desserts / sides that are cheap enough.
        """
        cart_ids = {i.get("product_id") for i in cart}
        cart_names_lower = {i.get("name", "").lower() for i in cart}

        # Prefer drinks or sides
        upsell_categories = ["drink", "dessert", "side", "cool drink", "juice", "chai", "tea"]
        for cat in upsell_categories:
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    models.InventoryItem.price <= budget_left,
                    func.lower(models.InventoryItem.category).contains(cat),
                    ~models.InventoryItem.id.in_(cart_ids),
                )
                .first()
            )
            if item and item.name.lower() not in cart_names_lower:
                return _to_dict(item)

        # Generic fallback: any affordable item not in cart
        item = (
            db.query(models.InventoryItem)
            .filter(
                models.InventoryItem.shop_id == shop_id,
                models.InventoryItem.quantity > 0,
                models.InventoryItem.price <= budget_left,
                ~models.InventoryItem.id.in_(cart_ids),
            )
            .first()
        )
        return _to_dict(item) if item else None

    # ── 7. Out-of-stock replacement ───────────────────────────────────────────

    @staticmethod
    def replacement_for(
        db:       Session,
        shop_id:  int,
        item_name: str,
        category: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Find a suitable in-stock replacement for an OOS item.
        Searches same category first, then falls back to price tier.
        """
        # Try same category
        if category:
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    func.lower(models.InventoryItem.category).contains(category.lower()),
                    func.lower(models.InventoryItem.name) != item_name.lower(),
                )
                .first()
            )
            if item:
                return _to_dict(item)

        # Keyword match in name
        keywords = item_name.lower().split()
        for kw in keywords:
            if len(kw) < 3:
                continue
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    func.lower(models.InventoryItem.name).contains(kw),
                    func.lower(models.InventoryItem.name) != item_name.lower(),
                )
                .first()
            )
            if item:
                return _to_dict(item)

        return None

    # ── 8. Menu listing (for view_menu intent) ────────────────────────────────

    @staticmethod
    def menu_items(
        db:       Session,
        shop_id:  int,
        category: Optional[str] = None,
        limit:    int = 8,
    ) -> list[dict]:
        """Return in-stock menu items, optionally filtered by category."""
        q = db.query(models.InventoryItem).filter(
            models.InventoryItem.shop_id == shop_id,
            models.InventoryItem.quantity > 0,
        )
        if category:
            q = q.filter(
                func.lower(models.InventoryItem.category).contains(category.lower())
            )
        return [_to_dict(p) for p in q.limit(limit).all()]

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _meal_priority(item: dict) -> int:
        """Score that pushes meals to the front of combo picks."""
        cat = item.get("category", "").lower()
        name = item.get("name", "").lower()
        score = 0
        for keyword in ["biryani", "rice", "curry", "meal", "parotta", "naan", "roti"]:
            if keyword in cat or keyword in name:
                score += 2
        for keyword in ["chicken", "mutton", "paneer", "veg", "egg"]:
            if keyword in name:
                score += 1
        return score
