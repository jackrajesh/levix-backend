import os
import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import models

client = TestClient(app)

def verify_analytics_hardening():
    # We need a token to access analytics. For a simple check, we'll verify the function logic.
    from app.routes.analytics import get_inventory_insights
    
    class MockShop: id = 1
    db = SessionLocal()
    
    print("--- 1. Testing Hardened Analytics (Empty Shop) ---")
    # Even if shop 1 is empty or has items but no logs
    insights = get_inventory_insights(current_shop=MockShop(), db=db)
    
    expected_keys = ["top_requested", "top_sold", "low_demand_requests", "low_demand_sales"]
    for key in expected_keys:
        assert key in insights
        assert isinstance(insights[key], list)
        print(f"  Key '{key}' present and is a list.")

    print("\n--- 2. Testing Error Recovery ---")
    # We'll intentionally pass a None DB to trigger an exception
    insights_error = get_inventory_insights(current_shop=MockShop(), db=None)
    assert insights_error == {
        "top_requested": [],
        "top_sold": [],
        "low_demand_requests": [],
        "low_demand_sales": []
    }
    print("  Successfully recovered from internal error with safe default.")
    
    db.close()

if __name__ == "__main__":
    os.environ["PYTHONPATH"] = "."
    verify_analytics_hardening()
