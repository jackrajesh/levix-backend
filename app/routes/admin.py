from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..schemas import ConnectWhatsAppRequest
from ..database import get_db
from ..services.shop_service import connect_whatsapp_to_shop

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/connect-whatsapp")
def connect_whatsapp(data: ConnectWhatsAppRequest, db: Session = Depends(get_db)):
    """
    Securely attach WhatsApp Cloud API credentials to a shop.
    Returns success message on completion.
    The access token is encrypted before storage.
    """
    return connect_whatsapp_to_shop(data, db)
