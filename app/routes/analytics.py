from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List, Dict, Any
from datetime import datetime

from .. import models
from ..database import get_db
from .auth import get_current_shop

router = APIRouter(tags=["analytics"])

def is_valid_product_name(n: Any) -> bool:
    """
    STRICT ANALYTICS FILTER: Rejects non-product strings, greetings, and junk.
    """
    from ..utils import CUSTOMER_FILLER_WORDS
    
    if not n or not isinstance(n, str) or not n.strip(): return False
    
    nl = n.lower().strip()
    
    # 1. Base length check (min 3 chars)
    if len(nl) < 3: return False
    
    # 2. Filler words check
    if nl in CUSTOMER_FILLER_WORDS: return False
    
    # 3. System junk & Logic noise
    blacklist = {
        "file", "word", "length", "each", "debug", "single", "something", "uh", "umm", "give", "take",
        "after", "before", "matching", "intent", "products", "tones", "task", "goal", "instructions", 
        "priority", "modify", "instructions", "changes", "appservicesproductservice"
    }
    if nl in blacklist or any(word in nl for word in ["file", "word", "length", "instructions", "modify"]):
        return False
    
    # 4. Multi-word limit (Real products usually <= 2 words)
    if len(nl.split()) > 2: return False
    
    return True

@router.get("/analytics")
def get_analytics(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    """
    Overhauled analytics with default-safe structures and revenue tracking.
    """
    query = db.query(models.LogEntry).filter(models.LogEntry.shop_id == current_shop.id)
    
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date.split('T')[0])
            query = query.filter(models.LogEntry.timestamp >= sd)
        except ValueError: pass
    if end_date:
        try:
            ed_str = end_date + "T23:59:59" if len(end_date) == 10 else end_date
            ed = datetime.fromisoformat(ed_str)
            query = query.filter(models.LogEntry.timestamp <= ed)
        except ValueError: pass
    
    logs = query.all()
    
    # --- Sales Metrics ---
    sales_query = db.query(models.SalesRecord).filter(models.SalesRecord.shop_id == current_shop.id)
    if start_date:
        try:
            sd_date = datetime.fromisoformat(start_date.split('T')[0]).date()
            sales_query = sales_query.filter(models.SalesRecord.date >= sd_date)
        except ValueError: pass
    if end_date:
        try:
            ed_date = datetime.fromisoformat(end_date.split('T')[0]).date()
            sales_query = sales_query.filter(models.SalesRecord.date <= ed_date)
        except ValueError: pass
    
    sales_records = sales_query.all()
    
    # Revenue tracking per product
    product_sales_data = {} # {name: {"qty": 0, "rev": 0, "price": 0}}
    total_rev = 0
    
    for sr in sales_records:
        pname = sr.product_name or (sr.inventory_item.name if sr.inventory_item else "Unknown")
        if not is_valid_product_name(pname): continue
        
        price = sr.price if sr.price is not None else (sr.inventory_item.price if sr.inventory_item else 0.0)
        rev = float(sr.quantity * price)
        total_rev += rev
        
        if pname not in product_sales_data:
            product_sales_data[pname] = {"qty": 0, "rev": 0, "price": float(price)}
        
        product_sales_data[pname]["qty"] += sr.quantity
        product_sales_data[pname]["rev"] += rev

    # Top/Low sold with revenue info
    sold_list = []
    for name, data in product_sales_data.items():
        sold_list.append({
            "name": name,
            "quantity_sold": data["qty"],
            "price": data["price"],
            "revenue": data["rev"]
        })

    top_sold = sorted(sold_list, key=lambda x: x["quantity_sold"], reverse=True)[:5]
    low_sold = sorted(sold_list, key=lambda x: x["quantity_sold"])[:5]

    # --- Request Metrics (Demand) ---
    product_requests = {}
    status_counts = {"available": 0, "out_of_stock": 0, "pending": 0, "coming_soon": 0}
    for log in logs:
        pname = log.product_name
        if not is_valid_product_name(pname): continue
        product_requests[pname] = product_requests.get(pname, 0) + 1
        if log.status in status_counts:
            status_counts[log.status] += 1

    top_requested = sorted(product_requests.items(), key=lambda x: x[1], reverse=True)[:5]
    top_requested_json = [{"name": name, "score": score} for name, score in top_requested]
    
    low_requested = sorted(product_requests.items(), key=lambda x: x[1])[:5]
    low_requested_json = [{"name": name, "score": score} for name, score in low_requested]
    
    total_valid_requests = sum(product_requests.values())

    cleaned_data = {
        "total_requests": total_valid_requests,
        "status_counts": status_counts,
        "total_revenue": total_rev,
        "top_sold_products": top_sold,
        "low_sold_products": low_sold,
        "top_requested_products": top_requested_json,
        "low_requested_products": low_requested_json
    }
    
    print("[CLEANED ANALYTICS]", cleaned_data)
    return cleaned_data

@router.get("/inventory/insights")
def get_inventory_insights(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    """
    Returns high-level business intelligence.
    STRICT JSON SCHEMA AS PER USER REQUEST.
    """
    safe_default = {
        "items": [],
        "top_requested": [],
        "top_sold": [],
        "low_demand_requests": [],
        "low_demand_sales": [],
        "total_revenue": 0
    }
    
    try:
        stats = get_analytics(start_date, end_date, current_shop, db)
        
        # --- PER-ITEM INSIGHTS (for Inventory Tab) ---
        items = db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == current_shop.id).all()
        item_stats = []
        
        # Pre-calculate counts from LogEntry to avoid N+1 queries in loop
        # But for limited inventory, a direct query is simpler to implement correctly
        for item in items:
            log_stats = db.query(
                func.count(models.LogEntry.id),
                func.sum(func.cast(models.LogEntry.status == 'out_of_stock', models.Integer))
            ).filter(
                models.LogEntry.shop_id == current_shop.id,
                models.LogEntry.product_id == item.id
            ).first()
            
            total_req = log_stats[0] or 0
            oos_count = log_stats[1] or 0
            oos_rate = (oos_count / total_req) if total_req > 0 else 0
            
            item_stats.append({
                "id": item.id,
                "name": item.name,
                "quantity": item.quantity,
                "price": float(item.price),
                "total_requests": total_req,
                "out_of_stock_rate": round(float(oos_rate), 2)
            })

        response_data = {
            "items": item_stats,
            "top_requested": stats.get("top_requested_products", []),
            "top_sold": stats.get("top_sold_products", []),
            "low_demand_requests": stats.get("low_requested_products", []),
            "low_demand_sales": stats.get("low_sold_products", []),
            "total_revenue": round(stats.get("total_revenue", 0), 2)
        }
        
        print("[ANALYTICS FINAL RESPONSE]", response_data)
        return response_data
        
    except Exception as e:
        print("[ANALYTICS ERROR]", str(e))
        import traceback
        traceback.print_exc()
        return safe_default
