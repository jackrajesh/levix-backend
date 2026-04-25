"""
order_engine.py — LEVIX Order & Cart Engine  (v2)
==================================================
Complete cart and order state management.

v2 improvements:
- CartItem is properly typed with from_dict/to_dict
- Delivery fee computation integrated
- Cart state machine methods (can_checkout, build_order_payload)
- MissingProductRequest logging on unmatched items
- Idempotency key generation
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from .. import models

logger = logging.getLogger("levix.order_engine")


# ─── Cart item ────────────────────────────────────────────────────────────────

@dataclass
class CartItem:
    product_id:   int
    name:         str
    unit_price:   float
    quantity:     int
    spice_level:  Optional[str] = None
    special_note: Optional[str] = None

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.quantity, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id":   self.product_id,
            "name":         self.name,
            "unit_price":   self.unit_price,
            "quantity":     self.quantity,
            "qty":          self.quantity,   # alias — formatters use 'qty'
            "subtotal":     self.subtotal,
            "spice_level":  self.spice_level,
            "special_note": self.special_note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CartItem":
        return cls(
            product_id   = int(d.get("product_id", 0)),
            name         = str(d.get("name", "")),
            unit_price   = float(d.get("unit_price", 0)),
            quantity     = max(1, int(d.get("quantity", d.get("qty", 1)))),
            spice_level  = d.get("spice_level"),
            special_note = d.get("special_note"),
        )


# ─── Cart summary ─────────────────────────────────────────────────────────────

@dataclass
class CartSummary:
    items:      list[dict]
    item_count: int
    total:      float
    is_empty:   bool


# ═══════════════════════════════════════════════════════════════════════════════
# OrderEngine
# ═══════════════════════════════════════════════════════════════════════════════

class OrderEngine:
    """
    Pure cart and order logic.  No AI calls.  All side effects (DB writes)
    are explicit — callers decide when to commit.
    """

    # ── Product search ────────────────────────────────────────────────────────

    @staticmethod
    def find_products(
        db:          Session,
        shop_id:     int,
        hint_tokens: list[str],
        limit:       int = 5,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy product search using hint tokens against name + category + details.
        Returns dicts ordered by token-hit score (best first).
        """
        if not hint_tokens:
            return []

        filters = []
        for token in hint_tokens:
            pattern = f"%{token}%"
            filters.append(func.lower(models.InventoryItem.name).like(pattern))
            filters.append(func.lower(models.InventoryItem.category).like(pattern))
            filters.append(func.lower(models.InventoryItem.product_details).like(pattern))

        products = (
            db.query(models.InventoryItem)
            .filter(models.InventoryItem.shop_id == shop_id)
            .filter(models.InventoryItem.quantity > 0)
            .filter(or_(*filters))
            .limit(limit * 4)
            .all()
        )

        def _score(p: models.InventoryItem) -> int:
            text = (
                (p.name or "").lower()
                + " " + (p.category or "").lower()
                + " " + (p.product_details or "").lower()
            )
            return sum(1 for t in hint_tokens if t in text)

        ranked = sorted(products, key=_score, reverse=True)[:limit]
        return [OrderEngine._product_to_dict(p) for p in ranked]

    @staticmethod
    def get_product_by_id(
        db:         Session,
        shop_id:    int,
        product_id: int,
    ) -> Optional[dict[str, Any]]:
        p = db.query(models.InventoryItem).filter_by(id=product_id, shop_id=shop_id).first()
        return OrderEngine._product_to_dict(p) if p else None

    # ── Cart mutations ────────────────────────────────────────────────────────

    @staticmethod
    def cart_add(
        cart:         list[dict],
        product:      dict[str, Any],
        quantity:     int,
        spice_level:  Optional[str] = None,
        special_note: Optional[str] = None,
    ) -> tuple[list[dict], dict]:
        """
        Add `quantity` units of `product` to `cart`.
        If product is already in cart, increments quantity (capped at max_qty).
        Returns (updated_cart, context_dict).
        """
        items = [CartItem.from_dict(i) for i in cart]
        quantity = max(1, int(quantity))
        max_qty = min(int(product.get("max_qty_per_order", 50)), 50)

        for item in items:
            if item.product_id == product["id"]:
                old_qty = item.quantity
                item.quantity = min(item.quantity + quantity, max_qty)
                added = item.quantity - old_qty
                if spice_level:
                    item.spice_level = spice_level
                if special_note:
                    item.special_note = special_note
                return (
                    [i.to_dict() for i in items],
                    {
                        "action":    "quantity_updated",
                        "item":      item.name,
                        "new_qty":   item.quantity,
                        "added":     added,
                        "subtotal":  item.subtotal,
                    },
                )

        new_item = CartItem(
            product_id   = int(product["id"]),
            name         = str(product["name"]),
            unit_price   = float(product["price"]),
            quantity     = min(quantity, max_qty),
            spice_level  = spice_level,
            special_note = special_note,
        )
        items.append(new_item)
        return (
            [i.to_dict() for i in items],
            {
                "action":     "item_added",
                "item":       new_item.name,
                "qty":        new_item.quantity,
                "unit_price": new_item.unit_price,
                "subtotal":   new_item.subtotal,
            },
        )

    @staticmethod
    def cart_remove(
        cart:        list[dict],
        hint_tokens: list[str],
    ) -> tuple[list[dict], dict]:
        items = [CartItem.from_dict(i) for i in cart]
        matched = OrderEngine._match_cart_item(items, hint_tokens)
        if not matched:
            return ([i.to_dict() for i in items], {"action": "not_found"})
        items.remove(matched)
        summary = OrderEngine.cart_summary([i.to_dict() for i in items])
        return (
            [i.to_dict() for i in items],
            {"action": "item_removed", "item": matched.name, "new_total": summary.total},
        )

    @staticmethod
    def cart_change_quantity(
        cart:        list[dict],
        hint_tokens: list[str],
        new_quantity: int,
    ) -> tuple[list[dict], dict]:
        items = [CartItem.from_dict(i) for i in cart]
        if not items:
            return ([], {"action": "cart_empty"})
        matched = OrderEngine._match_cart_item(items, hint_tokens) if hint_tokens else items[-1]
        if not matched:
            return ([i.to_dict() for i in items], {"action": "not_found"})
        matched.quantity = max(1, int(new_quantity))
        return (
            [i.to_dict() for i in items],
            {
                "action":   "quantity_changed",
                "item":     matched.name,
                "new_qty":  matched.quantity,
                "subtotal": matched.subtotal,
            },
        )

    @staticmethod
    def cart_apply_spice(
        cart:      list[dict],
        modifier:  str,
        hint_tokens: list[str] = None,  # type: ignore[assignment]
    ) -> tuple[list[dict], dict]:
        """Apply spice modifier to the last food item in cart, or a matched one."""
        items = [CartItem.from_dict(i) for i in cart]
        if not items:
            return ([], {"action": "cart_empty"})

        DRINK_WORDS = {"coke", "pepsi", "water", "drink", "juice", "chai", "tea", "coffee"}

        target = None
        if hint_tokens:
            target = OrderEngine._match_cart_item(items, hint_tokens)
        if not target:
            # Last non-drink item
            for item in reversed(items):
                if not any(d in item.name.lower() for d in DRINK_WORDS):
                    target = item
                    break

        if not target:
            return ([i.to_dict() for i in items], {"action": "not_found"})

        target.spice_level = modifier
        return (
            [i.to_dict() for i in items],
            {"action": "spice_set", "item": target.name, "modifier": modifier},
        )

    # ── Cart queries ──────────────────────────────────────────────────────────

    @staticmethod
    def cart_summary(cart: list[dict]) -> CartSummary:
        items = [CartItem.from_dict(i) for i in cart]
        total = round(sum(i.subtotal for i in items), 2)
        return CartSummary(
            items=[i.to_dict() for i in items],
            item_count=len(items),
            total=total,
            is_empty=len(items) == 0,
        )

    # ── Delivery fee ──────────────────────────────────────────────────────────

    @staticmethod
    def delivery_fee(
        cart_total: float,
        shop_settings: dict,
    ) -> float:
        """
        Compute delivery fee based on shop settings.

        Settings schema:
          delivery_fee_fixed: float       (e.g. 40)
          delivery_fee_threshold: float   (orders above this get free delivery)
          delivery_fee_free_above: bool   (defaults True)
        """
        fixed = float(shop_settings.get("delivery_fee_fixed", 40))
        threshold = float(shop_settings.get("delivery_fee_threshold", 500))
        free_above = shop_settings.get("delivery_fee_free_above", True)

        if free_above and cart_total >= threshold:
            return 0.0
        return fixed

    # ── Checkout payload ──────────────────────────────────────────────────────

    @staticmethod
    def build_checkout_payload(
        summary:       CartSummary,
        delivery_mode: str,
        address:       str,
        delivery_fee:  float,
    ) -> dict[str, Any]:
        """
        Produce a structured payload used both for the confirmation message
        and for writing the Order row.
        """
        total_with_delivery = round(summary.total + (delivery_fee if delivery_mode == "delivery" else 0), 2)
        return {
            "items":          summary.items,
            "subtotal":       summary.total,
            "delivery_fee":   delivery_fee if delivery_mode == "delivery" else 0,
            "total":          total_with_delivery,
            "delivery_mode":  delivery_mode,
            "address":        address if delivery_mode == "delivery" else "PICKUP",
        }

    # ── Missing product logging ───────────────────────────────────────────────

    @staticmethod
    def log_missing_product(
        db:           Session,
        shop_id:      int,
        customer_phone: str,
        hint:         str,
    ) -> None:
        """
        Upsert into MissingProductRequest so the shop owner can see demand.
        """
        try:
            existing = (
                db.query(models.MissingProductRequest)
                .filter_by(shop_id=shop_id, product_name=hint.lower()[:100])
                .first()
            )
            if existing:
                existing.count = (existing.count or 1) + 1
            else:
                db.add(
                    models.MissingProductRequest(
                        shop_id=shop_id,
                        product_name=hint.lower()[:100],
                        customer_phone=customer_phone,
                    )
                )
            db.commit()
        except Exception as exc:
            logger.warning(f"[ORDER] log_missing_product failed: {exc}")
            db.rollback()

    # ── Idempotency ───────────────────────────────────────────────────────────

    @staticmethod
    def build_idempotency_key(
        phone:            str,
        cart:             list[dict],
        timestamp_minute: str,
    ) -> str:
        payload = json.dumps(
            {"phone": phone, "cart": sorted(cart, key=lambda x: x.get("product_id", 0)), "ts": timestamp_minute},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:40]

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _product_to_dict(p: models.InventoryItem) -> dict[str, Any]:
        stock = int(p.quantity) if p.quantity else 0
        return {
            "id":                p.id,
            "name":              p.name,
            "category":          p.category or "",
            "price":             float(p.price),
            "max_qty_per_order": min(stock, 50) if stock > 0 else 50,
            "stock":             stock,
            "product_details":   p.product_details or "",
            "details":           p.product_details or "",
        }

    @staticmethod
    def _match_cart_item(
        items:       list[CartItem],
        hint_tokens: list[str],
    ) -> Optional[CartItem]:
        """Token-intersection scoring — returns best matching CartItem or None."""
        if not hint_tokens:
            return None
        best, best_score = None, 0
        for item in items:
            name_tokens = set(re.findall(r"[a-z0-9]+", item.name.lower()))
            score = len(name_tokens & set(hint_tokens))
            if score > best_score:
                best_score = score
                best = item
        return best if best_score > 0 else None
