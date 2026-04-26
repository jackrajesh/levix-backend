# -*- coding: utf-8 -*-
"""
live_proof.py — LEVIX End-to-End Live Proof Script
====================================================
Proves all 5 requirements against the REAL database:

1. Order inserted into DB
2. Pending dashboard updated (order visible in orders table)
3. Repeat customer memory loaded
4. Duplicate YES blocked
5. Address validation works

Run:  python live_proof.py
Output: live_proof_results.json + console evidence log
"""

import sys
import os
import io
import json
import time
from datetime import datetime, timezone

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SKIP_AI_INIT"] = "1"   # skip Gemini boot for local test

# ── Imports ───────────────────────────────────────────────────────────────────
from app.database import SessionLocal, engine
from app import models

# Ensure tables exist
models.Base.metadata.create_all(bind=engine)

from app.services.router_engine    import RouterEngine
from app.services.validation_engine import ValidationEngine
from app.services.conversation_engine import ConversationEngine
from app.services.memory_engine    import MemoryEngine
from app.services.order_engine     import OrderEngine

# ── Test config ───────────────────────────────────────────────────────────────
TEST_PHONE_NEW      = "919900000001"   # first-time customer
TEST_PHONE_REPEAT   = "919900000002"   # returning customer
TEST_PHONE_DUPE     = "919900000003"   # duplicate-order test
TEST_PHONE_ADDR     = "919900000004"   # address validation test

RESULTS = []

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def banner(title):
    print("\n" + "═"*60)
    print(f"  {title}")
    print("═"*60)

def ok(msg):
    print(f"  ✅  {msg}")
    return True

def fail(msg):
    print(f"  ❌  FAIL: {msg}")
    return False

def get_shop_id(db):
    shop = db.query(models.Shop).first()
    if not shop:
        # Create a minimal test shop
        shop = models.Shop(
            shop_name="Test Biryani House",
            owner_name="Test Owner",
            email=f"testowner_{int(time.time())}@levixtest.com",
            phone_number="9999999999",
            password_hash="testhash",
            settings={
                "delivery_fee_fixed": 40,
                "delivery_fee_threshold": 500,
                "delivery_fee_free_above": True
            }
        )
        db.add(shop)
        db.commit()
        db.refresh(shop)
        print(f"  ℹ️  Created test shop: id={shop.id}")
    return shop.id

