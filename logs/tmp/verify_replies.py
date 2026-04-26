import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from app.utils import generate_reply

class MockItem:
    def __init__(self, name, status, quantity, price):
        self.name = name
        self.status = status
        self.quantity = quantity
        self.price = price

def test_replies():
    print("--- Final Testing generate_reply ---")
    
    # Cases based on user requirements
    
    # 1. Available, qty > 5, has price
    item = MockItem("Almond 50g", "available", 10, 50.0)
    res = generate_reply(item)
    expected = "Yes, Almond 50g is available.\n\nPrice: ₹50"
    print(f"Test 1 (Available, Qty 10): {res}")
    assert res == expected, f"Expected '{expected}', got '{res}'"
    
    # 2. Available, low stock (qty 3), has price
    item = MockItem("Biscuit", "available", 3, 30.0)
    res = generate_reply(item)
    expected = "Yes, Biscuit is available, but only a few left.\n\nPrice: ₹30"
    print(f"Test 2 (Available, Qty 3): {res}")
    assert res == expected, f"Expected '{expected}', got '{res}'"
    
    # 3. Available, zero stock
    item = MockItem("Rice", "available", 0, 100.0)
    res = generate_reply(item)
    expected = "Sorry, Rice is currently out of stock."
    print(f"Test 3 (Available, Qty 0): {res}")
    assert "Price" not in res, "Price should not be in OOS reply"
    assert res == expected, f"Expected '{expected}', got '{res}'"
    
    # 4. Out of stock status
    item = MockItem("Milk", "out_of_stock", 10, 40.0)
    res = generate_reply(item)
    expected = "Sorry, Milk is currently out of stock."
    print(f"Test 4 (OOS status): {res}")
    assert "Price" not in res, "Price should not be in OOS reply"
    
    # 5. Coming soon, has price
    item = MockItem("Nuts", "coming_soon", 0, 200.0)
    res = generate_reply(item)
    expected = "Nuts will be available soon.\n\nPrice: ₹200"
    print(f"Test 5 (Coming Soon): {res}")
    assert res == expected, f"Expected '{expected}', got '{res}'"

    # 6. Available with price 0 (should not show price)
    item = MockItem("Salt", "available", 20, 0.0)
    res = generate_reply(item)
    print(f"Test 6 (Price 0): {res}")
    assert "Price" not in res, "Price line should be skipped if 0"
    
    # 7. With product_name override
    item = MockItem("Original Name", "available", 10, 50.0)
    res = generate_reply(item, "Custom Name")
    print(f"Test 7 (Override): {res}")
    assert "Custom Name" in res
    assert "Original Name" not in res

    print("\nAll verification tests passed!")

if __name__ == "__main__":
    try:
        test_replies()
    except Exception as e:
        print(f"\nVerification FAILED: {e}")
        sys.exit(1)
