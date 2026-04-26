import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils import generate_reply

class MockItem:
    def __init__(self, name, quantity, status, price):
        self.name = name
        self.quantity = quantity
        self.status = status
        self.price = price

def run_tests():
    print("--- Test 1. Available ---")
    item1 = MockItem("Test Product A", 10, "available", 500)
    print(generate_reply(item1))
    
    print("\n--- Test 2. Low Stock ---")
    item2 = MockItem("Test Product A", 3, "available", 150.50)
    print(generate_reply(item2))

    print("\n--- Test 3. Out of stock ---")
    item3 = MockItem("Test Product A", 0, "available", 20)
    print(generate_reply(item3))

    print("\n--- Test 4. Coming Soon ---")
    item4 = MockItem("Test Product A", 0, "coming_soon", 100)
    print(generate_reply(item4))

    print("\n--- Test 5. Owner check ---")
    item5 = MockItem("Test Product A", 10, "available", None)
    print(generate_reply(item5))
    
    print("\n--- Test 6. Owner check (Manual status) ---")
    item6 = MockItem("Test Product A", 20, "manual", 100)
    print(generate_reply(item6))

if __name__ == "__main__":
    run_tests()
