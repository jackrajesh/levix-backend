from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import Optional, List, Any
from datetime import datetime
import io
import csv
import pandas as pd
from fastapi.responses import StreamingResponse

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, UserIdentity, require_permission
from ..services.product_service import sync_stock_status
from ..services.logger import LoggerService

router = APIRouter(prefix="/sales", tags=["sales"])

@router.post("/set")
def set_sales(req: schemas.SalesSetRequest, identity: UserIdentity = Depends(require_permission("sales_create")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    if req.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity must be >= 0")
    
    normalized_date = req.date.strip()
    try:
        sale_date = datetime.strptime(normalized_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    product_id = req.product_id
    product_name = req.product_name.strip() if req.product_name else None
    
    sale_target_name = product_name or "Unknown Product"
    remaining_stock = None
    unit_price_for_log = req.price if req.price is not None else 0
    # 1. Handle Inventory Sale (Explicit Product ID)
    if product_id is not None:
        item = db.query(models.InventoryItem).filter(
            models.InventoryItem.id == product_id,
            models.InventoryItem.shop_id == current_shop.id
        ).first()
        if not item:
            raise HTTPException(status_code=400, detail="Product ID not found in inventory")
        product_name = item.name
        sale_target_name = item.name
        
        existing = db.query(models.SalesRecord).filter(
            models.SalesRecord.shop_id == current_shop.id,
            models.SalesRecord.product_id == product_id,
            models.SalesRecord.date == sale_date
        ).first()
        
        added_qty = req.quantity
        # Determine the price to record
        price_to_record = req.price if req.price is not None else item.price
        unit_price_for_log = float(price_to_record) if price_to_record is not None else 0

        if added_qty > item.quantity:
             raise HTTPException(status_code=400, detail=f"Insufficient stock. Only {item.quantity} available")

        if existing:
            existing.quantity += req.quantity
            existing.product_name = product_name
            existing.price = price_to_record
        else:
            new_sale = models.SalesRecord(
                shop_id=current_shop.id,
                product_id=product_id,
                product_name=product_name,
                date=sale_date,
                quantity=req.quantity,
                price=price_to_record,
                performed_by=identity.name,
                user_type=identity.user_type
            )
            db.add(new_sale)
            
        item.quantity = max(0, item.quantity - added_qty)
        remaining_stock = item.quantity
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
            # Determine logic for price
            price_to_record = req.price if req.price is not None else item.price
            unit_price_for_log = float(price_to_record) if price_to_record is not None else 0

            if added_qty > item.quantity:
                 raise HTTPException(status_code=400, detail=f"Insufficient stock. Only {item.quantity} available")

            if existing:
                existing.quantity += req.quantity
                existing.product_name = canonical_name
                existing.price = price_to_record
            else:
                new_sale = models.SalesRecord(
                    shop_id=current_shop.id,
                    product_id=item.id,
                    product_name=canonical_name,
                    date=sale_date,
                    quantity=req.quantity,
                    price=price_to_record,
                    performed_by=identity.name,
                    user_type=identity.user_type
                )
                db.add(new_sale)
            
            # Deduct stock
            item.quantity = max(0, item.quantity - added_qty)
            remaining_stock = item.quantity
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
                existing.quantity += req.quantity
                if req.price is not None: existing.price = req.price
                unit_price_for_log = float(existing.price) if existing.price is not None else 0
            else:
                new_sale = models.SalesRecord(
                    shop_id=current_shop.id,
                    product_id=None,
                    product_name=product_name.lower(),
                    date=sale_date,
                    quantity=req.quantity,
                    price=req.price if req.price is not None else 0,
                    performed_by=identity.name,
                    user_type=identity.user_type
                )
                db.add(new_sale)
                unit_price_for_log = float(new_sale.price) if new_sale.price is not None else 0
    else:
        raise HTTPException(status_code=400, detail="Either product_id or product_name is required")
    
    db.commit()
    total_amount = float(unit_price_for_log) * float(req.quantity)
    LoggerService.log(
        db, current_shop.id, identity, "Sales", 
        f"Recorded sale of {req.quantity}x {sale_target_name}",
        target=sale_target_name,
        new_value=str(req.quantity),
        action_type="sale_recorded",
        entity_type="sale",
        entity_name=sale_target_name,
        severity="success",
        new_values={
            "product_name": sale_target_name,
            "qty_sold": req.quantity,
            "unit_price": round(float(unit_price_for_log), 2),
            "total_amount": round(total_amount, 2),
            "sold_by": identity.name,
            "remaining_stock": remaining_stock,
            "payment_method": "manual",
            "order_id": None,
        },
        metadata={
            "event_kind": "sale",
            "payment_method": "manual",
        }
    )
    return {"status": "success", "message": "Sale recorded"}

@router.get("")
def get_sales(start_date: Optional[str] = None, end_date: Optional[str] = None, identity: UserIdentity = Depends(require_permission("sales_create")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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
        price = r.price if r.price is not None else (r.inventory_item.price if r.inventory_item else 0.0)
        result.append({
            "id": r.id,
            "product_id": r.product_id,
            "product_name": product_name,
            "date": r.date.isoformat(),
            "quantity": r.quantity,
            "price": float(price),
            "revenue": float(r.quantity * price)
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
def export_sales(start_date: Optional[str] = None, end_date: Optional[str] = None, identity: UserIdentity = Depends(require_permission("analytics_export")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    sales_resp = get_sales(start_date, end_date, identity, db)
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

@router.get("/export-excel")
def export_sales_excel(start_date: Optional[str] = None, end_date: Optional[str] = None, identity: UserIdentity = Depends(require_permission("analytics_export")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    """
    Professional Excel export for Sales History.
    """
    sales_resp = get_sales(start_date, end_date, identity, db)
    records = sales_resp["records"]
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if records:
            df = pd.DataFrame(records)
            # Remove internal IDs for professional look
            if 'id' in df.columns: df.drop(columns=['id'], inplace=True)
            if 'product_id' in df.columns: df.drop(columns=['product_id'], inplace=True)
            
            df.columns = ["Product", "Date", "Quantity", "Unit Price", "Total Revenue"]
            df.to_excel(writer, sheet_name='Sales History', index=False)
        else:
            pd.DataFrame([{"Message": "No sales records found"}]).to_excel(writer, index=False)
            
    output.seek(0)
    filename = f"Levix_Sales_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.delete("/{sale_id}")
def delete_sale(sale_id: int, identity: UserIdentity = Depends(require_permission("sales_delete")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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
    LoggerService.log(
        db, current_shop.id, identity, "Sales", 
        f"Deleted sale record for {sale.product_name}",
        target=f"Sale ID: {sale.id}",
        severity="Warning"
    )
    return {"status": "success", "message": "Sale removed"}
