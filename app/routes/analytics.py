from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from .. import models
from ..database import get_db
from .auth import get_current_shop

router = APIRouter(tags=["analytics"])

@router.get("/analytics")
def get_analytics(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    query = db.query(models.LogEntry).filter(models.LogEntry.shop_id == current_shop.id)
    
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date)
            query = query.filter(models.LogEntry.timestamp >= sd)
        except ValueError: pass
    if end_date:
        try:
            ed_str = end_date + "T23:59:59" if len(end_date) == 10 else end_date
            ed = datetime.fromisoformat(ed_str)
            query = query.filter(models.LogEntry.timestamp <= ed)
        except ValueError: pass
    
    logs = query.all()
    
    stats = {
        "total_requests": len(logs),
        "status_counts": {"available": 0, "out_of_stock": 0, "pending": 0, "coming_soon": 0},
        "product_request_counts": {},
        "top_sold_products": [],
        "low_sold_products": [],
        "top_requested_products": [],
        "low_requested_products": []
    }
    
    # --- Sales Metrics ---
    sales_query = db.query(models.SalesRecord).filter(models.SalesRecord.shop_id == current_shop.id)
    if start_date:
        try:
            sd_date = datetime.fromisoformat(start_date).date()
            sales_query = sales_query.filter(models.SalesRecord.date >= sd_date)
        except ValueError: pass
    if end_date:
        try:
            ed_date = datetime.fromisoformat(end_date).date()
            sales_query = sales_query.filter(models.SalesRecord.date <= ed_date)
        except ValueError: pass
    
    sales_records = sales_query.all()
    product_sales = {}
    for sr in sales_records:
        pname = sr.product_name or (sr.inventory_item.name if sr.inventory_item else "Unknown")
        product_sales[pname] = product_sales.get(pname, 0) + sr.quantity

    top_sold = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    stats["top_sold_products"] = [{"name": name, "score": score} for name, score in top_sold]
    
    low_sold = sorted(product_sales.items(), key=lambda x: x[1])[:5]
    stats["low_sold_products"] = [{"name": name, "score": score} for name, score in low_sold]

    # --- Request Metrics (Demand) ---
    product_requests = {}
    for log in logs:
        product = log.product_name
        product_requests[product] = product_requests.get(product, 0) + 1
        if log.status in stats["status_counts"]:
            stats["status_counts"][log.status] += 1

    top_requested = sorted(product_requests.items(), key=lambda x: x[1], reverse=True)[:5]
    stats["top_requested_products"] = [{"name": name, "score": score} for name, score in top_requested]
    
    low_requested = sorted(product_requests.items(), key=lambda x: x[1])[:5]
    stats["low_requested_products"] = [{"name": name, "score": score} for name, score in low_requested]
    
    stats["product_request_counts"] = product_requests
    return stats

@router.get("/inventory/insights")
def get_inventory_insights(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    items = db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == current_shop.id).all()
    log_query = db.query(models.LogEntry).filter(models.LogEntry.shop_id == current_shop.id)
    
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date.split('T')[0])
            log_query = log_query.filter(models.LogEntry.timestamp >= sd)
        except ValueError: pass
    if end_date:
        try:
            ed_str = end_date + "T23:59:59" if len(end_date) == 10 else end_date
            ed = datetime.fromisoformat(ed_str)
            log_query = log_query.filter(models.LogEntry.timestamp <= ed)
        except ValueError: pass
    
    all_logs = log_query.all()
    
    days = 1
    if start_date and end_date:
        try:
            d1 = datetime.fromisoformat(start_date.split('T')[0])
            d2 = datetime.fromisoformat(end_date.split('T')[0])
            days = max(1, (d2 - d1).days + 1)
        except Exception: days = 1
    elif len(all_logs) > 0:
        try:
            timestamps = [l.timestamp for l in all_logs if l.timestamp]
            if timestamps:
                d_first = min(timestamps).replace(tzinfo=None)
                d_last = max(timestamps).replace(tzinfo=None)
                days = max(1, (d_last - d_first).days + 1)
        except Exception: days = 1

    insights = []
    for item in items:
        prod_logs = [l for l in all_logs if l.product_id == item.id or l.product_name.lower() == item.name.lower()]
        last_asked = None
        if prod_logs:
            timestamps = [l.timestamp for l in prod_logs if l.timestamp]
            if timestamps:
                last_asked = max(timestamps).isoformat()
            
        total_asks = len(prod_logs)
        oos_count = len([l for l in prod_logs if l.status == "out_of_stock"])
        
        insights.append({
            "id": item.id,
            "name": item.name,
            "total_requests": total_asks,
            "out_of_stock_count": oos_count,
            "last_requested_timestamp": last_asked,
            "demand_rate": round(total_asks / days, 2),
            "oos_rate": round(oos_count / total_asks, 2) if total_asks > 0 else 0
        })
    return insights
