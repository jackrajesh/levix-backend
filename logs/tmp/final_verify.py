import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from app.services.ai_parser import parse_message_with_ai, normalize_ai_product, generate_ai_response

def test_ai_generator():
    print("\n--- Testing AI Response Generator ---")
    
    # Mode 1: System (Product found)
    system_data = {
        "product": "Milk",
        "available": True,
        "price": 40.0,
        "quantity": 2
    }
    system_msg = "milk iruka pa"
    print(f"\nSystem Mode Input: {system_msg}")
    reply = generate_ai_response(system_data, system_msg)
    print(f"Reply: {reply}")
    
    # Mode 2: Chat (No product)
    chat_data = {}
    chat_msg = "hello boss"
    print(f"\nChat Mode Input: {chat_msg}")
    reply = generate_ai_response(chat_data, chat_msg)
    print(f"Reply: {reply}")

def test_parser_timeout():
    print("\n--- Testing Parser Timeout (8s) ---")
    # This just ensures the code runs without error with the new timeout
    msg = "do you have bread?"
    res = parse_message_with_ai(msg)
    print(f"Parser Result: {res}")

if __name__ == "__main__":
    test_ai_generator()
    test_parser_timeout()
