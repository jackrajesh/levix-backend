from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import Optional, List
from datetime import datetime
import io
import csv

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop
from ..services.product_service import sync_stock_status

router = APIRouter(prefix="/sales", tags=["sales"])

@router.post("/set")
def set_sales(req: schemas.SalesSetRequest, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    if req.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity must be >= 0")
    
    normalized_date = req.date.strip()
    try:
        sale_date = datetime.strptime(normalized_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    product_id = req.product_id
    product_name = req.product_name.strip() if req.product_name else None
    
    # 1. Handle Inventory Sale (Explicit Product ID)
    if product_id is not None:
        item = db.query(models.InventoryItem).filter(
            models.InventoryItem.id == product_id,
            models.InventoryItem.shop_id == current_shop.id
        ).first()
        if not item:
            raise HTTPException(status_code=400, detail="Product ID not found in inventory")
        product_name = item.name
        
        existing = db.query(models.SalesRecord).filter(
            models.SalesRecord.shop_id == current_shop.id,
            models.SalesRecord.product_id == product_id,
            models.SalesRecord.date == sale_date
        ).first()
        
        added_qty = req.quantity
        if existing:
            added_qty = req.quantity - existing.quantity
            existing.quantity = req.quantity
            existing.product_name = product_name
        else:
            new_sale = models.SalesRecord(
                shop_id=current_shop.id,
                product_id=product_id,
                product_name=product_name,
                date=sale_date,
                quantity=req.quantity
            )
            db.add(new_sale)
            
        difference = added_qty
        item.quantity = max(0, item.quantity - difference)
        sync_stock_status(item, db)
        
    # 2. Handle Manual Sale (Name Only) - First check for inventory match
    elif product_name:
        # Case-insensitive match by name
        item = db.query(models.InventoryItem).filter(
            models.InventoryItem.shop_id == current_shop.id,
            sa_func.lower(models.InventoryItem.name) == product_name.lower()
        ).first()
        
        # Also check aliases
        if not item:
            alias_match = db.query(models.InventoryAlias).filter(
                sa_func.lower(models.InventoryAlias.alias) == product_name.lower()
            ).first()
            if alias_match:
                item = db.query(models.InventoryItem).filter(
                    models.InventoryItem.id == alias_match.inventory_id, # Verified field name
                    models.InventoryItem.shop_id == current_shop.id
                ).first()
        
        if item:
            # Matched! Redirect to inventory sale logic
            canonical_name = item.name
            existing = db.query(models.SalesRecord).filter(
                models.SalesRecord.shop_id == current_shop.id,
                models.SalesRecord.product_id == item.id,
                models.SalesRecord.date == sale_date
            ).first()
            
            manual_existing = db.query(models.SalesRecord).filter(
                models.SalesRecord.shop_id == current_shop.id,
                models.SalesRecord.product_id == None,
                sa_func.lower(models.SalesRecord.product_name) == product_name.lower(),
                models.SalesRecord.date == sale_date
            ).first()
            
            if manual_existing:
                if existing:
                    existing.quantity += manual_existing.quantity
                    db.delete(manual_existing)
                else:
                    manual_existing.product_id = item.id
                    manual_existing.product_name = canonical_name
                    existing = manual_existing
            
            added_qty = req.quantity
            if existing:
                added_qty = req.quantity - existing.quantity
                existing.quantity = req.quantity
                existing.product_name = canonical_name
            else:
                new_sale = models.SalesRecord(
                    shop_id=current_shop.id,
                    product_id=item.id,
                    product_name=canonical_name,
                    date=sale_date,
                    quantity=req.quantity
                )
                db.add(new_sale)
            
            # Deduct stock
            item.quantity = max(0, item.quantity - added_qty)
            sync_stock_status(item, db)
        else:
            # Standalone manual sale
            existing = db.query(models.SalesRecord).filter(
                models.SalesRecord.shop_id == current_shop.id,
                models.SalesRecord.product_id == None,
                sa_func.lower(models.SalesRecord.product_name) == product_name.lower(),
                models.SalesRecord.date == sale_date
            ).first()
            
            if existing:
                existing.quantity = req.quantity
            else:
                new_sale = models.SalesRecord(
                    shop_id=current_shop.id,
                    product_id=None,
                    product_name=product_name.lower(),
                    date=sale_date,
                    quantity=req.quantity
                )
                db.add(new_sale)
    else:
        raise HTTPException(status_code=400, detail="Either product_id or product_name is required")
    
    db.commit()
    return {"status": "success", "message": "Sale recorded"}

@router.get("")
def get_sales(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    query = db.query(models.SalesRecord).options(
        joinedload(models.SalesRecord.inventory_item)
    ).filter(models.SalesRecord.shop_id == current_shop.id)
    
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            query = query.filter(models.SalesRecord.date >= sd)
        except ValueError: pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            query = query.filter(models.SalesRecord.date <= ed)
        except ValueError: pass
    
    records = query.all()
    result = []
    for r in records:
        product_name = r.product_name or (r.inventory_item.name if r.inventory_item else "Unknown")
        result.append({
            "id": r.id,
            "product_id": r.product_id,
            "product_name": product_name,
            "date": r.date.isoformat(),
            "quantity": r.quantity
        })
    
    result.sort(key=lambda x: x["product_name"])
    result.sort(key=lambda x: x["date"], reverse=True)
    
    aggregated = {}
    for record in result:
        pname = record["product_name"]
        aggregated[pname] = aggregated.get(pname, 0) + record["quantity"]
    
    totals = [{"product_name": name, "total_quantity": qty} for name, qty in aggregated.items()]
    
    return {"records": result, "totals": totals}

@router.get("/export")
def export_sales(start_date: Optional[str] = None, end_date: Optional[str] = None, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    sales_resp = get_sales(start_date, end_date, current_shop, db)
    records = sales_resp["records"]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Product", "Date", "Quantity"])
    
    for r in records:
        writer.writerow([r["product_name"], r["date"], r["quantity"]])
    
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sales_export_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@router.delete("/{sale_id}")
def delete_sale(sale_id: int, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    sale = db.query(models.SalesRecord).filter(
        models.SalesRecord.id == sale_id,
        models.SalesRecord.shop_id == current_shop.id
    ).first()
    
    if not sale:
        raise HTTPException(status_code=404, detail="Sale record not found")
        
    if sale.product_id:
        item = db.query(models.InventoryItem).filter(models.InventoryItem.id == sale.product_id).first()
        if item:
            item.quantity += sale.quantity
            sync_stock_status(item, db)
            
    db.delete(sale)
    db.commit()
    return {"status": "success", "message": "Sale removed"}
