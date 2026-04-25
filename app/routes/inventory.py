from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import List, Optional

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, require_permission, UserIdentity
from ..services.product_service import (
    ALLOWED_STATUSES, 
    LOW_STOCK_THRESHOLD, 
    sync_stock_status, 
    handle_low_stock_log
)
from ..services.logger import LoggerService

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def get_inventory(identity: UserIdentity = Depends(require_permission("inventory_view")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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
            "product_details": item.product_details,
            "category": item.category,
            "created_at": item.created_at.isoformat() if item.created_at else None
        })
    return result

@router.post("/add")
def add_to_inventory(item: schemas.InventoryItemCreate, identity: UserIdentity = Depends(require_permission("inventory_add")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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
        product_details=item.product_details or None,
        category=item.category or None,
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
    LoggerService.log(
        db, current_shop.id, identity, "Inventory", 
        f"Added new product: {new_item.name}",
        target=new_item.name,
        new_value=str(new_item.quantity),
        action_type="product_added",
        entity_type="product",
        entity_name=new_item.name,
        severity="success",
        new_values={
            "product_name": new_item.name,
            "product_id": new_item.id,
            "sku": new_item.id,
            "category": new_item.status,
            "opening_stock": new_item.quantity,
            "price": float(new_item.price) if new_item.price is not None else 0.0,
            "added_by": identity.name,
        },
        metadata={
            "event_kind": "product_add",
        }
    )
    
    return {
        "status": "success",
        "product": {
            "id": new_item.id,
            "name": new_item.name,
            "quantity": new_item.quantity,
            "price": float(new_item.price) if new_item.price is not None else 0.0,
            "aliases": [a.alias for a in new_item.aliases],
            "status": new_item.status,
            "product_details": new_item.product_details,
            "category": new_item.category,
        }
    }

@router.post("/{product_id}/quantity")
def update_quantity(product_id: int, update: schemas.QuantityUpdate, identity: UserIdentity = Depends(require_permission("stock_adjust")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
        
    item.quantity = max(0, item.quantity + update.amount)
    old_qty = item.quantity - update.amount
    sync_stock_status(item, db)
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Quantity Changes", 
        f"Adjusted stock for {item.name}",
        target=item.name,
        old_value=str(old_qty),
        new_value=str(item.quantity)
    )
    return {"status": "success", "quantity": item.quantity, "new_status": item.status}

@router.post("/{product_id}/price")
def update_price(product_id: int, payload: dict, identity: UserIdentity = Depends(require_permission("price_change")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")

    if "price" not in payload:
        raise HTTPException(status_code=400, detail="price is required")
    try:
        new_price = float(payload.get("price"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="price must be numeric")
    if new_price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")

    old_price = float(item.price) if item.price is not None else 0.0
    item.price = new_price
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Inventory",
        f"Updated price for {item.name}",
        target=item.name,
        old_value=str(old_price),
        new_value=str(new_price),
        action_type="inventory_edit",
        entity_type="product",
        entity_name=item.name,
        severity="info",
    )
    return {"status": "success", "price": new_price}

@router.post("/update-status/{product_id}")
def update_status(product_id: int, update: schemas.StatusUpdate, identity: UserIdentity = Depends(require_permission("inventory_edit")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    if update.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {ALLOWED_STATUSES}")
    
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    
    old_status = item.status
    item.status = update.status
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Inventory", 
        f"Updated status for {item.name}",
        target=item.name,
        old_value=old_status,
        new_value=item.status
    )
    return {"status": "success", "message": f"Updated {item.name} to {update.status}"}

@router.post("/edit/{product_id}")
def edit_product(product_id: int, item: schemas.EditItem, identity: UserIdentity = Depends(require_permission("inventory_edit")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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

    before_snapshot = {
        "name": target.name,
        "price": float(target.price) if target.price is not None else 0,
        "stock": target.quantity,
        "category": target.status,
        "product_id": target.id,
        "sku": target.id,
    }

    target.name = item.name.strip()
    target.quantity = max(0, item.quantity)
    previous_price = float(target.price) if target.price is not None else 0.0
    requested_price = float(item.price) if item.price is not None else 0.0
    if requested_price != previous_price and not identity.has_permission("price_change"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    target.price = item.price
    target.product_details = item.product_details if item.product_details is not None else target.product_details
    target.category = item.category if item.category is not None else target.category
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
    after_snapshot = {
        "name": target.name,
        "price": float(target.price) if target.price is not None else 0,
        "stock": target.quantity,
        "category": target.status,
        "product_id": target.id,
        "sku": target.id,
    }
    LoggerService.log(
        db, current_shop.id, identity, "Inventory", 
        f"Manually edited product details: {target.name}",
        target=target.name,
        action_type="inventory_edit",
        entity_type="product",
        entity_name=target.name,
        old_values=before_snapshot,
        new_values=after_snapshot,
        severity="info",
        metadata={
            "event_kind": "product_edit",
        }
    )
    
    return {
        "status": "success",
        "product": {
            "id": target.id,
            "name": target.name,
            "quantity": target.quantity,
            "price": float(target.price) if target.price is not None else 0.0,
            "stock_warning_active": target.stock_warning_active,
            "aliases": [a.alias for a in target.aliases],
            "status": target.status,
            "product_details": target.product_details,
            "category": target.category,
        }
    }

@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    reason: str = Query("Manual delete", description="Reason for deleting this product"),
    identity: UserIdentity = Depends(require_permission("inventory_delete")),
    db: Session = Depends(get_db)
):
    current_shop = identity.shop
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    
    delete_snapshot = {
        "product_name": item.name,
        "product_id": item.id,
        "sku": item.id,
        "category": item.status,
        "price": float(item.price) if item.price is not None else 0.0,
        "stock_before_delete": item.quantity,
        "cost_price": None,
        "deleted_by": identity.name,
        "deleted_at": None,
        "delete_reason": reason.strip() or "Manual delete",
    }

    db.delete(item)
    db.commit()

    from datetime import datetime, timezone
    delete_snapshot["deleted_at"] = datetime.now(timezone.utc).isoformat()
    LoggerService.log(
        db, current_shop.id, identity, "Products Deleted", 
        f"Deleted product: {item.name}",
        target=item.name,
        action_type="product_deleted",
        entity_type="product",
        entity_name=item.name,
        severity="critical",
        old_values=delete_snapshot,
        metadata={
            "event_kind": "product_delete",
            "reason": delete_snapshot["delete_reason"],
        }
    )
    return {"status": "success", "message": "Product removed"}

@router.post("/bulk-delete")
def bulk_delete_inventory(req: schemas.BulkDeleteRequest, identity: UserIdentity = Depends(require_permission("inventory_delete")), db: Session = Depends(get_db)):
    current_shop = identity.shop
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
