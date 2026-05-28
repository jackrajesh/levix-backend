from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import List, Optional
import os

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, require_permission, UserIdentity, require_active_subscription
from ..services.product_service import (
    LOW_STOCK_THRESHOLD
)
from ..services.logger import LoggerService
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Helper to normalize category name
def get_or_create_category(db: Session, shop_id: str, name: str) -> Optional[str]:
    if not name: return None
    name = name.strip()
    return name if name else None

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/categories", response_model=List[str])
def get_categories(identity: UserIdentity = Depends(require_permission("inventory_view")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    # Get unique category names from inventory items
    cats = db.query(models.InventoryItem.category).filter(
        models.InventoryItem.shop_id == current_shop.id,
        models.InventoryItem.category.isnot(None)
    ).distinct().all()
    return [c[0] for c in cats if c[0]]

@router.get("")
def get_inventory(identity: UserIdentity = Depends(require_permission("inventory_view")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    items = db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == current_shop.id).all()
    
    result = []
    for item in items:
        result.append({
            "id": item.id,
            "name": item.name,
            "quantity": item.quantity,
            "price": float(item.price) if item.price is not None else 0.0,
            "barcode": item.barcode,
            "category": item.category or "Uncategorized",
            "created_at": item.created_at.isoformat() if item.created_at else None
        })
    return result

@router.get("/barcode/{barcode}")
def get_by_barcode(barcode: str, identity: UserIdentity = Depends(require_permission("inventory_view")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    logger.info(f"[SCAN RECEIVED] Barcode: {barcode} | Shop: {identity.shop.id}")

    # Search in current shop's inventory ONLY
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == identity.shop.id,
        models.InventoryItem.barcode == barcode
    ).first()
    
    if item:
        logger.info(f"[PRODUCT FOUND] {item.name}")
        return {
            "found": True,
            "product": {
                "id": item.id,
                "name": item.name,
                "price": float(item.price) if item.price is not None else 0.0,
                "quantity": item.quantity,
                "barcode": item.barcode,
                "category": item.category or "Uncategorized"
            }
        }
    
    logger.info(f"[PRODUCT NOT FOUND] Barcode: {barcode}")
    return {
        "found": False,
        "barcode": barcode
    }


@router.post("/bulk-add")
def bulk_add_to_inventory(payload: dict, identity: UserIdentity = Depends(require_permission("inventory_add")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    items = payload.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="No items provided")
    
    added_count = 0
    for item_data in items:
        name = item_data.get("name")
        barcode = item_data.get("barcode")
        qty = int(item_data.get("quantity", 1))
        price = float(item_data.get("price", 0))
        
        if not name:
            continue
            
        # Check if already exists in shop
        existing = db.query(models.InventoryItem).filter(
            models.InventoryItem.shop_id == current_shop.id,
            (sa_func.lower(models.InventoryItem.name) == name.lower()) | 
            (models.InventoryItem.barcode == barcode if barcode else False)
        ).first()
        
        cat_name = get_or_create_category(db, current_shop.id, item_data.get("category"))
        
        if existing:
            # Update quantity if exists (Auto-increment)
            existing.quantity += qty
            if price > 0: existing.price = price
            if cat_name: existing.category = cat_name
        else:
            # Create new
            new_item = models.InventoryItem(
                shop_id=current_shop.id,
                name=name,
                quantity=qty,
                price=price,
                barcode=barcode,
                category=cat_name
            )
            db.add(new_item)
            db.flush()
        
        added_count += 1
    
    db.commit()
    
    LoggerService.log(
        db, current_shop.id, identity, "Inventory", 
        f"Bulk added/updated {added_count} products via scanner",
        action_type="product_added",
        severity="success"
    )
    
    return {"status": "success", "added_count": added_count}


@router.post("/add")
def add_to_inventory(item: schemas.InventoryItemCreate, identity: UserIdentity = Depends(require_permission("inventory_add")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    existing = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == current_shop.id,
        sa_func.lower(models.InventoryItem.name) == item.name.lower()
    ).first()
    if item.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    
    qty = max(0, item.quantity)
    status = "available" if qty > 0 else "out_of_stock"
    
    cat_name = get_or_create_category(db, current_shop.id, item.category)
    
    new_item = models.InventoryItem(
        shop_id=current_shop.id,
        name=item.name,
        quantity=qty,
        price=item.price,
        barcode=item.barcode or None,
        category=cat_name
    )
    
    db.add(new_item)
    db.flush()
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
            "opening_stock": new_item.quantity,
            "price": float(new_item.price) if new_item.price is not None else 0.0,
            "added_by": identity.name,
        }
    )
    
    return {
        "status": "success",
        "product": {
            "id": new_item.id,
            "name": new_item.name,
            "quantity": new_item.quantity,
            "price": float(new_item.price) if new_item.price is not None else 0.0,
            "barcode": new_item.barcode,
            "category": new_item.category or "Uncategorized"
        }
    }

@router.post("/{product_id}/quantity")
def update_quantity(product_id: str, update: schemas.QuantityUpdate, identity: UserIdentity = Depends(require_permission("stock_adjust")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.id == product_id,
        models.InventoryItem.shop_id == current_shop.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    
    old_qty = item.quantity  # Capture BEFORE mutation
    item.quantity = max(0, item.quantity + update.amount)
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Quantity Changes", 
        f"Adjusted stock for {item.name}",
        target=item.name,
        old_value=str(old_qty),
        new_value=str(item.quantity)
    )
    return {"status": "success", "quantity": item.quantity}

@router.post("/{product_id}/price")
def update_price(product_id: str, payload: dict, identity: UserIdentity = Depends(require_permission("price_change")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
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
def update_status(product_id: str, update: schemas.StatusUpdate, identity: UserIdentity = Depends(require_permission("inventory_edit")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    # Legacy endpoint kept for API compatibility but now a no-op
    return {"status": "success", "message": "Product status updated"}

@router.post("/edit/{product_id}")
def edit_product(product_id: str, item: schemas.EditItem, identity: UserIdentity = Depends(require_permission("inventory_edit")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
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
    


    if item.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")

    before_snapshot = {
        "name": target.name,
        "price": float(target.price) if target.price is not None else 0,
        "stock": target.quantity,
        "product_id": target.id,
    }

    cat_name = get_or_create_category(db, current_shop.id, item.category)
    target.name = item.name.strip()
    target.quantity = max(0, item.quantity)
    target.price = item.price
    target.barcode = item.barcode if item.barcode is not None else target.barcode
    target.category = cat_name or target.category

    db.commit()
    db.refresh(target)
    after_snapshot = {
        "name": target.name,
        "price": float(target.price) if target.price is not None else 0,
        "stock": target.quantity,
        "product_id": target.id,
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
        severity="info"
    )
    
    return {
        "status": "success",
        "product": {
            "id": target.id,
            "name": target.name,
            "quantity": target.quantity,
            "price": float(target.price) if target.price is not None else 0.0,
            "barcode": target.barcode,
            "category": target.category or "Uncategorized"
        }
    }

@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    reason: str = Query("Manual delete", description="Reason for deleting this product"),
    identity: UserIdentity = Depends(require_permission("inventory_delete")),
    _sub: UserIdentity = Depends(require_active_subscription),
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
        "price": float(item.price) if item.price is not None else 0.0,
        "stock_before_delete": item.quantity,
        "deleted_by": identity.name,
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
def bulk_delete_inventory(req: schemas.BulkDeleteRequest, identity: UserIdentity = Depends(require_permission("inventory_delete")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
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
    
    # Delete pending requests linked to these items
    db.query(models.PendingRequest).filter(
        models.PendingRequest.product_id.in_(item_ids)
    ).delete(synchronize_session='fetch')
    
    # Finally delete the inventory items
    for item in items:
        db.delete(item)
    
    db.commit()
    return {"status": "success", "deleted_count": len(items)}
