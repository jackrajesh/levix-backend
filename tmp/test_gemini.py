import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from app.services.ai_parser import parse_message_with_ai

def test():
    messages = [
        "milk 2 packet iruka",
        "bread and butter venum",
        "give me 5 bananas"
    ]
    
    for msg in messages:
        print(f"\nParsing: '{msg}'")
        result = parse_message_with_ai(msg)
        print(f"Result: {result}")

if __name__ == "__main__":
    test()
