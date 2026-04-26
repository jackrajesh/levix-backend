import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from app.services.ai_parser import normalize_ai_product, parse_message_with_ai

def test_normalization():
    test_cases = [
        ("milk packet", "milk"),
        ("paal packet", "milk"),
        ("chai bro", "tea"),
        ("biriyani pa", "biryani"),
        ("milk 1 litre", "milk"),
        ("bread item pls", "bread")
    ]
    
    print("--- Testing Normalization ---")
    for input_txt, expected in test_cases:
        actual = normalize_ai_product(input_txt)
        status = "PASS" if actual == expected else f"FAIL (Got: '{actual}')"
        print(f"'{input_txt}' -> '{actual}' [{status}]")

def test_message_flow():
    # Note: Requires a real shop_id and DB items to fully test fuzzy match
    # For now, we test the AI parsing + Normalization part
    print("\n--- Testing AI Parsing + Normalization ---")
    messages = [
        "rendu paal packet iruka pa",
        "milk venum da",
        "chai iruka bro"
    ]
    
    for msg in messages:
        print(f"\nParsing: '{msg}'")
        res = parse_message_with_ai(msg)
        print(f"AI Extracted: {res.get('product')}")
        norm = normalize_ai_product(res.get('product'))
        print(f"Normalized: {norm}")

if __name__ == "__main__":
    test_normalization()
    test_message_flow()