def get_or_create_inventory(db, shop_id):
    """Ensure at least one in-stock product exists."""
    item = db.query(models.InventoryItem).filter_by(shop_id=shop_id).filter(
        models.InventoryItem.quantity > 0
    ).first()
    if not item:
        item = models.InventoryItem(
            shop_id=shop_id,
            name="Chicken Biryani",
            quantity=50,
            price=120,
            status="in_stock",
            category="biryani",
            product_details="spicy chicken biryani served with raita"
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        print(f"  ℹ️  Created test product: {item.name} @ ₹{item.price}")
    return item

def reset_sessions(db, shop_id, phones):
    """Wipe active sessions for test phones so each test starts clean."""
    for phone in phones:
        db.query(models.AIConversationSession).filter_by(
            shop_id=shop_id, customer_phone=phone
        ).update({"is_active": False})
    db.commit()

def reset_profiles(db, shop_id, phones):
    """Remove test profiles so memory tests start clean."""
    for phone in phones:
        db.query(models.CustomerProfile).filter_by(
            shop_id=shop_id, customer_phone=phone
        ).delete()
    db.commit()

def chat(db, shop_id, phone, messages):
    """Send a sequence of messages, return list of replies."""
    replies = []
    for msg in messages:
        reply = RouterEngine.process_message(db, shop_id, phone, msg)
        replies.append(reply)
        print(f"    USER: {msg!r}")
        print(f"     BOT: {reply!r}")
        print()
    return replies


# ─────────────────────────────────────────────────────────────────────────────
# PROOF 1 — Order inserted into DB
# ─────────────────────────────────────────────────────────────────────────────

def proof_1_order_in_db(db, shop_id, product):
    banner("PROOF 1 — Order Inserted into DB")
    phone = TEST_PHONE_NEW
    reset_sessions(db, shop_id, [phone])
    reset_profiles(db, shop_id, [phone])

    orders_before = db.query(models.Order).filter_by(shop_id=shop_id).count()
    print(f"  Orders in DB before: {orders_before}")

    replies = chat(db, shop_id, phone, [
        "hi",
        f"2 {product.name}",
        "pickup",
        "yes",
    ])

    # DB check
    db.expire_all()
    orders_after = db.query(models.Order).filter_by(shop_id=shop_id).count()
    latest_order = db.query(models.Order).filter_by(
        shop_id=shop_id, phone=phone
    ).order_by(models.Order.id.desc()).first()

    result = {
        "proof": "1_order_in_db",
        "orders_before": orders_before,
        "orders_after": orders_after,
        "order_inserted": orders_after > orders_before,
    }

    if latest_order:
        result.update({
            "order_id":      latest_order.id,
            "booking_id":    latest_order.booking_id,
            "phone":         latest_order.phone,
            "product":       latest_order.product,
            "total_amount":  float(latest_order.total_amount),
            "status":        latest_order.status,
            "created_at":    str(latest_order.created_at),
        })
        ok(f"Order #{latest_order.id} written — total ₹{latest_order.total_amount} status={latest_order.status}")
        ok(f"booking_id={latest_order.booking_id}  product={latest_order.product!r}")
    else:
        fail("No order row found in DB after full confirmation flow")

    passed = orders_after > orders_before
    result["passed"] = passed
    (ok if passed else fail)(f"Orders before={orders_before} → after={orders_after}")
    RESULTS.append(result)
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# PROOF 2 — Pending dashboard updated (order visible)
# ─────────────────────────────────────────────────────────────────────────────

def proof_2_pending_dashboard(db, shop_id):
    banner("PROOF 2 — Pending Dashboard Updated")

    # Query pending orders (status = 'pending')
    pending = db.query(models.Order).filter_by(
        shop_id=shop_id, status="pending"
    ).order_by(models.Order.id.desc()).all()

    result = {
        "proof": "2_pending_dashboard",
        "pending_orders_count": len(pending),
        "orders": [
            {
                "id":         o.id,
                "booking_id": o.booking_id,
                "phone":      o.phone,
                "product":    o.product,
                "total":      float(o.total_amount),
                "status":     o.status,
                "created_at": str(o.created_at),
            }
            for o in pending[:5]  # show up to 5
        ],
        "passed": len(pending) > 0,
    }

    if pending:
        ok(f"Found {len(pending)} pending order(s) in DB — dashboard would show these")
        for o in pending[:3]:
            ok(f"  → #{o.id} | {o.product} | ₹{o.total_amount} | {o.phone}")
    else:
        fail("No pending orders in DB")

    RESULTS.append(result)
    return result["passed"]


# ─────────────────────────────────────────────────────────────────────────────
# PROOF 3 — Repeat customer memory loaded
# ─────────────────────────────────────────────────────────────────────────────

def proof_3_repeat_customer(db, shop_id, product):
    banner("PROOF 3 — Repeat Customer Memory Loaded")
    phone = TEST_PHONE_REPEAT
    reset_sessions(db, shop_id, [phone])
    reset_profiles(db, shop_id, [phone])

    # SESSION A: Place first order
    print("  [SESSION A — First visit]")
    chat(db, shop_id, phone, [
        "hi",
        f"1 {product.name}",
        "pickup",
        "yes",
    ])

    # Verify profile created + order recorded
    db.expire_all()
    profile_a = db.query(models.CustomerProfile).filter_by(
        shop_id=shop_id, customer_phone=phone
    ).first()

    result = {
        "proof": "3_repeat_customer",
        "profile_created": profile_a is not None,
    }

    if profile_a:
        ok(f"Profile created after session A: phone={profile_a.customer_phone}")
        ok(f"  total_orders={profile_a.total_orders}  vip_tier={profile_a.vip_tier}")
        ok(f"  favourite_products={profile_a.favorite_products}")
        ok(f"  last_order_summary={profile_a.last_order_summary!r}")
        result.update({
            "session_a_total_orders":    profile_a.total_orders,
            "session_a_vip_tier":        profile_a.vip_tier,
            "session_a_favourites":      profile_a.favorite_products,
            "session_a_last_summary":    profile_a.last_order_summary,
        })
    else:
        fail("No customer profile created after first session")

    # SESSION B: Return visit — bot should personalise greeting
    print("\n  [SESSION B — Return visit]")
    reset_sessions(db, shop_id, [phone])   # expire old session, keep profile

    first_reply = RouterEngine.process_message(db, shop_id, phone, "hi")
    print(f"    USER: 'hi'")
    print(f"     BOT: {first_reply!r}")

    memory_loaded = (
        "welcome back" in first_reply.lower()
        or "again" in first_reply.lower()
        or product.name.lower() in first_reply.lower()
        or "usual" in first_reply.lower()
    )

    result.update({
        "session_b_greeting":     first_reply,
        "memory_loaded_in_reply": memory_loaded,
        "passed":                 profile_a is not None and memory_loaded,
    })

    (ok if memory_loaded else fail)(
        f"Return greeting contains memory signal: {memory_loaded}"
    )

    RESULTS.append(result)
    return result["passed"]


# ─────────────────────────────────────────────────────────────────────────────
# PROOF 4 — Duplicate YES blocked
# ─────────────────────────────────────────────────────────────────────────────

def proof_4_duplicate_yes_blocked(db, shop_id, product):
    banner("PROOF 4 — Duplicate YES Confirmation Blocked")
    phone = TEST_PHONE_DUPE
    reset_sessions(db, shop_id, [phone])
    reset_profiles(db, shop_id, [phone])

    # Build cart and confirm once
    chat(db, shop_id, phone, [
        "hi",
        f"1 {product.name}",
        "pickup",
    ])

    orders_before = db.query(models.Order).filter_by(shop_id=shop_id, phone=phone).count()

    # First YES
    reply_1 = RouterEngine.process_message(db, shop_id, phone, "yes")
    print(f"    USER: 'yes' (first)")
    print(f"     BOT: {reply_1!r}")

    orders_after_1 = db.query(models.Order).filter_by(shop_id=shop_id, phone=phone).count()

    # Second YES immediately
    reply_2 = RouterEngine.process_message(db, shop_id, phone, "yes")
    print(f"    USER: 'yes' (second — duplicate)")
    print(f"     BOT: {reply_2!r}")

    db.expire_all()
    orders_after_2 = db.query(models.Order).filter_by(shop_id=shop_id, phone=phone).count()

    duplicate_blocked = orders_after_2 == orders_after_1
    result = {
        "proof":              "4_duplicate_yes_blocked",
        "orders_before":      orders_before,
        "orders_after_yes1":  orders_after_1,
        "orders_after_yes2":  orders_after_2,
        "yes1_reply":         reply_1,
        "yes2_reply":         reply_2,
        "duplicate_blocked":  duplicate_blocked,
        "passed":             duplicate_blocked and orders_after_1 > orders_before,
    }

    (ok if duplicate_blocked else fail)(
        f"Duplicate YES blocked. Orders: before={orders_before} → yes1={orders_after_1} → yes2={orders_after_2}"
    )
    if not duplicate_blocked:
        fail(f"DUPLICATE ORDER WAS CREATED! yes2 created extra order")

    second_reply_safe = any(
        word in reply_2.lower()
        for word in ["already", "confirmed", "placed", "working"]
    )
    (ok if second_reply_safe else fail)(
        f"Second reply is user-friendly (not crash/error): {reply_2!r}"
    )

    RESULTS.append(result)
    return result["passed"]


# ─────────────────────────────────────────────────────────────────────────────
# PROOF 5 — Address validation works
# ─────────────────────────────────────────────────────────────────────────────

def proof_5_address_validation(db, shop_id, product):
    banner("PROOF 5 — Address Validation Works")

    test_cases = [
        # (input, should_pass, label)
        ("12",                               False, "bare number"),
        ("hi",                               False, "single word"),
        ("123 456",                          False, "only numbers with space"),
        ("12 Gandhi Street Karur",           True,  "valid 4-token address"),
        ("flat 4b rose nagar tirupur",       True,  "valid lowercase"),
        ("No 5, Anna Nagar, Chennai 600040", True,  "valid with pin"),
    ]

    vr_results = []
    all_pass = True

    for addr, should_pass, label in test_cases:
        vr = ValidationEngine.address(addr)
        correct = (bool(vr) == should_pass)
        vr_results.append({
            "input":       addr,
            "label":       label,
            "should_pass": should_pass,
            "actual_pass": bool(vr),
            "reason":      vr.reason if not vr else "OK",
            "correct":     correct,
        })
        symbol = "✅" if correct else "❌"
        print(f"    {symbol}  [{label}] addr={addr!r} → valid={bool(vr)} (expected={should_pass})")
        if not correct:
            all_pass = False

    # Full flow: delivery with bad address, then good address
    print("\n  [Full flow — delivery with bad then good address]")
    phone = TEST_PHONE_ADDR
    reset_sessions(db, shop_id, [phone])
    reset_profiles(db, shop_id, [phone])

    replies = chat(db, shop_id, phone, [
        "hi",
        f"1 {product.name}",
        "delivery",
        "12",                               # bad address
        "12 Gandhi Street Karur Tamil Nadu", # good address
    ])

    # Bad address reply should ask for clarification, not proceed
    bad_addr_reply   = replies[3]
    bad_addr_handled = any(w in bad_addr_reply.lower() for w in [
        "detail", "street", "area", "address", "more", "landmark", "incomplete"
    ])

    # Good address reply should show the address back
    good_addr_reply   = replies[4]
    good_addr_handled = "gandhi" in good_addr_reply.lower() or "confirm" in good_addr_reply.lower()

    print(f"\n    Bad address reply:  {bad_addr_reply!r}")
    print(f"    Good address reply: {good_addr_reply!r}")
    (ok if bad_addr_handled else fail)(f"Bot asked for clarification on bad address")
    (ok if good_addr_handled else fail)(f"Bot accepted and echoed good address")

    result = {
        "proof":                "5_address_validation",
        "validation_cases":     vr_results,
        "all_cases_correct":    all_pass,
        "bad_addr_handled":     bad_addr_handled,
        "good_addr_handled":    good_addr_handled,
        "passed":               all_pass and bad_addr_handled and good_addr_handled,
    }

    RESULTS.append(result)
    return result["passed"]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "█"*60)
    print("  LEVIX LIVE END-TO-END PROOF")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("█"*60)

    db = SessionLocal()
    try:
        shop_id = get_shop_id(db)
        product = get_or_create_inventory(db, shop_id)
        print(f"\n  Shop ID: {shop_id}")
        print(f"  Test product: {product.name} @ ₹{product.price}")

        # Reset all test phones
        all_phones = [TEST_PHONE_NEW, TEST_PHONE_REPEAT, TEST_PHONE_DUPE, TEST_PHONE_ADDR]
        reset_sessions(db, shop_id, all_phones)

        p1 = proof_1_order_in_db(db, shop_id, product)
        p2 = proof_2_pending_dashboard(db, shop_id)
        p3 = proof_3_repeat_customer(db, shop_id, product)
        p4 = proof_4_duplicate_yes_blocked(db, shop_id, product)
        p5 = proof_5_address_validation(db, shop_id, product)

        # ── Final summary ──────────────────────────────────────────────────────
        banner("FINAL PROOF SUMMARY")
        proofs = [
            ("1. Order inserted into DB",       p1),
            ("2. Pending dashboard updated",     p2),
            ("3. Repeat customer memory loaded", p3),
            ("4. Duplicate YES blocked",         p4),
            ("5. Address validation works",      p5),
        ]
        total_pass = 0
        for label, passed in proofs:
            sym = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {sym}  {label}")
            if passed:
                total_pass += 1

        print(f"\n  Score: {total_pass}/5 proofs passed")

        # ── Write results JSON ─────────────────────────────────────────────────
        final_output = {
            "run_at":   datetime.now(timezone.utc).isoformat(),
            "shop_id":  shop_id,
            "product":  {"name": product.name, "price": float(product.price)},
            "summary":  {label: passed for label, passed in proofs},
            "score":    f"{total_pass}/5",
            "all_passed": total_pass == 5,
            "proofs":   RESULTS,
        }

        out_path = os.path.join(os.path.dirname(__file__), "live_proof_results.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2, default=str)

        print(f"\n  Evidence written → live_proof_results.json")
        print("█"*60 + "\n")

        sys.exit(0 if total_pass == 5 else 1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
