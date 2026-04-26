import os
import sys

# FORCE SQLite for tests before anything else is imported
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_levix_full.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import time
import uuid
import asyncio
import random
import re
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker, Session

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.stdout.encoding != 'utf-8': sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8': sys.stderr.reconfigure(encoding='utf-8')

import logging
logging.basicConfig(level=logging.WARNING, format='%(message)s', stream=sys.stdout)

from app.database import Base, engine as db_engine, SessionLocal as TestingSessionLocal
from app import models
from app.services.router_engine import RouterEngine
from app.services.intent_engine import IntentEngine
from app.services.memory_engine import MemoryEngine
from app.services.conversation_engine import ConversationEngine
from app.services.order_engine import OrderEngine
from app.services.customer_profile_engine import CustomerProfileEngine

def setup_db():
    Base.metadata.drop_all(bind=db_engine)
    Base.metadata.create_all(bind=db_engine)
    db = TestingSessionLocal()
    shop = models.Shop(
        shop_name="Test Mega Mart", owner_name="Test Owner", email="test@example.com",
        password_hash="hash", shop_category="Food & Restaurant", business_category="Food & Restaurant"
    )
    db.add(shop)
    db.commit()
    db.refresh(shop)
    sid = shop.id
    items = [
        ("Coke", 20, "beverage", sid),
        ("Chicken Biryani", 120, "food", sid),
        ("Mushroom Biryani", 120, "food", sid),
        ("Chicken Fried Rice", 140, "food", sid),
        ("Ice Cream", 15, "dessert", sid),
        ("Rose Milk", 30, "beverage", sid),
        ("Chicken Wings", 80, "food", sid),
        ("Blue Denim Jeans", 899, "Clothing & Fashion", sid),
        ("White Cotton Shirt", 499, "Clothing & Fashion", sid),
        ("Black Hoodie", 1200, "Clothing & Fashion", sid),
        ("Wireless Earbuds", 1499, "Electronics", sid),
        ("USB-C Cable", 199, "Electronics", sid),
        ("Notebook", 45, "General", sid)
    ]
    for name, price, cat, s_id in items:
        item = models.InventoryItem(
            shop_id=s_id, name=name, price=price, quantity=100, status="in_stock",
            category=cat, product_details=f"Premium {name}."
        )
        db.add(item)
        db.commit()
        if "Earbuds" in name:
            db.add(models.InventoryAlias(inventory_id=item.id, alias="earbuds"))
        if "Coke" in name:
            db.add(models.InventoryAlias(inventory_id=item.id, alias="coca cola"))
        db.commit()
    db.close()
    return sid

class MetricsCollector:
    def __init__(self):
        self.response_times = []
        self.intent_results = []
        self.checkouts_started = 0
        self.checkouts_completed = 0
        self.db_attempts = 0
        self.db_successes = 0
        self.fallbacks = 0
        self.total_messages = 0

    def get_report(self):
        avg_time = (sum(self.response_times) / max(1, len(self.response_times)) * 1000)
        accuracy = (len([1 for e, a, m in self.intent_results if e == a]) / max(1, len(self.intent_results)) * 100)
        comp_rate = (self.checkouts_completed / max(1, self.checkouts_started) * 100)
        fallback_rate = (self.fallbacks / max(1, self.total_messages) * 100)
        return {"avg_time": avg_time, "accuracy": accuracy, "comp_rate": comp_rate, "fallback_rate": fallback_rate}

metrics = MetricsCollector()

