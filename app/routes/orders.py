from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, UserIdentity, require_permission, require_active_subscription
from ..services.sse import broadcast_event
from ..services.logger import LoggerService
import json

router = APIRouter(prefix="/orders", tags=["orders"])

@router.get("", response_model=List[schemas.OrderResponse])
def get_orders(status: Optional[str] = None, identity: UserIdentity = Depends(require_permission("orders_view")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    query = db.query(models.Order).filter(models.Order.shop_id == current_shop.id)
    if status:
        status_val = status.upper()
        if status_val == "ACCEPTED":
            query = query.filter(models.Order.status.in_(["ACCEPTED", "CONFIRMED"]))
        elif status_val == "REJECTED":
            query = query.filter(models.Order.status.in_(["REJECTED", "CANCELLED"]))
        elif status_val == "COMPLETED":
            query = query.filter(models.Order.status.in_(["COMPLETED", "DELIVERED"]))
        else:
            query = query.filter(models.Order.status == status_val)
    return query.order_by(models.Order.created_at.desc()).all()

@router.get("/{booking_id}", response_model=schemas.OrderResponse)
def get_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_view")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def log_order_action(db: Session, shop_id: str, order_id: str, action: str, identity: UserIdentity):
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
def accept_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_edit")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = "CONFIRMED"
    log_order_action(db, current_shop.id, order.order_id, "order_accepted", identity)
    db.commit()
    
    # Centralized Order Notification Trigger
    try:
        from ..services.order_notification_service import OrderNotificationService
        OrderNotificationService.send_order_accepted_message(order, db)
    except Exception as notify_err:
        import logging
        logging.getLogger("levix.orders").error(f"[ORDER_NOTIFY] Accepted message failed to send: {notify_err}")
        
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Accepted order {order.booking_id}",
        target=f"Booking: {order.booking_id}"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "CONFIRMED"}))
    return {"status": "success", "message": "Order accepted"}

@router.patch("/{booking_id}/reject")
def reject_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_cancel")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = "CANCELLED"
    log_order_action(db, current_shop.id, order.order_id, "order_rejected", identity)
    db.commit()
    
    # Centralized Order Notification Trigger
    try:
        from ..services.order_notification_service import OrderNotificationService
        OrderNotificationService.send_order_rejected_message(order, db)
    except Exception as notify_err:
        import logging
        logging.getLogger("levix.orders").error(f"[ORDER_NOTIFY] Rejected message failed to send: {notify_err}")
        
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Rejected order {order.booking_id}",
        target=f"Booking: {order.booking_id}",
        severity="warning"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "CANCELLED"}))
    return {"status": "success", "message": "Order rejected"}

@router.patch("/{booking_id}/complete")
def complete_order(booking_id: str, identity: UserIdentity = Depends(require_permission("orders_edit")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    order = db.query(models.Order).filter(models.Order.booking_id == booking_id, models.Order.shop_id == current_shop.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status == "DELIVERED":
        return {"status": "error", "message": "Order already completed"}

    # Verify transition
    if order.status != "ACCEPTED" and order.status != "CONFIRMED":
         raise HTTPException(status_code=400, detail="Order must be accepted before completion")

    order.status = "DELIVERED"
    
    # --- REDUCE INVENTORY & CREATE SALES RECORDS ---
    from datetime import date
    import logging
    logger = logging.getLogger("levix.orders")
    
    order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
    
    if not order_items:
        # Fallback to legacy flat fields if no items found
        logger.warning(f"[COMPLETE] No order items found for {order.id}. Using flat fields.")
        sale = models.SalesRecord(
            shop_id=current_shop.id,
            product_name=order.product or "Order Item",
            date=date.today(),
            quantity=order.quantity or 1,
            price=order.unit_price if order.unit_price is not None else 0,
            performed_by=identity.name,
            user_type=identity.user_type
        )
        db.add(sale)
    else:
        for item in order_items:
            # Reduce inventory
            inv_item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item.product_id).first()
            if inv_item:
                if inv_item.quantity < item.quantity:
                     logger.warning(f"[COMPLETE] Insufficient stock for {inv_item.name} ({inv_item.quantity} < {item.quantity}). Failing.")
                     raise HTTPException(status_code=400, detail=f"Insufficient stock for {inv_item.name}")
                
                inv_item.quantity -= item.quantity
                logger.info(f"[COMPLETE] Deducted {item.quantity} from stock of {inv_item.name}")
            
            # Create SalesRecord
            sale = models.SalesRecord(
                shop_id=current_shop.id,
                product_id=item.product_id,
                product_name=item.name,
                date=date.today(),
                quantity=item.quantity,
                price=item.price,
                performed_by=identity.name,
                user_type=identity.user_type
            )
            db.add(sale)
    
    log_order_action(db, current_shop.id, order.order_id, "order_completed", identity)
    db.commit()
    
    # Centralized Order Notification Trigger
    try:
        from ..services.order_notification_service import OrderNotificationService
        OrderNotificationService.send_order_completed_message(order, db)
    except Exception as notify_err:
        logger.error(f"[ORDER_NOTIFY] Completed message failed to send: {notify_err}")
        
    LoggerService.log(
        db, current_shop.id, identity, "Orders", 
        f"Completed order {order.booking_id} & recorded sales",
        target=f"Booking: {order.booking_id}",
        severity="info"
    )
    broadcast_event(current_shop.id, "order_updated", json.dumps({"booking_id": booking_id, "status": "DELIVERED"}))
    return {"status": "success", "message": "Order completed & sales recorded"}

@router.post("/bulk-delete")
def bulk_delete_orders(request: schemas.BulkDeleteRequest, identity: UserIdentity = Depends(require_permission("orders_cancel")), _sub: UserIdentity = Depends(require_active_subscription), db: Session = Depends(get_db)):
    current_shop = identity.shop
    # request.order_ids will contain the 'id' (string/UUID) of the orders to delete
    
    # Delete order items first to avoid foreign key violation
    db.query(models.OrderItem).filter(models.OrderItem.order_id.in_(request.order_ids)).delete(synchronize_session=False)
    
    deleted = db.query(models.Order).filter(
        models.Order.id.in_(request.order_ids),
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
