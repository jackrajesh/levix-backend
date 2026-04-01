from app.utils import generate_reply
from types import SimpleNamespace

def test_generate_reply():
    # Helper to mock item
    def mock_item(name, quantity, status, price):
        return SimpleNamespace(name=name, quantity=quantity, status=status, price=price)

    # 1. Available, qty > 5, has price
    item = mock_item("Almond 50g", 10, "available", 50.0)
    reply = generate_reply(item)
    print(f"Test 1: {reply}")
    assert "Yes, Almond 50g is available." in reply
    assert "Price: ₹50" in reply

    # 2. Low stock, 0 < qty <= 5, has price
    item = mock_item("Biscuit", 3, "available", 30.0)
    reply = generate_reply(item)
    print(f"Test 2: {reply}")
    assert "Yes, Biscuit is available, but only a few left." in reply
    assert "Price: ₹30" in reply

    # 3. Out of stock (quantity <= 0), has price (should be hidden)
    item = mock_item("Rice", 0, "available", 100.0)
    reply = generate_reply(item)
    print(f"Test 3: {reply}")
    assert "Sorry, Rice is currently out of stock." in reply
    assert "Price" not in reply

    # 4. Out of stock (status), has price (should be hidden)
    item = mock_item("Sugar", 10, "out_of_stock", 40.0)
    reply = generate_reply(item)
    print(f"Test 4: {reply}")
    assert "Sorry, Sugar is currently out of stock." in reply
    assert "Price" not in reply

    # 5. Coming soon, has price
    item = mock_item("Milk", 0, "coming_soon", 25.0)
    reply = generate_reply(item)
    print(f"Test 5: {reply}")
    assert "Milk will be available soon." in reply
    # Current logic allows price for coming_soon if quantity > 0? 
    # Wait, rule: price_line only if item.price > 0 AND item.status != 'out_of_stock' AND item.quantity > 0
    # In my implementation: item.quantity > 0 is required for price.
    assert "Price" not in reply 

    # 6. Available, price with decimal
    item = mock_item("Pen", 10, "available", 5.50)
    reply = generate_reply(item)
    print(f"Test 6: {reply}")
    assert "Price: ₹5.5" in reply

    print("\nAll automated tests passed!")

if __name__ == "__main__":
    test_generate_reply()
