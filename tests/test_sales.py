from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)

def test_overwrite():
    # Setup: Register/Login as a test user
    client.post("/register", json={
        "shop_name": "Test Shop",
        "owner_name": "Tester",
        "email": "test@sales.com",
        "password": "password123"
    })
    login_res = client.post("/login", data={"username": "test@sales.com", "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Add product to inventory first so we can use product_id
    add_res = client.post("/inventory/add", json={
        "name": "Chilli Powder",
        "quantity": 100,
        "aliases": ["chilli"]
    }, headers=headers)
    product_id = add_res.json()["product"]["id"]
    
    # 2. First entry
    client.post("/sales/set", json={
        "product_id": product_id,
        "date": "2026-02-27",
        "quantity": 10
    }, headers=headers)
    
    # 3. Second entry (overwrite)
    client.post("/sales/set", json={
        "product_id": product_id,
        "date": " 2026-02-27 ", # Test date normalization
        "quantity": 99
    }, headers=headers)
    
    # 4. Verify via API
    res = client.get("/sales?start_date=2026-02-27&end_date=2026-02-27", headers=headers)
    data = res.json()
    
    records = [r for r in data["records"] if r["product_id"] == product_id]
    print(f"Records for Chilli Powder on 2026-02-27: {len(records)}")
    
    assert len(records) == 1
    assert records[0]["quantity"] == 99
    
    # 5. Verify stock deduction
    inv_res = client.get("/inventory", headers=headers)
    inv_data = inv_res.json()
    item = next(i for i in inv_data["inventory"] if i["id"] == product_id)
    # Start 100, set to 10 (90 left), then set to 99 (start 100 - 99 = 1 left)
    assert item["quantity"] == 1

if __name__ == "__main__":
    test_overwrite()
