import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from app.services.ai_parser import normalize_ai_product, parse_message_with_ai

def test_normalization_advanced():
    print("\n--- Testing Advanced Normalization ---")
    test_cases = [
        ("rendu milk", "milk"),
        ("2 milk packet", "milk"),
        ("onnu tea", "tea"),
        ("moonu biriyani", "biryani"),
        ("hi boss rendu paal", "milk")
    ]
    for inp, expected in test_cases:
        res = normalize_ai_product(inp)
        print(f"Input: '{inp}' -> Result: '{res}'")

def test_safety_guard_logic():
    print("\n--- Testing Safety Guard Logic (Manual Check) ---")
    # Simulation of the logic in messages.py
    def simulate_reply_guard(intent, matched_item, ai_reply):
        if intent in ["check_availability", "order"] and matched_item:
            return "[DB Template Override]"
        elif not matched_item and any(x in ai_reply.lower() for x in ["available", "price", "rs", "₹"]):
            return "[Safety Overridden: Hallucination Detected]"
        return ai_reply

    print(f"Case 1 (Accurate Order): {simulate_reply_guard('order', True, 'Sure!')}")
    print(f"Case 2 (Hallucination): {simulate_reply_guard('greeting', False, 'Yes, it is available for Rs 50')}")
    print(f"Case 3 (Normal Chat): {simulate_reply_guard('greeting', False, 'Hello!')}")

if __name__ == "__main__":
    test_normalization_advanced()
    test_safety_guard_logic()
    
    # Try one real AI call if quota allows
    print("\n--- Testing One Real AI Call ---")
    res = parse_message_with_ai("rendu milk iruka bro")
    print(f"AI Result: {res}")
