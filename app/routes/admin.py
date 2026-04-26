from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .auth import get_current_shop, UserIdentity, require_permission
from ..schemas import ConnectWhatsAppRequest, ShopNameUpdate, ShopCategoryUpdate
from ..models import Shop
from ..database import get_db
from ..services.sse import broadcast_event
from ..services.shop_service import connect_whatsapp_to_shop

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/shop-name")
def update_shop_name(data: ShopNameUpdate, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("settings_edit"))):
    shop = identity.shop
    """Update the display name of the current shop."""
    shop.shop_name = data.shop_name
    db.commit()
    return {"status": "success", "message": "Shop name updated"}

@router.post("/shop-category")
def update_shop_category(data: ShopCategoryUpdate, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("settings_edit"))):
    shop = identity.shop
    shop.shop_category = data.shop_category
    db.commit()
    return {"status": "success", "message": "Shop category updated"}

@router.get("/shop-name")
def get_shop_name(identity: UserIdentity = Depends(require_permission("settings_view"))):
    shop = identity.shop
    return {"shop_name": shop.shop_name}

@router.post("/connect-whatsapp")
def connect_whatsapp(data: ConnectWhatsAppRequest, identity: UserIdentity = Depends(require_permission("settings_edit")), db: Session = Depends(get_db)):
    """
    Securely attach WhatsApp Cloud API credentials to a shop.
    Returns success message on completion.
    The access token is encrypted before storage.
    """
    return connect_whatsapp_to_shop(data, db)

@router.get("/whatsapp/status")
def whatsapp_status(identity: UserIdentity = Depends(require_permission("settings_view"))):
    shop = identity.shop
    return {
        "connected": bool(shop.whatsapp_phone_number_id and shop.whatsapp_access_token),
        "phone_number_id": shop.whatsapp_phone_number_id,
        "business_account_id": shop.whatsapp_business_account_id,
    }

@router.post("/whatsapp/config")
def update_whatsapp_config(data: ConnectWhatsAppRequest, identity: UserIdentity = Depends(require_permission("settings_edit")), db: Session = Depends(get_db)):
    return connect_whatsapp_to_shop(data, db)

@router.post("/force-refresh/{shop_id}")
def force_refresh(shop_id: int, identity: UserIdentity = Depends(require_permission("settings_edit"))):
    if identity.shop.id != shop_id:
         from fastapi import HTTPException
         raise HTTPException(status_code=403, detail="Not authorized for this shop")
    """
    Triggers a manual refresh event for the specified shop.
    Useful for external integrations or manual data updates.
    """
    # Broadcast to all possible listeners to ensure a UI update
    broadcast_event(shop_id, "pending_updated")
    broadcast_event(shop_id, "order_updated")
    broadcast_event(shop_id, "new_order", '{"order_id":"MANUAL","customer":"System"}')
    broadcast_event(shop_id, "hard_reload")
    return {"status": "success", "message": f"Refresh triggered for shop {shop_id}"}

@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("settings_view"))):
    """Task 2 fix: List recent system alerts for the shop."""
    from ..models import AdminAlert
    alerts = db.query(AdminAlert).filter(AdminAlert.shop_id == identity.shop.id).order_by(AdminAlert.created_at.desc()).limit(50).all()
    return alerts
