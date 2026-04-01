from fastapi.testclient import TestClient
from app.main import app
from app.database import engine
from app.models import Base

client = TestClient(app)

def test_run_all():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    
    print("Testing /register...")
    response = client.post(
        "/register",
        json={"shop_name": "Test Shop", "owner_name": "Test Owner", "email": "test@shop.com", "password": "password123"}
    )
    if response.status_code != 200:
        if response.status_code == 400 and "already registered" in response.text:
            print("Already registered, continuing...")
        else:
            print("Register failed:", response.status_code, response.text)
            return
    else:
        print("Register passed")
    
    print("Testing /login...")
    response = client.post(
        "/login",
        data={"username": "test@shop.com", "password": "password123"}
    )
    if response.status_code != 200:
        print("Login failed:", response.status_code, response.text)
        return
    token = response.json()["access_token"]
    print("Login passed")
    
    print("Testing /me...")
    response = client.get(
        "/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    if response.status_code != 200:
        print("/me failed:", response.status_code, response.text)
        return
    print("/me passed")
    print("All tests passed!")

if __name__ == "__main__":
    test_run_all()
