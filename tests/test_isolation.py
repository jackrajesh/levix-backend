"""
Multi-Tenant Shop Isolation Test
Tests that Shop A and Shop B have completely isolated data.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import engine
from app.models import Base

client = TestClient(app)

def register_and_login(shop_name, owner, email, password):
    """Register a shop and login, returning the auth header."""
    r = client.post("/register", json={
        "shop_name": shop_name,
        "owner_name": owner,
        "email": email,
        "password": password
    })
    if r.status_code == 400 and "already registered" in r.text:
        pass  # Already registered from a previous run
    elif r.status_code != 200:
        print(f"  FAIL register {email}: {r.status_code} {r.text}")
        return None
    
    r = client.post("/login", data={"username": email, "password": password})
    if r.status_code != 200:
        print(f"  FAIL login {email}: {r.status_code} {r.text}")
        return None
    
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_isolation():
    print("=== Multi-Tenant Isolation Test ===\n")
    
    # Setup
    print("1. Registering Shop A and Shop B...")
    headers_a = register_and_login("Alpha Store", "Alice", "alpha@test.com", "pass123")
    headers_b = register_and_login("Beta Store", "Bob", "beta@test.com", "pass456")
    
    if not headers_a or not headers_b:
        print("ABORT: Could not register/login both shops.")
        return
    print("   OK\n")
    
    # ---------- INVENTORY ISOLATION ----------
    print("2. Shop A adds product 'iPhone 16'...")
    r = client.post("/inventory/add", json={
        "name": "iPhone 16",
        "status": "available",
        "aliases": ["iphone16", "iphone 16"]
    }, headers=headers_a)
    if r.status_code == 400 and "already exists" in r.text:
        print("   (already exists, skipping)")
    elif r.status_code != 200:
        print(f"   FAIL: {r.status_code} {r.text}")
        return
    else:
        print("   OK")
    
    print("3. Shop B checks its inventory (should be empty or not have iPhone 16)...")
    r = client.get("/inventory", headers=headers_b)
    assert r.status_code == 200
    inv_b = r.json().get("inventory", [])
    names_b = [i["name"] for i in inv_b]
    if "iPhone 16" in names_b:
        print("   FAIL: Shop B can see Shop A's inventory!")
        return
    print(f"   OK — Shop B inventory has {len(inv_b)} items, no 'iPhone 16'\n")
    
    print("4. Shop A checks its inventory (should have iPhone 16)...")
    r = client.get("/inventory", headers=headers_a)
    assert r.status_code == 200
    inv_a = r.json().get("inventory", [])
    names_a = [i["name"] for i in inv_a]
    if "iPhone 16" not in names_a:
        print("   FAIL: Shop A cannot see its own product!")
        return
    print(f"   OK — Shop A inventory has {len(inv_a)} items, 'iPhone 16' found\n")
    
    # ---------- SALES ISOLATION ----------
    product_id_a = next(i["id"] for i in inv_a if i["name"] == "iPhone 16")
    
    print("5. Shop A records a sale for iPhone 16...")
    r = client.post("/sales/set", json={
        "product_id": product_id_a,
        "date": "2026-03-01",
        "quantity": 5
    }, headers=headers_a)
    if r.status_code != 200:
        print(f"   FAIL: {r.status_code} {r.text}")
        return
    print("   OK")
    
    print("6. Shop B checks sales (should be empty or not contain Shop A's sale)...")
    r = client.get("/sales", headers=headers_b)
    assert r.status_code == 200
    sales_b = r.json().get("records", [])
    if any(s.get("product_name") == "iPhone 16" for s in sales_b):
        print("   FAIL: Shop B can see Shop A's sales!")
        return
    print(f"   OK — Shop B has {len(sales_b)} sales records, none for 'iPhone 16'\n")
    
    # ---------- PENDING ISOLATION ----------
    print("7. Shop B adds a pending request via webhook...")
    r = client.post("/webhook", json={
        "customer_message": "Do you have Samsung Galaxy S25?",
        "shop_id": None  # We need Shop B's ID
    }, headers=headers_b)
    # Get Shop B's ID
    r_me = client.get("/me", headers=headers_b)
    shop_b_id = r_me.json()["shop_id"]
    
    r = client.post("/webhook", json={
        "customer_message": "Do you have Samsung Galaxy S25?",
        "shop_id": shop_b_id
    })
    print(f"   Webhook reply: {r.json().get('reply', 'N/A')}")
    
    print("8. Shop A checks pending (should NOT see Shop B's pending)...")
    r = client.get("/pending", headers=headers_a)
    assert r.status_code == 200
    pending_a = r.json()
    if any(p.get("product", "").lower() == "samsung galaxy s25" for p in pending_a):
        print("   FAIL: Shop A can see Shop B's pending requests!")
        return
    print(f"   OK — Shop A has {len(pending_a)} pending items, none for 'Samsung Galaxy S25'\n")
    
    # ---------- ANALYTICS ISOLATION ----------
    print("9. Shop B checks analytics (should NOT contain Shop A's logs)...")
    r = client.get("/analytics", headers=headers_b)
    assert r.status_code == 200
    analytics_b = r.json()
    if analytics_b.get("product_request_counts", {}).get("iPhone 16"):
        print("   FAIL: Shop B analytics contain Shop A's log data!")
        return
    print(f"   OK — Shop B analytics clean\n")
    
    # ---------- CROSS-SHOP ACCESS ATTEMPT ----------
    print("10. Shop B tries to delete Shop A's product (should fail)...")
    r = client.delete(f"/inventory/{product_id_a}", headers=headers_b)
    if r.status_code == 404:
        print("   OK — Correctly denied (404)")
    else:
        print(f"   FAIL: Got {r.status_code} instead of 404. Shop B accessed Shop A's resource!")
        return
    
    print("\n=== ALL ISOLATION TESTS PASSED ===")

if __name__ == "__main__":
    test_isolation()
