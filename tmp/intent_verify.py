import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from app.services.ai_parser import parse_message_with_ai, normalize_ai_product, generate_ai_response

def test_intent_safeguard():
    print("\n--- Testing Intent Validation Safeguard ---")
    # Message: "hi, do you have milk?" 
    # AI might say greeting, but it has a product.
    msg = "hi, do you have milk?"
    res = parse_message_with_ai(msg)
    print(f"Input: {msg}")
    print(f"AI Initial Output: {res}")
    
    intent = res.get("intent")
    product = res.get("product")
    
    # Simulate safeguard logic from messages.py
    if intent in ["greeting", "inquiry", "unknown"] and product:
        intent = "check_availability"
        print(f"Safeguard: Overriding intent to {intent}")

def test_order_intent():
    print("\n--- Testing Order Intent Responses ---")
    # Case 1: Order available
    data_avail = {
        "intent": "order",
        "product": "Milk",
        "available": True,
        "quantity": 2
    }
    # In messages.py, for order we use a specific format
    reply = f"Got it 👍 {data_avail['quantity']} {data_avail['product']}. Shall I confirm the order?"
    print(f"Order Available Reply: {reply}")
    
    # Case 2: Order OOS
    data_oos = {
        "intent": "order",
        "product": "Milk",
        "available": False,
        "quantity": 2
    }
    reply_oos = f"Sorry, {data_oos['product']} is currently not available."
    print(f"Order OOS Reply: {reply_oos}")

if __name__ == "__main__":
    test_intent_safeguard()
    test_order_intent()
