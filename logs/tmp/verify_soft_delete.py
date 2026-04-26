import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import models
from app.routes.auth import verify_password
from unittest.mock import patch
from app.routes import auth

client = TestClient(app)

def test_soft_delete():
    # 1. Login to get token
    # We can just mock the dependency if auth is complex, 
    # but let's override the get_current_shop dependency
    db = SessionLocal()
    shop = db.query(models.Shop).first()
    if not shop:
        print("No shop found to test with")
        return
        
    app.dependency_overrides[auth.get_current_shop] = lambda: shop
    app.dependency_overrides[auth.get_db] = lambda: SessionLocal()

    # 2. Add an item
    response = client.post("/inventory/add", json={
        "name": "Soft Delete Test Item",
        "aliases": ["test_soft_delete"],
        "price": 100,
        "quantity": 10
    })
    
    assert response.status_code == 200, f"Failed to add: {response.text}"
    item_id = response.json()["product"]["id"]
    
    # 3. GET inventory returns it
    inv_response = client.get("/inventory")
    items = inv_response.json()["inventory"]
    assert any(i["id"] == item_id for i in items), "Item not in GET /inventory"
    
    # 4. Bulk Delete it
    del_response = client.delete("/inventory/bulk-delete", json={"ids": [item_id]})
    assert del_response.status_code == 200, f"Delete failed: {del_response.text}"
    
    # 5. GET inventory does not return it
    inv_response2 = client.get("/inventory")
    items2 = inv_response2.json()["inventory"]
    assert not any(i["id"] == item_id for i in items2), "Item still in GET /inventory"
    
    # 6. Database row still exists with is_deleted = True
    db_item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    assert db_item is not None, "Item was hard deleted!"
    assert db_item.is_deleted == True, "Item is_deleted is not True!"
    
    # cleanup db session
    db.close()
    
    print("Verification Passed: Item is soft-deleted, not returned by API, but exists in DB.")

if __name__ == "__main__":
    test_soft_delete()
