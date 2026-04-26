# -*- coding: utf-8 -*-
"""
transcript_test.py
Runs before/after scenarios against real DB.
Shows BEFORE (expected old behavior) vs AFTER (actual new output).
"""
import sys, os, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SKIP_AI_INIT"] = "1"

from app.database import SessionLocal
from app import models
from app.services.router_engine import RouterEngine

models.Base.metadata.create_all(bind=SessionLocal().get_bind())

RESULTS = []

def get_shop(db):
    shop = db.query(models.Shop).first()
    assert shop, "No shop found — run live_proof.py first"
    return shop.id

def reset(db, shop_id, phones):
    for p in phones:
        db.query(models.AIConversationSession).filter_by(shop_id=shop_id, customer_phone=p).update({"is_active": False})
    db.commit()

def chat(db, shop_id, phone, messages):
    replies = []
    for m in messages:
        r = RouterEngine.process_message(db, shop_id, phone, m)
        replies.append(r)
    return replies

def run_test(name, phone, steps, expected_signals, db, shop_id):
    """
    steps: list of (input, before_desc)
    expected_signals: list of strings that MUST appear in reply
    """
    reset(db, shop_id, [phone])
    inputs  = [s[0] for s in steps]
    befores = [s[1] for s in steps]
    replies = chat(db, shop_id, phone, inputs)

    passed  = True
    details = []
    for i, (inp, before, reply, signal) in enumerate(zip(inputs, befores, replies, expected_signals)):
        hit = signal.lower() in reply.lower() if signal else True
        details.append({
            "input":   inp,
            "before":  before,
            "after":   reply,
            "signal":  signal,
            "pass":    hit,
        })
        if not hit:
            passed = False

    RESULTS.append({"test": name, "passed": passed, "steps": details})

    # Print
    print(f"\n{'='*60}")
    print(f"  TEST: {name} -- {'PASS' if passed else 'FAIL'}")
    print(f"{'='*60}")
    for d in details:
        mark = "[OK]" if d["pass"] else "[FAIL]"
        print(f"  IN : {d['input']!r}")
        print(f"  BEF: {d['before']}")
        print(f"  AFT: {d['after']!r}")
        print(f"  {mark} signal={d['signal']!r}")
        print()
    return passed


