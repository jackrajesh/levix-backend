from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import List, Optional

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop
from ..services.product_service import (
    ALLOWED_STATUSES, 
    LOW_STOCK_THRESHOLD, 
    sync_stock_status, 
    handle_low_stock_log
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def get_inventory(current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    items = db.query(models.InventoryItem).options(
        joinedload(models.InventoryItem.aliases)
    ).filter(models.InventoryItem.shop_id == current_shop.id).all()
    
    result = []
    for item in items:
        result.append({
            "id": item.id,
            "name": item.name,
            "quantity": item.quantity,
            "price": float(item.price) if item.price is not None else 0.0,
            "status": item.status,
            "stock_warning_active": item.stock_warning_active,
            "aliases": [a.alias for a in item.aliases],
            "created_at": item.created_at.isoformat() if item.created_at else None
        })
    return result

@router.post("/add")
def add_to_inventory(item: schemas.InventoryItemCreate, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    existing = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == current_shop.id,
        sa_func.lower(models.InventoryItem.name) == item.name.lower()
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product already exists")
    
    valid_aliases = [a.strip() for a in item.aliases if a.strip()]
    if not valid_aliases:
        raise HTTPException(status_code=400, detail="At least one alias required")
    
    if item.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    
    qty = max(0, item.quantity)
    status = "available" if qty > 0 else "out_of_stock"
    
    new_item = models.InventoryItem(
        shop_id=current_shop.id,
        name=item.name,
        quantity=qty,
        price=item.price,
        status=status,
    )
    
    if qty <= LOW_STOCK_THRESHOLD:
        new_item.stock_warning_active = True
    
    db.add(new_item)
    db.flush()
    
    for alias_str in valid_aliases:
        db.add(models.InventoryAlias(
            inventory_id=new_item.id,
            alias=alias_str.lower()
        ))
    
    db.commit()
    db.refresh(new_item)
    
    return {
        "status": "success",
        "product": {
            "id": new_item.id,
            "name": new_item.name,
            "quantity": new_item.quantity,
            "price": float(new_item.price) if new_item.price is not None else 0.0,
            "aliases": [a.alias for a in new_item.aliases],
            "status": new_item.status
        }
    }

@router.post("/{product_id}/quantity")
def update_quantity(product_id: int, update: schemas.QuantityUpdate, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
        
    item.quantity = max(0, item.quantity + update.amount)
    sync_stock_status(item, db)
    db.commit()
    return {"status": "success", "quantity": item.quantity, "new_status": item.status}

@router.post("/update-status/{product_id}")
def update_status(product_id: int, update: schemas.StatusUpdate, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    if update.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {ALLOWED_STATUSES}")
    
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    
    item.status = update.status
    db.commit()
    return {"status": "success", "message": f"Updated {item.name} to {update.status}"}

@router.post("/edit/{product_id}")
def edit_product(product_id: int, item: schemas.EditItem, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    if not item.name.strip():
        raise HTTPException(status_code=400, detail="Product name cannot be empty")
    
    target = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    
    duplicate = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == current_shop.id,
        sa_func.lower(models.InventoryItem.name) == item.name.lower().strip(),
        models.InventoryItem.id != product_id
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Another product with this name already exists")
    
    valid_aliases = [a.strip() for a in item.aliases if a.strip()]
    if not valid_aliases:
        raise HTTPException(status_code=400, detail="At least one alias required")

    if item.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")

    target.name = item.name.strip()
    target.quantity = max(0, item.quantity)
    target.price = item.price
    sync_stock_status(target, db)
    handle_low_stock_log(target, db)

    db.query(models.InventoryAlias).filter(
        models.InventoryAlias.inventory_id == product_id
    ).delete()
    
    for alias_str in valid_aliases:
        db.add(models.InventoryAlias(
            inventory_id=product_id,
            alias=alias_str.lower()
        ))
    
    db.commit()
    db.refresh(target)
    
    return {
        "status": "success",
        "product": {
            "id": target.id,
            "name": target.name,
            "quantity": target.quantity,
            "price": float(target.price) if target.price is not None else 0.0,
            "stock_warning_active": target.stock_warning_active,
            "aliases": [a.alias for a in target.aliases],
            "status": target.status
        }
    }

@router.delete("/{product_id}")
def delete_product(product_id: int, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db.delete(item)
    db.commit()
    return {"status": "success", "message": "Product removed"}

@router.post("/bulk-delete")
def bulk_delete_inventory(req: schemas.BulkDeleteRequest, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    
    items = db.query(models.InventoryItem).filter(
        models.InventoryItem.id.in_(req.ids),
        models.InventoryItem.shop_id == current_shop.id
    ).all()
    
    if not items:
        raise HTTPException(status_code=404, detail="No matching products found")
    
    item_ids = [i.id for i in items]
    
    # Safely nullify sales record references so sales/analytics data is preserved
    db.query(models.SalesRecord).filter(
        models.SalesRecord.product_id.in_(item_ids)
    ).update({models.SalesRecord.product_id: None}, synchronize_session='fetch')
    
    # Nullify log entry product_id references
    db.query(models.LogEntry).filter(
        models.LogEntry.product_id.in_(item_ids)
    ).update({models.LogEntry.product_id: None}, synchronize_session='fetch')
    
    # Delete aliases
    db.query(models.InventoryAlias).filter(
        models.InventoryAlias.inventory_id.in_(item_ids)
    ).delete(synchronize_session='fetch')
    
    # Delete pending requests linked to these items
    db.query(models.PendingRequest).filter(
        models.PendingRequest.product_id.in_(item_ids)
    ).delete(synchronize_session='fetch')
    
    # Finally delete the inventory items
    for item in items:
        db.delete(item)
    
    db.commit()
    return {"status": "success", "deleted_count": len(items)}
