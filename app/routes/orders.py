from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, UserIdentity, require_permission
from ..services.sse import broadcast_event
from ..services.logger import LoggerService
import json

router = APIRouter(prefix="/orders", tags=["orders"])

@router.get("", response_model=List[schemas.OrderResponse])
def get_orders(status: Optional[str] = None, identity: UserIdentity = Depends(require_permission("orders_view")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    query = db.query(models.Order).filter(models.Order.shop_id == current_shop.id)
    if status:
        query = query.filter(models.Order.status == status)
    return query.order_by(models.Order.created_at.desc()).all()

@router.get("/{booking_id}", response_model=schemas.OrderResponse)
def get_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_view")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def log_order_action(db: Session, shop_id: int, order_id: str, action: str, identity: UserIdentity):
    log = models.OrderLog(
        shop_id=shop_id, 
        order_id=order_id, 
        action=action,
        performed_by=identity.name,
        user_type=identity.user_type
    )
    db.add(log)
    db.commit()

@router.patch("/{booking_id}/accept")
def accept_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_edit")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = "accepted"
    log_order_action(db, current_shop.id, order.order_id, "order_accepted", identity)
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Accepted order {order.booking_id}",
        target=f"Booking: {order.booking_id}"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "accepted"}))
    return {"status": "success", "message": "Order accepted"}

@router.patch("/{booking_id}/reject")
def reject_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_cancel")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = "rejected"
    log_order_action(db, current_shop.id, order.order_id, "order_rejected", identity)
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Rejected order {order.booking_id}",
        target=f"Booking: {order.booking_id}",
        severity="Warning"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "rejected"}))
    return {"status": "success", "message": "Order rejected"}

@router.patch("/{booking_id}/complete")
def complete_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_edit")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status == "completed":
        return {"status": "error", "message": "Order already completed"}

    order.status = "completed"
    
    # --- AUTO SALES ENTRY ---
    from datetime import date
    sale = models.SalesRecord(
        shop_id=current_shop.id,
        product_name=order.product,
        date=date.today(),
        quantity=order.quantity,
        price=order.unit_price, # Total is calculated in the Sales logic usually, but we store unit price
        performed_by=identity.name,
        user_type=identity.user_type
    )
    db.add(sale)
    
    log_order_action(db, current_shop.id, order.order_id, "order_completed", identity)
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Completed order {order.booking_id} & auto-recorded sale",
        target=f"Booking: {order.booking_id}",
        severity="Info"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "completed"}))
    return {"status": "success", "message": "Order completed & sale recorded"}

@router.post("/bulk-delete")
def bulk_delete_orders(request: schemas.BulkDeleteRequest, identity: UserIdentity = Depends(require_permission("orders_cancel")), db: Session = Depends(get_db)):
    current_shop = identity.shop
    # request.ids will contain the 'id' (integer) of the orders to delete
    # Note: In the UI we often use booking_id, but schemas.BulkDeleteRequest uses list[int]
    # Let's check models to see if Order.id exists (it should as a PK)
    
    deleted = db.query(models.Order).filter(
        models.Order.id.in_(request.ids),
        models.Order.shop_id == current_shop.id
    ).delete(synchronize_session=False)
    
    db.commit()
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Bulk deleted {deleted} orders",
        severity="Warning"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"action": "bulk_delete", "count": deleted}))
    return {"status": "success", "deleted_count": deleted}
