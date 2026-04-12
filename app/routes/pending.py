from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop
from ..services.sse import broadcast_event
from ..services.product_service import add_log_db

router = APIRouter(tags=["pending"])

@router.post("/pending/bulk-delete")
def bulk_delete_pending(req: schemas.BulkDeleteRequest, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    
    deleted = db.query(models.PendingRequest).filter(
        models.PendingRequest.id.in_(req.ids),
        models.PendingRequest.shop_id == current_shop.id
    ).delete(synchronize_session='fetch')
    
    db.commit()
    broadcast_event("pending_updated")
    return {"status": "success", "deleted_count": deleted}

@router.get("/pending")
def get_pending(current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    pending = db.query(models.PendingRequest).filter(
        models.PendingRequest.shop_id == current_shop.id
    ).all()
    return [{
        "id": p.id, 
        "product": p.product_name, 
        "customer_message": p.customer_message, 
        "request_type": p.request_type, 
        "created_at": p.created_at.isoformat() if p.created_at else None
    } for p in pending]

@router.delete("/pending/{request_id}")
def delete_pending(request_id: int, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    found_req = db.query(models.PendingRequest).filter(
        models.PendingRequest.id == request_id,
        models.PendingRequest.shop_id == current_shop.id
    ).first()
    
    if not found_req:
        raise HTTPException(status_code=404, detail="Request not found")
    
    db.delete(found_req)
    db.commit()
    broadcast_event("pending_updated")
    return {"status": "success", "message": "Pending request removed"}

@router.post("/yes/{request_id}")
def resolve_yes(request_id: int, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    found_req = db.query(models.PendingRequest).filter(
        models.PendingRequest.id == request_id,
        models.PendingRequest.shop_id == current_shop.id
    ).first()
    
    if not found_req:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if found_req.request_type == "oos_warning":
        if found_req.product_id:
            item = db.query(models.InventoryItem).filter(models.InventoryItem.id == found_req.product_id).first()
            if item:
                item.status = "out_of_stock"
                item.stock_warning_active = False
        db.delete(found_req)
        db.commit()
        broadcast_event("pending_updated")
        return {"status": "success", "message": "Product marked as Out Of Stock"}
    
    existing_item = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == current_shop.id,
        sa_func.lower(models.InventoryItem.name) == found_req.product_name.lower()
    ).first()
    
    if existing_item:
        existing_item.quantity = max(1, existing_item.quantity)
        existing_item.status = "available"
        existing_item.stock_warning_active = False
    else:
        new_item = models.InventoryItem(
            shop_id=current_shop.id,
            name=found_req.product_name,
            quantity=1,
            status="available",
            stock_warning_active=False
        )
        db.add(new_item)
        db.flush()
        db.add(models.InventoryAlias(
            inventory_id=new_item.id,
            alias=found_req.product_name.lower()
        ))
    
    db.delete(found_req)
    db.commit()
    broadcast_event("pending_updated")
    return {"status": "success", "message": f"{found_req.product_name} marked as available"}

@router.post("/no/{request_id}")
def resolve_no(request_id: int, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    found_req = db.query(models.PendingRequest).filter(
        models.PendingRequest.id == request_id,
        models.PendingRequest.shop_id == current_shop.id
    ).first()
    
    if not found_req:
        raise HTTPException(status_code=404, detail="Request not found")

    if found_req.request_type == "oos_warning":
        if found_req.product_id:
            item = db.query(models.InventoryItem).filter(models.InventoryItem.id == found_req.product_id).first()
            if item:
                item.stock_warning_active = False
        db.delete(found_req)
        db.commit()
        broadcast_event("pending_updated")
        return {"status": "success", "message": "Warning dismissed"}
    
    existing_item = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == current_shop.id,
        sa_func.lower(models.InventoryItem.name) == found_req.product_name.lower()
    ).first()
    
    if existing_item:
        existing_item.quantity = 0
        existing_item.status = "out_of_stock"
        existing_item.stock_warning_active = True
        add_log_db(db, current_shop.id, existing_item.name, "low_stock", existing_item.id)
    else:
        new_item = models.InventoryItem(
            shop_id=current_shop.id,
            name=found_req.product_name,
            quantity=0,
            status="out_of_stock",
            stock_warning_active=True
        )
        db.add(new_item)
        db.flush()
        db.add(models.InventoryAlias(
            inventory_id=new_item.id,
            alias=found_req.product_name.lower()
        ))
        add_log_db(db, current_shop.id, new_item.name, "low_stock", new_item.id)
    
    db.delete(found_req)
    db.commit()
    broadcast_event("pending_updated")
    return {"status": "success", "message": f"{found_req.product_name} marked as out of stock"}
