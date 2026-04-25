# -*- coding: utf-8 -*-
"""
recommendation_engine.py — LEVIX Smart Recommendation Brain (v2)
=================================================================
Key fix: meal-first combo builder.
- MEAL_CATEGORIES take priority over all others
- Drinks/sides are ADDON-only, never primary combo items
- Group meals: qty scales correctly per person count
- product_details used for item descriptions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models

logger = logging.getLogger("levix.recommendation")


# ─── Meal category priority list ─────────────────────────────────────────────

MEAL_CATEGORIES = [
    "biryani", "fried rice", "meals", "meal", "rice",
    "wings", "leg piece", "leg", "chicken", "mutton",
    "curry", "parotta", "roti", "naan", "dosa", "idli",
    "kebab", "tikka", "tandoori", "fry", "roast", "grilled",
    "kothu", "parcel", "combo",
]

DRINK_CATEGORIES = [
    "drink", "cool drink", "juice", "coke", "pepsi", "water",
    "tea", "coffee", "chai", "milk", "lassi", "shake", "soda",
    "rose milk", "badam milk", "faluda",
]

SIDE_CATEGORIES = [
    "side", "starter", "snack", "raita", "pickle", "papad",
    "dessert", "sweet", "ice cream", "halwa",
]


def _is_drink(item: dict) -> bool:
    cat  = item.get("category", "").lower()
    name = item.get("name", "").lower()
    tags = item.get("tags", "").lower()
    for d in DRINK_CATEGORIES:
        if d in cat or d in name or d in tags:
            return True
    return False


def _is_meal(item: dict) -> bool:
    cat  = item.get("category", "").lower()
    name = item.get("name", "").lower()
    tags = item.get("tags", "").lower()
    for m in MEAL_CATEGORIES:
        if m in cat or m in name:
            return True
    return False


# ─── Result type ──────────────────────────────────────────────────────────────

@dataclass
class RecommendationResult:
    items: list[dict] = field(default_factory=list)
    total: float = 0.0
    rationale: str = ""
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
        "details":  p.product_details or "",
    }


def _meal_score(item: dict) -> int:
    """High = strong meal signal. Negative = drink/side."""
    if _is_drink(item):
        return -100   # drinks never lead a combo
    cat  = item.get("category", "").lower()
    name = item.get("name", "").lower()
    score = 0
    for i, keyword in enumerate(MEAL_CATEGORIES):
        if keyword in cat or keyword in name:
            score += (len(MEAL_CATEGORIES) - i) * 3   # higher weight for higher priority
    return score


# ═══════════════════════════════════════════════════════════════════════════════
# RecommendationEngine
# ═══════════════════════════════════════════════════════════════════════════════

class RecommendationEngine:

    # ── 1. Budget combo (meal-first) ──────────────────────────────────────────

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
        Meal-first greedy combo:
        1. Fill meals for `people` count (one portion each person for main item)
        2. Only add drinks/sides if budget permits AND meals are already chosen
        3. Never output 5x Coke as a dinner suggestion
        """
        if budget <= 0:
            return RecommendationResult(rationale="Budget must be positive")

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

        all_items = [_to_dict(p) for p in q.all()]

        # Separate meals from drinks/sides
        meals  = sorted([i for i in all_items if not _is_drink(i)], key=_meal_score, reverse=True)
        drinks = sorted([i for i in all_items if _is_drink(i)], key=lambda x: x["price"])

        if not meals:
            return RecommendationResult(rationale="No meal items found under budget")

        combo: list[dict] = []
        remaining = float(budget)
        seen_ids: set = set()
        portions = max(1, people)

        # Phase 1: Fill meals
        for item in meals:
            if item["id"] in seen_ids:
                continue
            cost = item["price"] * portions
            if cost <= remaining:
                combo.append({**item, "qty": portions})
                remaining -= cost
                seen_ids.add(item["id"])
                portions = 1  # subsequent items 1 serve only
            elif item["price"] <= remaining:
                combo.append({**item, "qty": 1})
                remaining -= item["price"]
                seen_ids.add(item["id"])
            if len(combo) >= 3:
                break

        # Phase 2: Optional drinks only if budget remains
        if remaining >= 30 and drinks:
            for d in drinks:
                if d["id"] in seen_ids:
                    continue
                if d["price"] <= remaining:
                    combo.append({**d, "qty": 1})
                    remaining -= d["price"]
                    seen_ids.add(d["id"])
                    break   # max 1 drink item in a food combo

        if not combo:
            return RecommendationResult(rationale="No items fit within budget")

        total = round(sum(i["price"] * i["qty"] for i in combo), 2)
        rationale = (
            f"Meal combo for {people} {'person' if people == 1 else 'people'} "
            f"under \u20b9{budget:.0f}"
        )
        if veg_only:
            rationale += " (veg)"
        return RecommendationResult(items=combo, total=total, rationale=rationale)

    # ── 2. Group meal ─────────────────────────────────────────────────────────

    @staticmethod
    def group_meal(
        db:      Session,
        shop_id: int,
        people:  int,
        budget:  Optional[float] = None,
    ) -> RecommendationResult:
        budget = budget or (people * 200)   # ₹200/person default
        return RecommendationEngine.combo_under_budget(
            db, shop_id, budget, people=people
        )

    # ── 3. Veg-only combo ─────────────────────────────────────────────────────

    @staticmethod
    def veg_combo(db: Session, shop_id: int, budget: float) -> RecommendationResult:
        return RecommendationEngine.combo_under_budget(
            db, shop_id, budget, veg_only=True
        )

    # ── 4. Spicy picks ────────────────────────────────────────────────────────

    @staticmethod
    def spicy_picks(db: Session, shop_id: int, limit: int = 4) -> RecommendationResult:
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
        return RecommendationResult(items=dicts, total=round(total, 2), rationale="Spicy picks")

    # ── 5. Popular items ──────────────────────────────────────────────────────

    @staticmethod
    def popular_items(db: Session, shop_id: int, limit: int = 4) -> RecommendationResult:
        profiles = (
            db.query(models.CustomerProfile)
            .filter(models.CustomerProfile.shop_id == shop_id)
            .all()
        )
        popularity: dict[str, int] = {}
        for p in profiles:
            for name, count in (p.favorite_products or {}).items():
                popularity[name] = popularity.get(name, 0) + count

        if not popularity:
            items = (
                db.query(models.InventoryItem)
                .filter(models.InventoryItem.shop_id == shop_id, models.InventoryItem.quantity > 0)
                .limit(limit).all()
            )
            dicts = [_to_dict(p) for p in items]
        else:
            top_names = sorted(popularity, key=popularity.get, reverse=True)[:limit]  # type: ignore
            dicts = []
            for name in top_names:
                item = (
                    db.query(models.InventoryItem)
                    .filter(
                        models.InventoryItem.shop_id == shop_id,
                        func.lower(models.InventoryItem.name) == name.lower(),
                        models.InventoryItem.quantity > 0,
                    ).first()
                )
                if item:
                    dicts.append(_to_dict(item))

        total = sum(d["price"] for d in dicts)
        return RecommendationResult(items=dicts, total=round(total, 2), rationale="Popular items")

    # ── 6. Upsell suggestion ──────────────────────────────────────────────────

    @staticmethod
    def upsell_for(
        db: Session,
        shop_id: int,
        cart: list[dict],
        budget_left: float = 500,
    ) -> Optional[dict]:
        """Return ONE drink/side upsell not already in cart."""
        cart_ids = {i.get("product_id") for i in cart}
        cart_names_lower = {i.get("name", "").lower() for i in cart}

        for cat in DRINK_CATEGORIES + ["dessert", "side", "starter"]:
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    models.InventoryItem.price <= budget_left,
                    func.lower(models.InventoryItem.category).contains(cat),
                    ~models.InventoryItem.id.in_(cart_ids),
                ).first()
            )
            if item and item.name.lower() not in cart_names_lower:
                return _to_dict(item)
        return None

    # ── 7. OOS replacement ────────────────────────────────────────────────────

    @staticmethod
    def replacement_for(
        db: Session,
        shop_id: int,
        item_name: str,
        category: Optional[str] = None,
    ) -> Optional[dict]:
        if category:
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    func.lower(models.InventoryItem.category).contains(category.lower()),
                    func.lower(models.InventoryItem.name) != item_name.lower(),
                ).first()
            )
            if item:
                return _to_dict(item)

        for kw in item_name.lower().split():
            if len(kw) < 3:
                continue
            item = (
                db.query(models.InventoryItem)
                .filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                    func.lower(models.InventoryItem.name).contains(kw),
                    func.lower(models.InventoryItem.name) != item_name.lower(),
                ).first()
            )
            if item:
                return _to_dict(item)
        return None

    # ── 8. Menu listing ───────────────────────────────────────────────────────

    @staticmethod
    def menu_items(
        db: Session,
        shop_id: int,
        category: Optional[str] = None,
        limit: int = 8,
    ) -> list[dict]:
        q = db.query(models.InventoryItem).filter(
            models.InventoryItem.shop_id == shop_id,
            models.InventoryItem.quantity > 0,
        )
        if category:
            q = q.filter(func.lower(models.InventoryItem.category).contains(category.lower()))
        return [_to_dict(p) for p in q.limit(limit).all()]
