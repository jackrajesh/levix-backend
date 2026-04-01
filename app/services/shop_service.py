from fastapi import HTTPException
from sqlalchemy.orm import Session
from .. import models
from ..utils.encryption import encrypt


def get_shop_by_phone_number_id(phone_number_id: str, db: Session):
    """Return the Shop whose whatsapp_phone_number_id matches, or None."""
    if not phone_number_id:
        return None
    return (
        db.query(models.Shop)
        .filter(models.Shop.whatsapp_phone_number_id == phone_number_id)
        .first()
    )


def connect_whatsapp_to_shop(data, db: Session) -> dict:
    """
    Securely attach WhatsApp Cloud API credentials to a shop.

    - access_token is encrypted before storage
    - Raw token is never logged or returned
    """
    shop = db.query(models.Shop).filter(models.Shop.id == data.shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail=f"Shop with id {data.shop_id} not found")

    shop.whatsapp_phone_number_id = data.phone_number_id
    shop.whatsapp_access_token = encrypt(data.access_token)  # encrypt at save-time
    shop.whatsapp_business_account_id = data.business_account_id

    db.commit()
    print(f"[Admin] WhatsApp credentials saved for shop '{shop.shop_name}' (id={shop.id})")

    return {"status": "success", "message": "WhatsApp connected successfully"}