def main():
    db = SessionLocal()
    try:
        shop_id = get_shop(db)
        print(f"Shop ID: {shop_id}")

        # ── Setup products ────────────────────────────────────────────────────
        def ensure(name, price, category, details, qty=50):
            p = db.query(models.InventoryItem).filter_by(shop_id=shop_id, name=name).first()
            if not p:
                p = models.InventoryItem(
                    shop_id=shop_id, name=name, price=price,
                    category=category, product_details=details,
                    quantity=qty, status="in_stock")
                db.add(p)
            else:
                p.quantity = qty; p.price = price
                p.category = category; p.product_details = details
            db.commit()

        ensure("Chicken Biryani", 120, "biryani",   "basmati rice, medium spicy, serves 1")
        ensure("Mutton Biryani",  180, "biryani",   "premium mutton, aromatic, serves 1")
        ensure("Veg Fried Rice",  80,  "fried rice","vegetarian, egg optional, serves 1")
        ensure("Chicken Wings",   150, "wings",     "crispy fried wings, 6 pieces")
        ensure("Leg Piece",       110, "leg piece", "juicy chicken leg, full piece")
        ensure("Coke",            50,  "drink",     "350ml can")
        ensure("Rose Milk",       60,  "drink",     "fresh rose flavored milk 300ml")
        ensure("Mango Lassi",     70,  "drink",     "chilled mango lassi 300ml")

        # ── 1. Welcome back greeting ──────────────────────────────────────────
        # Plant a profile with order history
        phone_ret = "919988776600"
        reset(db, shop_id, [phone_ret])
        profile = db.query(models.CustomerProfile).filter_by(shop_id=shop_id, customer_phone=phone_ret).first()
        if not profile:
            profile = models.CustomerProfile(
                shop_id=shop_id, customer_phone=phone_ret,
                favorite_products={"Chicken Biryani": 3},
                total_orders=3, vip_tier="NEW",
                last_order_summary="2x Chicken Biryani",
                visit_count=4, message_count=10,
                favorite_categories={}, last_5_orders=[], notes={})
            db.add(profile)
            db.commit()

        run_test(
            "1. Welcome back greeting",
            phone_ret,
            [("hi", "Raw invoice dump / hi again")],
            ["want your usual"],
            db, shop_id,
        )

        # ── 2. Order status NOT treated as add_item ───────────────────────────
        phone_s = "919988776601"
        reset(db, shop_id, [phone_s])
        # Plant an order for this phone
        try:
            o = models.Order(
                shop_id=shop_id, booking_id=f"BK55501", order_id=f"STAT55501",
                customer_name=phone_s, phone=phone_s,
                address="PICKUP", product="2x Chicken Biryani",
                quantity=2, unit_price=240, total_amount=240, status="PREPARING")
            db.add(o); db.commit()
        except Exception:
            db.rollback()

        run_test(
            "2. Order status intent",
            phone_s,
            [("tell me order status", "Added product / confused reply")],
            ["bk55501"],
            db, shop_id,
        )

        # ── 3. YES + text = modify, not confirm ───────────────────────────────
        phone_ym = "919988776602"
        reset(db, shop_id, [phone_ym])
        chat(db, shop_id, phone_ym, ["hi", "1 chicken biryani", "pickup"])
        run_test(
            "3. YES+text = cart modify",
            phone_ym,
            [("yes add coke too", "Confirms order / ignores extra text")],
            ["coke"],
            db, shop_id,
        )

        # ── 4. Recommendation: 5 people under 700 = meals not drinks ─────────
        phone_rec = "919988776603"
        reset(db, shop_id, [phone_rec])
        replies = chat(db, shop_id, phone_rec, ["5 people under 700"])
        after = replies[0]
        # Must have a meal item, must NOT be 5x Coke
        no_coke_dump = "5x coke" not in after.lower() and "5x rose milk" not in after.lower()
        has_meal = any(m in after.lower() for m in ["biryani", "fried rice", "wings", "leg", "mutton"])
        RESULTS.append({
            "test": "4. Group combo = meals not drinks",
            "passed": no_coke_dump and has_meal,
            "steps": [{"input": "5 people under 700", "before": "5x Coke as combo",
                        "after": after, "pass": no_coke_dump and has_meal}]
        })
        print(f"\n{'='*60}\n  TEST: 4. Group combo = meals not drinks -- {'PASS' if (no_coke_dump and has_meal) else 'FAIL'}")
        print(f"  IN : '5 people under 700'")
        print(f"  BEF: Outputs 5x Coke as dinner combo")
        print(f"  AFT: {after!r}")
        print(f"  no_coke_dump={no_coke_dump} has_meal={has_meal}\n")

        # ── 5. Multi-item parser ──────────────────────────────────────────────
        phone_mi = "919988776604"
        reset(db, shop_id, [phone_mi])
        run_test(
            "5. Multi-item parser",
            phone_mi,
            [("hi", ""), ("2 fried rice, 1 coke, 1 rose milk", "Only first item added")],
            ["", "added to cart"],
            db, shop_id,
        )

        # ── 6. 5-digit order number ───────────────────────────────────────────
        phone_ord = "919988776605"
        reset(db, shop_id, [phone_ord])
        replies = chat(db, shop_id, phone_ord, ["hi", "2 chicken biryani", "pickup", "yes"])
        after = replies[-1]
        import re
        has_5digit = bool(re.search(r"#\d{5}", after))
        RESULTS.append({
            "test": "6. 5-digit order number",
            "passed": has_5digit,
            "steps": [{"input": "yes", "before": "No order number in reply",
                        "after": after, "pass": has_5digit}]
        })
        print(f"\n{'='*60}\n  TEST: 6. 5-digit order number -- {'PASS' if has_5digit else 'FAIL'}")
        print(f"  AFT: {after!r}  has_5digit={has_5digit}\n")

        # ── 7. Clear cart flow ────────────────────────────────────────────────
        phone_cc = "919988776606"
        reset(db, shop_id, [phone_cc])
        run_test(
            "7. Clear cart flow",
            phone_cc,
            [("hi", ""), ("1 chicken biryani", ""), ("clear cart", "No confirmation asked")],
            ["", "", "sure"],
            db, shop_id,
        )

        # ── 8. Non-food filter ────────────────────────────────────────────────
        phone_nf = "919988776607"
        reset(db, shop_id, [phone_nf])
        run_test(
            "8. Non-food redirect",
            phone_nf,
            [("I want to buy an iphone", "Logs as missing product / adds to cart")],
            ["food store"],
            db, shop_id,
        )

        # ── 9. Product details used in price reply ────────────────────────────
        phone_pd = "919988776608"
        reset(db, shop_id, [phone_pd])
        run_test(
            "9. Product details in reply",
            phone_pd,
            [("how much is chicken biryani", "Plain price only")],
            ["basmati"],
            db, shop_id,
        )

        # ── Summary ───────────────────────────────────────────────────────────
        passed = sum(1 for r in RESULTS if r["passed"])
        total  = len(RESULTS)
        print(f"\n{'='*60}")
        print(f"  TRANSCRIPT TEST SUMMARY: {passed}/{total}")
        print(f"{'='*60}")
        for r in RESULTS:
            sym = "PASS" if r["passed"] else "FAIL"
            print(f"  [{sym}]  {r['test']}")

        with open("transcript_results.json", "w", encoding="utf-8") as f:
            json.dump({"score": f"{passed}/{total}", "all_passed": passed == total, "results": RESULTS},
                      f, indent=2, default=str)
        print(f"\n  Evidence -> transcript_results.json")
        sys.exit(0 if passed == total else 1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
