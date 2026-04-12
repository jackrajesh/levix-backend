import os
import sys
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app import models
from app.services.product_service import fuzzy_match_product, normalize_product
from app.services.ai_parser import parse_message_with_ai

def verify_final_overhaul():
    db = SessionLocal()
    # Using shop_id 3 as it has existing data in this environment
    shop_id = 3
    
    print("--- 1. Testing Spelling & Multi-Product Parsing ---")
    test_msg = "ciken wins and parrotta iruka"
    ai_data = parse_message_with_ai(test_msg)
    
    if ai_data:
        print(f"Products Extracted: {ai_data.get('products')}")
        print(f"Intent: {ai_data.get('intent')}")
        print(f"Tone: {ai_data.get('tone')}")
    
    print("\n--- 2. Testing Dynamic Fuzzy Threshold (Short Query) ---")
    # "wins" -> "wings". Target in DB is "Chiken Wings".
    match_short = fuzzy_match_product("wins", db, shop_id)
    print(f"Match for 'wins': {match_short.name if match_short else 'None'}")
    
    print("\n--- 3. Testing Alias Expansion & Fallback ---")
    # "leg pis" -> "leg piece". Target in DB is "Chiken Leg Piece".
    match_alias = fuzzy_match_product("leg pis", db, shop_id)
    print(f"Match for 'leg pis': {match_alias.name if match_alias else 'None'}")
    
    # "spicy chiken biriyani" -> "Chiken Briyani"
    match_fallback = fuzzy_match_product("spicy chiken biriyani", db, shop_id)
    print(f"Match for 'spicy chiken biriyani': {match_fallback.name if match_fallback else 'None'}")

    print("\n--- 4. Testing Analytics Structure ---")
    from app.routes.analytics import get_inventory_insights
    class MockShop: id = shop_id
    insights = get_inventory_insights(current_shop=MockShop(), db=db)
    print(f"Insights Keys: {list(insights.keys())}")
    for key in ["top_requested", "top_sold", "low_demand"]:
        result = insights.get(key)
        print(f"  {key} is list: {isinstance(result, list)} (Value: {result})")
    
    db.close()

if __name__ == "__main__":
    os.environ["PYTHONPATH"] = "."
    verify_final_overhaul()
