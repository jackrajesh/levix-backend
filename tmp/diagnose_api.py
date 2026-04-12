from app.database import SessionLocal
from app.models import Shop, InventoryItem, SalesRecord, LogEntry
from app.routes.inventory import get_inventory
from app.routes.analytics import get_analytics, get_inventory_insights

def run():
    db = SessionLocal()
    shop = db.query(Shop).first()
    if not shop:
        print("No shop found.")
        return
    
    print(f"Testing for shop: {shop.shop_name} (ID: {shop.id})")
    
    print("\n--- Testing GET /inventory ---")
    try:
        inv = get_inventory(current_shop=shop, db=db)
        print("Success! Items:", len(inv))
    except Exception as e:
        print("ERROR in /inventory:")
        import traceback
        traceback.print_exc()

    print("\n--- Testing GET /analytics ---")
    try:
        analytics = get_analytics(current_shop=shop, db=db)
        print("Success! Analytics keys:", list(analytics.keys()))
    except Exception as e:
        print("ERROR in /analytics:")
        import traceback
        traceback.print_exc()

    print("\n--- Testing GET /inventory/insights ---")
    try:
        insights = get_inventory_insights(current_shop=shop, db=db)
        print("Success! Insights keys:", list(insights.keys()))
    except Exception as e:
        print("ERROR in /inventory/insights:")
        import traceback
        traceback.print_exc()
        
    db.close()

if __name__ == '__main__':
    run()
