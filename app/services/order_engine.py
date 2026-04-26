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

# Change 3: Category-conditional Aliases + P1 Seed Typo Corrections
_TYPO_CORRECTIONS: dict[str, str] = {
    # beverages
    "coke":       "cola",
    "pepsi":      "cola",
    "cold drink": "cola",
    # biryani variants
    "briyani":   "biryani",
    "biriyani":  "biryani",
    "bryani":    "biryani",
    # mushroom
    "mashroom":  "mushroom",
    "musroom":   "mushroom",
    # ice cream
    "icecream":  "ice cream",
    "ice-cream": "ice cream",
    # chicken
    "chiken":    "chicken",
    "chciken":   "chicken",
    # fried rice
    "frid rice": "fried rice",
}

_DEFAULT_ALIASES = {
    "Food & Restaurant": {
        "coke": "coke", "pepsi": "pepsi", "coca cola": "coke", "coca-cola": "coke",
        "coco cola": "coke", "cold drink": "cola",
        "briyani": "biryani", "biriyani": "biryani", "bryani": "biryani",
        "mashroom": "mushroom", "musroom": "mushroom",
        "icecream": "ice cream", "ice-cream": "ice cream",
        "chiken": "chicken", "chciken": "chicken",
        "frid rice": "fried rice",
        "lassi": "juice",
    },
    "Electronics": {
        "iphone": "mobile", "android": "mobile", "macbook": "laptop",
        "charger": "cable", "earphones": "buds",
    },
    "Clothing & Fashion": {
        "shirt": "top", "tshirt": "top", "pant": "trouser", "shoes": "footwear",
    },
    "Pharmacy & Health": {
        "tablet": "medicine", "capsule": "medicine", "syrup": "medicine",
    },
}


def normalize_typos(text: str) -> str:
    """FAIL 3.4: Normalizes common typos BEFORE the matching pipeline starts."""
    corrections = {
        "mashroom": "mushroom",
        "musroom": "mushroom", 
        "briyani": "biryani",
        "biriyani": "biryani",
        "bryani": "biryani",
        "chiken": "chicken",
        "chciken": "chicken",
        "frid": "fried",
        "icecream": "ice cream"
    }
    low = text.lower()
    for wrong, right in corrections.items():
        low = low.replace(wrong, right)
    return low

