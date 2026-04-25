"""
order_engine.py — LEVIX Cart & Order Engine
Manages cart CRUD, product catalogue queries, and order placement.
All DB access is SQLAlchemy-compatible (PostgreSQL).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean, Column, Integer, Numeric, String, Text,
    create_engine, or_, func,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# ORM Models — Product Catalogue (shared with your main schema)
# ---------------------------------------------------------------------------

class CatalogueBase(DeclarativeBase):
    pass


class Product(CatalogueBase):
    __tablename__ = "levix_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    name_lower = Column(String(200), nullable=False, index=True)   # for fuzzy match
    category = Column(String(80), index=True)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)
    is_available = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    tags = Column(Text)   # comma-separated: "spicy,veg,biryani"
    max_qty_per_order = Column(Integer, default=20)
    image_url = Column(String(500))


# ---------------------------------------------------------------------------
# Cart Item
# ---------------------------------------------------------------------------

@dataclass
class CartItem:
    product_id: int
    name: str
    unit_price: float
    quantity: int
    spice_level: str | None = None   # mild | medium | extra_spicy
    special_note: str | None = None

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.quantity, 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CartItem":
        return cls(**d)


# ---------------------------------------------------------------------------
# DB factory (can share the engine created in memory_engine)
# ---------------------------------------------------------------------------

_order_db_factory: sessionmaker | None = None


def init_order_db(database_url: str, echo: bool = False) -> None:
    global _order_db_factory
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    CatalogueBase.metadata.create_all(engine)
    _order_db_factory = sessionmaker(bind=engine, expire_on_commit=False)


def _get_db() -> Session:
    if _order_db_factory is None:
        raise RuntimeError("Call init_order_db() before using OrderEngine.")
    return _order_db_factory()


# ---------------------------------------------------------------------------
# OrderEngine
# ---------------------------------------------------------------------------

class OrderEngine:
    """
    Stateless engine — all state lives in the session dict passed in.
    Methods return (updated_cart, reply_context) tuples where reply_context
    is a dict that router.py uses to build the human response.
    """

    # ------------------------------------------------------------------
    # Product search
    # ------------------------------------------------------------------

    def find_products(
        self,
        hint_tokens: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search products by name/tags using token overlap.
        Returns list of product dicts sorted by relevance.
        """
        if not hint_tokens:
            return []

        with _get_db() as db:
            # Build OR filter across tokens
            filters = []
            for token in hint_tokens:
                pattern = f"%{token}%"
                filters.append(Product.name_lower.like(pattern))
                filters.append(Product.tags.like(pattern))

            products = (
                db.query(Product)
                .filter(Product.is_available == True)
                .filter(or_(*filters))
                .limit(limit * 3)   # fetch extra to re-rank
                .all()
            )

            # Score by number of matching tokens
            def _score(p: Product) -> int:
                text = (p.name_lower or "") + " " + (p.tags or "")
                return sum(1 for t in hint_tokens if t in text)

            products = sorted(products, key=_score, reverse=True)[:limit]
            return [self._product_to_dict(p) for p in products]

    def get_product_by_id(self, product_id: int) -> dict[str, Any] | None:
        with _get_db() as db:
            p = db.query(Product).filter_by(id=product_id, is_available=True).first()
            return self._product_to_dict(p) if p else None

    def get_popular_products(self, category: str | None = None, limit: int = 6) -> list[dict]:
        with _get_db() as db:
            q = db.query(Product).filter_by(is_available=True, is_popular=True)
            if category:
                q = q.filter(func.lower(Product.category) == category.lower())
            return [self._product_to_dict(p) for p in q.limit(limit).all()]

    def get_products_by_budget(
        self,
        budget: float,
        group_size: int = 1,
        category: str | None = None,
    ) -> list[dict]:
        """Return products whose price * group_size fits within budget."""
        per_person_budget = budget / max(group_size, 1)
        with _get_db() as db:
            q = (
                db.query(Product)
                .filter(Product.is_available == True)
                .filter(Product.price <= per_person_budget)
                .order_by(Product.is_popular.desc(), Product.price.desc())
            )
            if category:
                q = q.filter(func.lower(Product.category) == category.lower())
            return [self._product_to_dict(p) for p in q.limit(8).all()]

    def get_all_categories(self) -> list[str]:
        with _get_db() as db:
            rows = (
                db.query(Product.category)
                .filter(Product.is_available == True)
                .distinct()
                .all()
            )
            return sorted({r[0] for r in rows if r[0]})

    # ------------------------------------------------------------------
    # Cart operations
    # All methods accept and return plain list[dict] for JSON-safe storage
    # ------------------------------------------------------------------

    def cart_add(
        self,
        cart: list[dict],
        product: dict[str, Any],
        quantity: int,
        spice_level: str | None = None,
        special_note: str | None = None,
    ) -> tuple[list[dict], dict]:
        """
        Add or increase quantity of a product in the cart.
        Returns (new_cart, context).
        """
        cart = [CartItem.from_dict(i) for i in cart]
        quantity = max(1, quantity)
        max_qty = product.get("max_qty_per_order", 20)

        for item in cart:
            if item.product_id == product["id"]:
                new_qty = min(item.quantity + quantity, max_qty)
                added = new_qty - item.quantity
                item.quantity = new_qty
                if spice_level:
                    item.spice_level = spice_level
                if special_note:
                    item.special_note = special_note
                return (
                    [i.to_dict() for i in cart],
                    {
                        "action": "quantity_updated",
                        "item": item.name,
                        "new_qty": item.quantity,
                        "added": added,
                        "subtotal": item.subtotal,
                    },
                )

        new_item = CartItem(
            product_id=product["id"],
            name=product["name"],
            unit_price=float(product["price"]),
            quantity=quantity,
            spice_level=spice_level,
            special_note=special_note,
        )
        cart.append(new_item)
        return (
            [i.to_dict() for i in cart],
            {
                "action": "item_added",
                "item": new_item.name,
                "qty": new_item.quantity,
                "unit_price": new_item.unit_price,
                "subtotal": new_item.subtotal,
            },
        )

    def cart_remove(
        self,
        cart: list[dict],
        hint_tokens: list[str],
    ) -> tuple[list[dict], dict]:
        """
        Remove item matching hint_tokens from cart.
        """
        items = [CartItem.from_dict(i) for i in cart]
        matched = self._match_cart_item(items, hint_tokens)
        if not matched:
            return (
                [i.to_dict() for i in items],
                {"action": "not_found", "hint": " ".join(hint_tokens)},
            )
        items.remove(matched)
        return (
            [i.to_dict() for i in items],
            {"action": "item_removed", "item": matched.name},
        )

    def cart_change_quantity(
        self,
        cart: list[dict],
        hint_tokens: list[str],
        new_quantity: int,
    ) -> tuple[list[dict], dict]:
        """
        Set absolute quantity for item in cart.
        hint_tokens=[] targets the most recently added item.
        """
        items = [CartItem.from_dict(i) for i in cart]
        if not items:
            return ([], {"action": "cart_empty"})

        if hint_tokens:
            matched = self._match_cart_item(items, hint_tokens)
        else:
            matched = items[-1]   # last added

        if not matched:
            return (
                [i.to_dict() for i in items],
                {"action": "not_found", "hint": " ".join(hint_tokens)},
            )

        old_qty = matched.quantity
        matched.quantity = max(1, new_quantity)
        return (
            [i.to_dict() for i in items],
            {
                "action": "quantity_changed",
                "item": matched.name,
                "old_qty": old_qty,
                "new_qty": matched.quantity,
                "subtotal": matched.subtotal,
            },
        )

    def cart_apply_preference(
        self,
        cart: list[dict],
        hint_tokens: list[str],
        spice_level: str,
    ) -> tuple[list[dict], dict]:
        """Apply spice_level to matching item or all items if no match."""
        items = [CartItem.from_dict(i) for i in cart]
        if hint_tokens:
            matched = self._match_cart_item(items, hint_tokens)
            if matched:
                matched.spice_level = spice_level
                return (
                    [i.to_dict() for i in items],
                    {"action": "preference_set", "item": matched.name, "spice": spice_level},
                )

        # Apply to all
        for item in items:
            item.spice_level = spice_level
        return (
            [i.to_dict() for i in items],
            {"action": "preference_all", "spice": spice_level},
        )

    # ------------------------------------------------------------------
    # Cart summary
    # ------------------------------------------------------------------

    def cart_summary(self, cart: list[dict]) -> dict[str, Any]:
        items = [CartItem.from_dict(i) for i in cart]
        total = round(sum(i.subtotal for i in items), 2)
        return {
            "items": [
                {
                    "name": i.name,
                    "qty": i.quantity,
                    "unit_price": i.unit_price,
                    "subtotal": i.subtotal,
                    "spice_level": i.spice_level,
                    "special_note": i.special_note,
                }
                for i in items
            ],
            "item_count": len(items),
            "total_items_qty": sum(i.quantity for i in items),
            "total": total,
            "is_empty": len(items) == 0,
        }

    def rebuild_cart_from_order(self, order: dict[str, Any]) -> list[dict]:
        """
        Rebuild a cart from a previous order's items_snapshot,
        validating each product still exists and is available.
        """
        rebuilt: list[dict] = []
        for snap_item in order.get("items", []):
            pid = snap_item.get("product_id")
            p = self.get_product_by_id(pid) if pid else None
            if p:
                rebuilt.append(
                    CartItem(
                        product_id=p["id"],
                        name=p["name"],
                        unit_price=float(p["price"]),
                        quantity=snap_item.get("quantity", 1),
                        spice_level=snap_item.get("spice_level"),
                        special_note=snap_item.get("special_note"),
                    ).to_dict()
                )
        return rebuilt

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def build_idempotency_key(
        self, phone: str, cart: list[dict], timestamp_minute: str
    ) -> str:
        """
        Deterministic key per (phone, cart contents, minute-bucket).
        Prevents double-tap order submission within the same minute.
        """
        payload = json.dumps(
            {"phone": phone, "cart": cart, "ts": timestamp_minute},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:40]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _product_to_dict(p: Product) -> dict[str, Any]:
        return {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "price": float(p.price),
            "is_available": p.is_available,
            "is_popular": p.is_popular,
            "tags": p.tags or "",
            "max_qty_per_order": p.max_qty_per_order,
            "image_url": p.image_url,
        }

    @staticmethod
    def _match_cart_item(
        items: list[CartItem], hint_tokens: list[str]
    ) -> CartItem | None:
        """Score cart items by token overlap with hint_tokens."""
        if not hint_tokens:
            return None
        best: CartItem | None = None
        best_score = 0
        for item in items:
            name_tokens = set(re.findall(r"[a-z0-9]+", item.name.lower()))
            score = len(name_tokens & set(hint_tokens))
            if score > best_score:
                best_score = score
                best = item
        return best if best_score > 0 else None
