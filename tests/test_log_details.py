from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app import models, auth


TEST_DB_URL = "sqlite:///./tmp/test_log_details.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _seed_owner():
    db = TestingSessionLocal()
    shop = models.Shop(
        shop_name="Logs Shop",
        owner_name="Tester",
        email="logs@test.com",
        phone_number="9999999999",
        password_hash=auth.hash_password("password123"),
    )
    db.add(shop)
    db.commit()
    db.close()


def _login_token():
    response = client.post(
        "/login",
        data={"username": "logs@test.com", "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_log_details_inventory_edit_and_login():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_owner()
    token = _login_token()
    headers = {"Authorization": f"Bearer {token}"}

    add_res = client.post(
        "/inventory/add",
        headers=headers,
        json={"name": "Ice Cream", "quantity": 8, "price": 50, "aliases": ["ice cream"]},
    )
    assert add_res.status_code == 200
    product_id = add_res.json()["product"]["id"]

    edit_res = client.post(
        f"/inventory/edit/{product_id}",
        headers=headers,
        json={"name": "Ice cream premium", "quantity": 12, "price": 60, "aliases": ["ice cream premium"]},
    )
    assert edit_res.status_code == 200

    logs_res = client.get("/api/logs?limit=50&page=1", headers=headers)
    assert logs_res.status_code == 200
    logs = logs_res.json()["logs"]
    assert len(logs) >= 2

    db = TestingSessionLocal()
    inventory_log = db.query(models.ActivityLog).filter(models.ActivityLog.action_type == "inventory_edit").first()
    login_log = db.query(models.ActivityLog).filter(models.ActivityLog.action_type == "login").first()
    db.close()

    assert inventory_log is not None
    assert login_log is not None

    inventory_detail = client.get(f"/api/logs/{inventory_log.id}", headers=headers)
    assert inventory_detail.status_code == 200
    inventory_data = inventory_detail.json()
    assert inventory_data["action_type"] == "inventory_edit"
    assert inventory_data["entity_type"] == "product"
    assert inventory_data["old_values"]["name"] == "Ice Cream"
    assert inventory_data["new_values"]["name"] == "Ice cream premium"
    assert inventory_data["old_values"]["price"] == 50.0
    assert inventory_data["new_values"]["price"] == 60.0

    login_detail = client.get(f"/api/logs/{login_log.id}", headers=headers)
    assert login_detail.status_code == 200
    login_data = login_detail.json()
    assert login_data["action_type"] == "login"
    assert login_data["old_values"] is None
    assert login_data["new_values"] is None
    assert isinstance(login_data.get("metadata"), dict)
