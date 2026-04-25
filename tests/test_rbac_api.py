from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth, models
from app.database import Base, get_db
from app.main import app
from app.permissions import MASTER_PERMISSION_KEYS, ROLE_TEMPLATES, normalize_permissions


TEST_DB_URL = "sqlite:///./tmp/test_rbac_api.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app, raise_server_exceptions=False)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_team_member(db, shop_id: int, email: str, name: str, role: str, permissions: list[str]):
    member = models.TeamMember(
        shop_id=shop_id,
        name=name,
        email=email,
        password_hash=auth.hash_password("pass1234"),
        role=role,
        permissions=normalize_permissions(permissions),
        is_active=True,
        status="active",
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    owner = models.Shop(
        shop_name="RBAC Shop",
        owner_name="Owner User",
        email="owner@rbac.local",
        phone_number="9999999999",
        password_hash=auth.hash_password("pass1234"),
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)

    item = models.InventoryItem(
        shop_id=owner.id,
        name="Apple",
        quantity=50,
        price=10,
        status="available",
    )
    db.add(item)
    db.flush()
    db.add(models.InventoryAlias(inventory_id=item.id, alias="apple"))

    sale = models.SalesRecord(
        shop_id=owner.id,
        product_id=item.id,
        product_name="Apple",
        date=date.today(),
        quantity=1,
        price=10,
    )
    db.add(sale)

    order = models.Order(
        shop_id=owner.id,
        booking_id="BKG-1",
        order_id="ORD-1",
        customer_name="Cust",
        phone="9999999999",
        address="Addr",
        product="Apple",
        quantity=1,
        unit_price=10,
        total_amount=10,
        status="pending",
    )
    db.add(order)

    pending = models.PendingRequest(
        shop_id=owner.id,
        product_name="Orange",
        customer_message="Need Orange",
        request_type="customer",
    )
    db.add(pending)

    log = models.ActivityLog(
        shop_id=owner.id,
        user_name="Owner User",
        role="Owner",
        category="System Events",
        action="Seed log",
        target="seed",
        severity="info",
    )
    db.add(log)
    db.commit()

    _create_team_member(
        db,
        owner.id,
        "staff_inventory@rbac.local",
        "Inventory Staff",
        "Inventory Manager",
        ["inventory_view", "inventory_add", "inventory_edit", "stock_adjust", "price_change"],
    )
    _create_team_member(
        db,
        owner.id,
        "staff_cashier@rbac.local",
        "Cashier Staff",
        "Cashier",
        ["orders_view", "sales_create", "inventory_view"],
    )
    _create_team_member(
        db,
        owner.id,
        "staff_manager@rbac.local",
        "Manager Staff",
        "Manager",
        ROLE_TEMPLATES["Manager"],
    )
    _create_team_member(
        db,
        owner.id,
        "staff_support@rbac.local",
        "Support Staff",
        "Support Agent",
        ROLE_TEMPLATES["Support Agent"],
    )
    _create_team_member(
        db,
        owner.id,
        "staff_restricted@rbac.local",
        "Restricted Staff",
        "Restricted",
        [],
    )

    for permission in MASTER_PERMISSION_KEYS:
        _create_team_member(
            db,
            owner.id,
            f"perm_{permission}@rbac.local",
            f"Perm {permission}",
            f"Only {permission}",
            [permission],
        )

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def _login(email: str, password: str = "pass1234") -> str:
    response = client.post("/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


RBAC_ROUTE_CASES = [
    ("inbox_view", "GET", "/pending", None, "normal"),
    ("inbox_reply", "POST", "/pending/bulk-delete", {"ids": [1]}, "normal"),
    ("inventory_view", "GET", "/inventory", None, "normal"),
    ("inventory_add", "POST", "/inventory/add", {"name": "Banana", "quantity": 5, "price": 12, "status": "available", "aliases": ["banana"]}, "normal"),
    ("inventory_edit", "POST", "/inventory/update-status/1", {"status": "available"}, "normal"),
    ("inventory_delete", "DELETE", "/inventory/1", None, "normal"),
    ("stock_adjust", "POST", "/inventory/1/quantity", {"amount": 1}, "normal"),
    ("price_change", "POST", "/inventory/edit/1", {"name": "Apple", "quantity": 50, "price": 11, "aliases": ["apple"]}, "normal"),
    ("orders_view", "GET", "/orders", None, "normal"),
    ("orders_edit", "PATCH", "/orders/BKG-1/accept", None, "normal"),
    ("orders_cancel", "PATCH", "/orders/BKG-1/reject", None, "normal"),
    ("sales_create", "POST", "/sales/set", {"product_id": 1, "date": str(date.today()), "quantity": 1, "price": 10}, "normal"),
    ("sales_create", "GET", "/sales", None, "normal"),
    ("sales_delete", "DELETE", "/sales/1", None, "normal"),
    ("analytics_view", "GET", "/analytics", None, "normal"),
    ("analytics_export", "GET", "/analytics/export", None, "normal"),
    ("logs_view", "GET", "/api/logs", None, "normal"),
    ("logs_export", "GET", "/api/logs/export", None, "normal"),
    ("logs_clear", "DELETE", "/api/logs/clear", None, "owner_only"),
    ("billing_view", "GET", "/api/plans/current", None, "normal"),
    ("billing_manage", "POST", "/api/plans/upgrade?addon_type=smart_ai", None, "normal"),
    ("settings_edit", "POST", "/admin/shop-name", {"shop_name": "RBAC Shop Updated"}, "normal"),
    ("team_view", "GET", "/api/team/members", None, "normal"),
    ("team_add_member", "POST", "/api/team/members", {"name": "Tmp", "email": "tmp_member@rbac.local", "password": "pass1234", "role": "Temp", "permissions": []}, "normal"),
    ("team_edit_member", "PUT", "/api/team/members/1", {"name": "Edited Name"}, "normal"),
    ("team_remove_member", "DELETE", "/api/team/members/1", None, "normal"),
    ("team_manage_permissions", "POST", "/api/team/roles", {"name": "Custom Role", "permissions": ["inventory_view"]}, "normal"),
    ("analytics_export", "GET", "/sales/export", None, "normal"),
]


def _request(method: str, path: str, token: str, payload):
    kwargs = {"headers": _auth_headers(token)}
    if payload is not None:
        kwargs["json"] = payload
    return client.request(method, path, **kwargs)


@pytest.mark.parametrize("permission,method,path,payload,mode", RBAC_ROUTE_CASES)
def test_permission_block_and_allow(permission, method, path, payload, mode):
    allowed_token = _login(f"perm_{permission}@rbac.local")
    blocked_token = _login("staff_restricted@rbac.local")

    allowed_response = _request(method, path, allowed_token, payload)
    if mode == "owner_only":
        assert allowed_response.status_code == 403
    else:
        assert allowed_response.status_code != 403, (
            f"User with {permission} got blocked on {method} {path}: {allowed_response.text}"
        )

    blocked_response = _request(method, path, blocked_token, payload)
    assert blocked_response.status_code == 403, (
        f"Restricted user unexpectedly accessed {method} {path}: {blocked_response.text}"
    )
    body = blocked_response.json()
    if "message" in body:
        assert body["message"] == "Insufficient permissions"
    elif "detail" in body:
        assert body["detail"] == "Insufficient permissions"


def test_owner_bypass_can_access_all_guarded_routes():
    owner_token = _login("owner@rbac.local")
    failures = []
    for _, method, path, payload, _ in RBAC_ROUTE_CASES:
        response = _request(method, path, owner_token, payload)
        if response.status_code == 403:
            failures.append(f"{method} {path}")
    assert not failures, f"Owner bypass failed for routes: {failures}"


def test_role_presets_have_expected_minimum_access():
    inventory_token = _login("staff_inventory@rbac.local")
    cashier_token = _login("staff_cashier@rbac.local")
    manager_token = _login("staff_manager@rbac.local")
    support_token = _login("staff_support@rbac.local")

    assert client.get("/inventory", headers=_auth_headers(inventory_token)).status_code != 403
    assert client.get("/orders", headers=_auth_headers(cashier_token)).status_code != 403
    assert client.get("/analytics", headers=_auth_headers(manager_token)).status_code != 403
    assert client.get("/pending", headers=_auth_headers(support_token)).status_code != 403


def test_export_permissions_matrix():
    logs_only = _login("perm_logs_export@rbac.local")
    analytics_only = _login("perm_analytics_export@rbac.local")
    both = _login("staff_manager@rbac.local")  # Manager template includes both export permissions.
    none = _login("staff_restricted@rbac.local")
    owner = _login("owner@rbac.local")

    # 1) Logs-only staff can export logs, blocked from analytics export.
    assert client.get("/api/logs/export", headers=_auth_headers(logs_only)).status_code != 403
    assert client.get("/analytics/export", headers=_auth_headers(logs_only)).status_code == 403

    # 2) Analytics-only staff can export analytics (and sales), blocked from logs export.
    assert client.get("/analytics/export", headers=_auth_headers(analytics_only)).status_code != 403
    assert client.get("/sales/export-excel", headers=_auth_headers(analytics_only)).status_code != 403
    assert client.get("/api/logs/export", headers=_auth_headers(analytics_only)).status_code == 403

    # 3) Staff with both can export both.
    assert client.get("/analytics/export", headers=_auth_headers(both)).status_code != 403
    assert client.get("/api/logs/export", headers=_auth_headers(both)).status_code != 403

    # 4) Staff with no export permissions is blocked from both.
    assert client.get("/analytics/export", headers=_auth_headers(none)).status_code == 403
    assert client.get("/api/logs/export", headers=_auth_headers(none)).status_code == 403

    # 5) Owner bypass still works everywhere.
    assert client.get("/analytics/export", headers=_auth_headers(owner)).status_code != 403
    assert client.get("/api/logs/export", headers=_auth_headers(owner)).status_code != 403