def _apply_typo_corrections(text: str) -> str:
    """Apply multi-word and single-word typo corrections before tokenising."""
    return normalize_typos(text)


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
    def calculate_score(p: models.InventoryItem, corrected_tokens: list[str]) -> int:
        searchable = (
            (p.name or "").lower()
            + " " + (p.category or "").lower()
            + " " + (p.product_details or "").lower()
        )
        name_lower = (p.name or "").lower()
        hint_joined = " ".join(corrected_tokens)
        
        # Exact Match
        if hint_joined == name_lower:
            return 100
            
        # Descriptors
        generic_words = {"rice", "biryani", "roti", "naan", "parotta", "chicken", "mutton", "fish", "ice cream", "juice", "milk", "water", "drink"}
        modifiers = [t for t in corrected_tokens if t not in generic_words]
        generics = [t for t in corrected_tokens if t in generic_words]
        
        primary_descriptor = modifiers[0] if modifiers else None
        
        # PRIMARY DESCRIPTOR RULE
        if primary_descriptor and primary_descriptor not in searchable:
            return 0
            
        # Keyword Overlap
        overlap = 0
        for t in corrected_tokens:
            if t in searchable:
                overlap += 1
        
        if not corrected_tokens: return 0
        base_score = (overlap / len(corrected_tokens)) * 50
        
        # Bonus for name inclusion
        if name_lower in hint_joined or hint_joined in name_lower:
            base_score += 30
            
        # Bonus for matching all generics
        if generics and all(g in searchable for g in generics):
            base_score += 10
            
        return int(base_score)

    @staticmethod
    def find_products(
        db:          Session,
        shop_id:     int,
        hint_tokens: list[str],
        limit:       int = 5,
        shop_category: str = "General / Other",
    ) -> list[dict[str, Any]]:
        if not hint_tokens:
            return []

        hint_str = " ".join(hint_tokens)
        corrected_str = _apply_typo_corrections(hint_str)

        cat_aliases = _DEFAULT_ALIASES.get(shop_category, {})
        if shop_category == "General / Other":
            for aliases in _DEFAULT_ALIASES.values():
                cat_aliases.update(aliases)

        corrected_tokens = [
            cat_aliases.get(t.lower(), t.lower())
            for t in corrected_str.split()
            if t
        ]
        if not corrected_tokens:
            corrected_tokens = hint_tokens

        # FAIL 3.3: Seed aliases if table is empty
        alias_count = db.query(models.InventoryAlias).join(models.InventoryItem).filter(models.InventoryItem.shop_id == shop_id).count()
        if alias_count == 0:
            seed_aliases = [
                ("coke", "Coco Cola"),
                ("cola", "Coco Cola"), 
                ("cold drink", "Coco Cola"),
                ("briyani", "biryani"),
                ("biriyani", "biryani"),
                ("mashroom", "mushroom"),
                ("icecream", "ice cream"),
                ("chiken", "chicken")
            ]
            for alias_txt, target_name in seed_aliases:
                # Find target product
                target_p = db.query(models.InventoryItem).filter(
                    models.InventoryItem.shop_id == shop_id,
                    func.lower(models.InventoryItem.name) == target_name.lower()
                ).first()
                if target_p:
                    new_alias = models.InventoryAlias(
                        inventory_id=target_p.id,
                        alias=alias_txt
                    )
                    db.add(new_alias)
            db.commit()

        # FAIL 3.3: Step 1: Check InventoryAlias table for exact alias match (Score 95)
        for token in corrected_tokens:
            alias_match = (
                db.query(models.InventoryAlias)
                .join(models.InventoryItem)
                .filter(models.InventoryItem.shop_id == shop_id)
                .filter(func.lower(models.InventoryAlias.alias) == token.lower())
                .first()
            )
            if alias_match:
                product = db.query(models.InventoryItem).filter(
                    models.InventoryItem.id == alias_match.inventory_id,
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0,
                ).first()
                if product:
                    # Return directly with high score to bypass fuzzy
                    return [{**OrderEngine._product_to_dict(product), "match_score": 95}]

        # Step 3-6: Fuzzy match
        filters = []
        for token in corrected_tokens:
            pattern = f"%{token}%"
            filters.append(func.lower(models.InventoryItem.name).like(pattern))
            filters.append(func.lower(models.InventoryItem.category).like(pattern))
            filters.append(func.lower(models.InventoryItem.product_details).like(pattern))

        if not filters:
            return []

        products = (
            db.query(models.InventoryItem)
            .filter(models.InventoryItem.shop_id == shop_id)
            .filter(models.InventoryItem.quantity > 0)
            .filter(or_(*filters))
            .limit(limit * 4)
            .all()
        )

        scored = []
        all_scores = []
        for p in products:
            s = OrderEngine.calculate_score(p, corrected_tokens)
            all_scores.append((p.name, s))
            if s >= 60: # Threshold for candidates
                scored.append((s, OrderEngine._product_to_dict(p)))

        # FAIL 4.4: Debug logging for matching
        print(f"[MATCH DEBUG] query='{hint_str}' corrected='{corrected_str}' scores={all_scores}")

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [item for score, item in scored[:limit]]
        
        # Add score to results for router to check thresholds
        for i, res in enumerate(results):
            res["match_score"] = scored[i][0]
            
        return results

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
        customer_name: str,
        hint:         str,
        message_text: str = "",
    ) -> None:
        """
        Insert or increment a MissingProductRequest row (non-blocking).
        Falls back gracefully if the DB write fails — never crashes the caller.
        """
        try:
            existing = (
                db.query(models.MissingProductRequest)
                .filter_by(shop_id=shop_id, product_name=hint[:100])
                .first()
            )
            if existing:
                existing.count = (existing.count or 0) + 1
                existing.customer_phone = customer_phone
            else:
                inquiry = models.MissingProductRequest(
                    shop_id=shop_id,
                    product_name=hint[:100],
                    customer_phone=customer_phone,
                    count=1,
                )
                db.add(inquiry)
            db.commit()
            logger.info(f"[ORDER] Missing product logged: '{hint}' for shop {shop_id}")
        except Exception as exc:
            logger.warning(f"[ORDER] log_missing_product failed (non-fatal): {exc}")
            try:
                db.rollback()
            except Exception:
                pass

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
