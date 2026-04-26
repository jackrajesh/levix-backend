from app.database import SessionLocal
from app import models
import json

def verify_data():
    db = SessionLocal()
    try:
        results = {}
        
        # 1. Users (Team members)
        results["team_members"] = db.query(models.TeamMember).count()
        
        # 2. Shops
        results["shops"] = db.query(models.Shop).count()
        
        # 3. Inventory (Products)
        results["products"] = db.query(models.InventoryItem).count()
        
        # 4. Orders
        results["orders"] = db.query(models.Order).count()
        
        # 5. Pending Requests
        results["pending_requests"] = db.query(models.PendingRequest).count()
        
        # 6. AI Leads
        results["ai_leads"] = db.query(models.AILead).count()
        
        print(json.dumps(results, indent=4))
        
    except Exception as e:
        print(f"Error during verification: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    verify_data()
