"""
validation_engine.py — LEVIX Input & Commerce Validation Layer
==============================================================
Centralised guards for every data point the bot touches.

Key principles:
- Every guard returns a ValidationResult (valid/invalid + reason).
- Raise NOTHING — callers get a typed result and decide what to do.
- All thresholds are constants at the top; easy to tune per-shop later.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("levix.validation")

# ─── Tuneable constants ────────────────────────────────────────────────────────

MAX_CART_ITEMS       = 20          # distinct product lines
MAX_ITEM_QTY         = 50          # quantity per single product
MAX_CART_TOTAL       = 50_000      # ₹ safety cap
MIN_ADDRESS_TOKENS   = 4           # word-count gate for address strings
MAX_ADDRESS_LEN      = 300
MIN_PHONE_DIGITS     = 10
MAX_PHONE_DIGITS     = 15
MAX_MSG_LEN          = 1000        # incoming WhatsApp message character limit
IDEMPOTENCY_WINDOW_S = 90          # seconds within which we block a duplicate order


# ─── Result object ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    cleaned: Any = None           # sanitised / coerced version of the input

    def __bool__(self) -> bool:
        return self.valid


# ═══════════════════════════════════════════════════════════════════════════════
# ValidationEngine
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationEngine:
    """
    Stateless collection of validation helpers used by every engine that
    touches customer-supplied or AI-inferred data.
    """

    # ── Message ───────────────────────────────────────────────────────────────

    @staticmethod
    def message(text: str) -> ValidationResult:
        """
        Validate raw incoming customer message.

        Blocks: empty, too-long, pure-whitespace, binary garbage.
        """
        if not isinstance(text, str):
            return ValidationResult(False, "message must be a string")
        text = text.strip()
        if not text:
            return ValidationResult(False, "empty message")
        if len(text) > MAX_MSG_LEN:
            return ValidationResult(False, f"message exceeds {MAX_MSG_LEN} chars")
        # Basic printable ASCII / Unicode gate (WhatsApp messages are always UTF-8)
        if not re.search(r"[\w\s]", text, re.UNICODE):
            return ValidationResult(False, "message contains no readable content")
        return ValidationResult(True, cleaned=text)

    # ── Quantity ──────────────────────────────────────────────────────────────

    @staticmethod
    def quantity(value: Any, *, item_name: str = "") -> ValidationResult:
        """
        Validate a quantity value.

        Accepts int, float (coerced), or string digit.
        """
        try:
            qty = int(value)
        except (TypeError, ValueError):
            return ValidationResult(False, f"'{value}' is not a valid quantity")

        if qty <= 0:
            return ValidationResult(False, f"quantity must be at least 1 (got {qty})")
        if qty > MAX_ITEM_QTY:
            return ValidationResult(
                False,
                f"maximum {MAX_ITEM_QTY} units per item"
                + (f" for {item_name}" if item_name else ""),
            )
        return ValidationResult(True, cleaned=qty)

    # ── Cart ──────────────────────────────────────────────────────────────────

    @staticmethod
    def cart_size(cart: list[dict]) -> ValidationResult:
        """Ensure cart has not exceeded line-item limit."""
        if len(cart) > MAX_CART_ITEMS:
            return ValidationResult(
                False, f"cart cannot have more than {MAX_CART_ITEMS} distinct items"
            )
        return ValidationResult(True)

    @staticmethod
    def cart_total(total: float) -> ValidationResult:
        """Block astronomically large orders (likely a bug)."""
        if total > MAX_CART_TOTAL:
            return ValidationResult(
                False, f"cart total ₹{total} exceeds safety limit of ₹{MAX_CART_TOTAL}"
            )
        return ValidationResult(True)

    @staticmethod
    def cart_not_empty(cart: list[dict]) -> ValidationResult:
        if not cart:
            return ValidationResult(False, "cart is empty")
        return ValidationResult(True)

    # ── Phone ─────────────────────────────────────────────────────────────────

    @staticmethod
    def phone(value: str) -> ValidationResult:
        """
        Validate and normalise a phone number.

        Strips spaces, dashes, parentheses. Returns digits-only cleaned value.
        """
        if not value:
            return ValidationResult(False, "phone number is required")
        digits = re.sub(r"[\s\-().+]", "", str(value))
        if not digits.isdigit():
            return ValidationResult(False, "phone number contains non-digit characters")
        if len(digits) < MIN_PHONE_DIGITS or len(digits) > MAX_PHONE_DIGITS:
            return ValidationResult(
                False,
                f"phone number must be {MIN_PHONE_DIGITS}-{MAX_PHONE_DIGITS} digits (got {len(digits)})",
            )
        return ValidationResult(True, cleaned=digits)

    # ── Address ───────────────────────────────────────────────────────────────

    @staticmethod
    def address(value: str) -> ValidationResult:
        """
        Validate a delivery address.

        A valid address must:
        - Not be empty or just numbers
        - Have at least MIN_ADDRESS_TOKENS word-like tokens
        - Not exceed MAX_ADDRESS_LEN characters
        """
        if not value:
            return ValidationResult(False, "address is required")
        value = value.strip()
        if len(value) > MAX_ADDRESS_LEN:
            return ValidationResult(False, "address is too long")

        # Block obviously garbage inputs
        if re.fullmatch(r"[\d\s]+", value):
            return ValidationResult(False, "address looks incomplete (only numbers)")

        tokens = [t for t in re.split(r"[\s,/]+", value) if t]
        if len(tokens) < MIN_ADDRESS_TOKENS:
            return ValidationResult(
                False,
                f"address seems too short (need at least {MIN_ADDRESS_TOKENS} parts like street, area, city)",
            )
        return ValidationResult(True, cleaned=value)

    # ── Budget ────────────────────────────────────────────────────────────────

    @staticmethod
    def budget(value: Any) -> ValidationResult:
        """Validate a numeric budget. Must be positive and sane."""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return ValidationResult(False, f"'{value}' is not a valid budget amount")
        if amount <= 0:
            return ValidationResult(False, "budget must be greater than 0")
        if amount > 100_000:
            return ValidationResult(False, f"budget ₹{amount:.0f} seems too high")
        return ValidationResult(True, cleaned=round(amount, 2))

    # ── Delivery mode ─────────────────────────────────────────────────────────

    @staticmethod
    def delivery_mode(value: str) -> ValidationResult:
        allowed = {"delivery", "pickup"}
        v = (value or "").strip().lower()
        if v not in allowed:
            return ValidationResult(
                False, f"delivery mode must be one of: {', '.join(allowed)}"
            )
        return ValidationResult(True, cleaned=v)

    # ── Idempotency (duplicate order guard) ───────────────────────────────────

    @staticmethod
    def not_duplicate_order(
        last_order_time_iso: Optional[str],
        window_seconds: int = IDEMPOTENCY_WINDOW_S,
    ) -> ValidationResult:
        """
        Returns invalid if an order was already placed within `window_seconds`.
        Prevents double-tap YES confirmation from creating two orders.
        """
        if not last_order_time_iso:
            return ValidationResult(True)
        from datetime import datetime, timezone
        try:
            last_dt = datetime.fromisoformat(last_order_time_iso)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < window_seconds:
                return ValidationResult(
                    False,
                    f"order already confirmed {int(elapsed)}s ago — duplicate blocked",
                )
        except Exception as exc:
            logger.warning(f"[VALIDATION] idempotency parse error: {exc}")
        return ValidationResult(True)

    # ── Composite cart validation ─────────────────────────────────────────────

    @staticmethod
    def full_cart(cart: list[dict]) -> ValidationResult:
        """Run all cart-level checks in one call."""
        r = ValidationEngine.cart_not_empty(cart)
        if not r:
            return r
        r = ValidationEngine.cart_size(cart)
        if not r:
            return r
        # Validate each item's quantity
        for item in cart:
            r = ValidationEngine.quantity(item.get("quantity", 0), item_name=item.get("name", ""))
            if not r:
                return r
        return ValidationResult(True)

    # ── Checkout readiness ────────────────────────────────────────────────────

    @staticmethod
    def checkout_ready(
        cart: list[dict],
        delivery_mode: str,
        address: Optional[str],
        cart_total: float,
    ) -> ValidationResult:
        """
        Gate that must pass before we attempt to write an Order to the DB.
        Checks cart, delivery mode, address (if delivery), and total.
        """
        r = ValidationEngine.full_cart(cart)
        if not r:
            return r
        r = ValidationEngine.delivery_mode(delivery_mode)
        if not r:
            return r
        if delivery_mode == "delivery":
            r = ValidationEngine.address(address or "")
            if not r:
                return r
        r = ValidationEngine.cart_total(cart_total)
        if not r:
            return r
        return ValidationResult(True)