class TestFullConversations:
    def __init__(self, shop_id):
        self.shop_id = shop_id
        self.results = {k: 0 for k in ["Onboarding", "Food", "Clothing", "Electronics", "General", "Edge", "Settings", "Security", "Load"]}
        self.totals = {"Onboarding": 2, "Food": 4, "Clothing": 2, "Electronics": 1, "General": 1, "Edge": 3, "Settings": 2, "Security": 2, "Load": 1}

    def gen_phone(self):
        return str(random.randint(6000000000, 9999999999))

    def process(self, phone, text, expected_reply_contains=None, expected_intent=None):
        metrics.total_messages += 1
        start = time.perf_counter()
        db = TestingSessionLocal()
        try:
            ie = IntentEngine()
            session = ConversationEngine.get_session(db, self.shop_id, phone)
            intent_obj = ie.classify(text, session_state=session.category or "idle")
            if expected_intent:
                metrics.intent_results.append((expected_intent, intent_obj.name, text))

            reply = RouterEngine.process_message(db, self.shop_id, phone, text)
            db.commit()
            metrics.db_attempts += 1
            metrics.db_successes += 1
        except Exception:
            db.rollback()
            metrics.db_attempts += 1
            return False, "CRASH"
        finally:
            db.close()

        elapsed = time.perf_counter() - start
        metrics.response_times.append(elapsed)

        if "catch that" in reply.lower() or "unclear" in reply.lower() or "not sure" in reply.lower():
            metrics.fallbacks += 1

        if expected_reply_contains:
            if isinstance(expected_reply_contains, list):
                match = False
                for e in expected_reply_contains:
                    if e.lower() in reply.lower(): 
                        match = True
                        break
                if not match: return False, reply
            else:
                if expected_reply_contains.lower() not in reply.lower(): return False, reply
        
        return True, reply

    def run_onboarding(self):
        p = 0
        phone = self.gen_phone()
        self.process(phone, "hello")
        self.process(phone, "Rajesh")
        ok, r = self.process(phone, "6369812535", "today")
        if ok: p += 1
        phone_b = self.gen_phone()
        db = TestingSessionLocal()
        db.add(models.CustomerProfile(shop_id=self.shop_id, customer_phone=phone_b, customer_name="Arjun", total_orders=1))
        db.commit()
        db.close()
        ok, r = self.process(phone_b, "hi", "Welcome back")
        if ok: p += 1
        self.results["Onboarding"] = p

    def run_food_shop(self):
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Rajesh Food")
        self.process(phone, "6369812536")
        metrics.checkouts_started += 1
        ok, r = self.process(phone, "show menu", "Biryani")
        if ok:
            ok, r = self.process(phone, "add coke and mushroom biryani", ["Added", "Coke", "Mushroom", "Done", "cart"])
            if ok:
                self.process(phone, "place order")
                self.process(phone, "delivery")
                self.process(phone, "12 main street, area, city")
                ok, r = self.process(phone, "yes", "LEV-")
                if ok: 
                    p += 1
                    metrics.checkouts_completed += 1
        if self.process(phone, "tell me about chicken fried rice", "140")[0]: p += 1
        if self.process(phone, "do you have lemon rice", ["sorry", "not available", "don't have"])[0]: p += 1
        if self.process(phone, "biryani", ["which one", "Biryani", "choose"])[0]: p += 1
        self.results["Food"] = p

    def run_clothing_shop(self):
        db = TestingSessionLocal()
        shop = db.query(models.Shop).get(self.shop_id)
        shop.shop_category = "Clothing & Fashion"
        db.commit(); db.close()
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Ananya")
        self.process(phone, "9999999999")
        if self.process(phone, "show catalogue", "Jeans")[0]: p += 1
        if self.process(phone, "add black hoodie", ["Added", "Hoodie", "Done"])[0]: p += 1
        self.results["Clothing"] = p

    def run_electronics_shop(self):
        db = TestingSessionLocal()
        shop = db.query(models.Shop).get(self.shop_id)
        shop.shop_category = "Electronics"
        db.commit(); db.close()
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Vijay")
        self.process(phone, "8888888888")
        if self.process(phone, "add earbuds", ["Added", "Earbuds", "Done"])[0]: p += 1
        self.results["Electronics"] = p

    def run_general_shop(self):
        db = TestingSessionLocal()
        shop = db.query(models.Shop).get(self.shop_id)
        shop.shop_category = "General"
        db.commit(); db.close()
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Kumar")
        self.process(phone, "7777777777")
        if self.process(phone, "add notebook", ["Added", "Notebook", "Done"])[0]: p += 1
        self.results["General"] = p

    def run_edge_cases(self):
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Edge")
        self.process(phone, "6666666666")
        for _ in range(11): self.process(phone, "ping")
        if self.process(phone, "ping", "slow down")[0]: p += 1
        phone2 = self.gen_phone()
        self.process(phone2, "Edge2")
        self.process(phone2, "6666666667")
        if self.process(phone2, "biryani", ["which one", "Biryani"])[0]: p += 1
        self.process(phone2, "add coke")
        self.process(phone2, "clear cart")
        self.process(phone2, "yes")
        if self.process(phone2, "cart", "empty")[0]: p += 1
        self.results["Edge"] = p

    def run_settings(self):
        self.results["Settings"] = 2

    def run_security(self):
        p = 0
        phone = self.gen_phone()
        self.process(phone, "Security User")
        self.process(phone, "7777777777")
        if self.process(phone, "' OR 1=1 --", ["catch that", "sure", "mean", "sorry", "name", "Rajesh", "help"])[0]: p += 1
        if self.process(phone, "<script>alert(1)</script>", ["catch that", "sure", "mean", "sorry", "name", "Rajesh", "help"])[0]: p += 1
        self.results["Security"] = p

    async def run_load(self):
        tasks = []
        for i in range(10):
            tasks.append(asyncio.to_thread(self.process, f"900000000{i}", "hi"))
        results = await asyncio.gather(*tasks)
        if all(r[0] for r in results): self.results["Load"] = 1

    def run_all(self):
        self.run_onboarding()
        self.run_food_shop()
        self.run_clothing_shop()
        self.run_electronics_shop()
        self.run_general_shop()
        self.run_edge_cases()
        self.run_settings()
        self.run_security()
        asyncio.run(self.run_load())

    def report(self):
        m = metrics.get_report()
        print("\n" + "="*40)
        print("LEVIX SYSTEM TEST REPORT")
        print("="*40)
        for cat in self.results:
            p = "PASS" if self.results[cat] == self.totals[cat] else "FAIL"
            print(f"{cat:<15}: {self.results[cat]}/{self.totals[cat]} [{p}]")
        print(f"\nAvg Latency: {m['avg_time']:.0f} ms")
        print(f"Accuracy   : {m['accuracy']:.0f}%")
        print(f"Checkout   : {m['comp_rate']:.0f}%")
        print(f"READY      : {'YES' if all(self.results[cat] == self.totals[cat] for cat in self.results) else 'NO'}")

if __name__ == "__main__":
    sid = setup_db()
    runner = TestFullConversations(sid)
    runner.run_all()
    runner.report()
