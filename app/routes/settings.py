from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, require_permission, UserIdentity

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="templates")

# ── Shop Category constants ────────────────────────────────────────────────────
SHOP_CATEGORIES = [
    "Food & Restaurant",
    "Grocery",
    "Clothing & Fashion",
    "Electronics",
    "Pharmacy & Health",
    "Hardware & Tools",
    "Salon & Beauty",
    "Bakery",
    "Stationery",
    "General",
]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ShopProfileUpdate(BaseModel):
    shop_category: Optional[str] = None
    business_category: Optional[str] = None
    business_subnote: Optional[str] = None

    @validator("shop_category")
    def validate_shop_category(cls, v):
        if v is not None and v not in SHOP_CATEGORIES:
            raise ValueError(f"shop_category must be one of: {', '.join(SHOP_CATEGORIES)}")
        return v


# ── AI Settings page ──────────────────────────────────────────────────────────

@router.get("/shop-profile", response_class=HTMLResponse)
async def shop_profile_page(
    request: Request,
    identity: UserIdentity = Depends(require_permission("settings_view")),
    db: Session = Depends(get_db)
):
    """Render the Shop Profile settings page."""
    shop = identity.shop
    return templates.TemplateResponse(
        "settings/shop_profile.html",
        {
            "request": request,
            "shop_name": shop.shop_name,
            "shop_id": shop.id,
            "user_name": identity.name,
            "user_role": identity.role,
            "shop_category": getattr(shop, "shop_category", "General") or "General",
            "business_subnote": shop.business_subnote or "",
        }
    )


@router.get("/ai", response_class=HTMLResponse)
async def ai_settings_page(
    request: Request,
    identity: UserIdentity = Depends(require_permission("settings_view")),
    db: Session = Depends(get_db)
):
    """Render the AI Assistant settings page for the shop owner."""
    shop = identity.shop
    return templates.TemplateResponse(
        "settings/ai.html",
        {
            "request": request,
            "shop_name": shop.shop_name,
            "shop_id": shop.id,
            "user_name": identity.name,
            "user_role": identity.role
        }
    )


@router.get("/api/ai")
def get_ai_settings(
    identity: UserIdentity = Depends(require_permission("settings_view")),
    db: Session = Depends(get_db)
):
    """API to fetch AI settings."""
    return {
        "status": "success",
        "settings": {
            "ai_enabled": True,
            "auto_reply": True,
            "tone": "friendly",
            "escalate_on_uncertainty": True
        }
    }


@router.post("/api/ai")
def update_ai_settings(
    payload: dict,
    identity: UserIdentity = Depends(require_permission("settings_edit")),
    db: Session = Depends(get_db)
):
    """API to update AI settings."""
    return {"status": "success", "message": "AI Settings updated successfully"}


# ── Shop Profile (category + business details) ────────────────────────────────

@router.get("/api/shop-profile")
def get_shop_profile(
    identity: UserIdentity = Depends(require_permission("settings_view")),
    db: Session = Depends(get_db)
):
    """Return the shop profile settings including shop_category."""
    shop = db.query(models.Shop).filter_by(id=identity.shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return {
        "status": "success",
        "data": {
            "shop_name": shop.shop_name,
            "shop_category": shop.shop_category or "General",
            "business_category": shop.business_category or "",
            "business_subnote": shop.business_subnote or "",
            "available_categories": SHOP_CATEGORIES,
        }
    }


@router.patch("/api/shop-profile")
def update_shop_profile(
    payload: ShopProfileUpdate,
    identity: UserIdentity = Depends(require_permission("settings_edit")),
    db: Session = Depends(get_db)
):
    """Update shop profile fields, including shop_category."""
    shop = db.query(models.Shop).filter_by(id=identity.shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    changed = []
    if payload.shop_category is not None:
        shop.shop_category = payload.shop_category
        changed.append("shop_category")
    if payload.business_category is not None:
        shop.business_category = payload.business_category
        changed.append("business_category")
    if payload.business_subnote is not None:
        shop.business_subnote = payload.business_subnote
        changed.append("business_subnote")

    if changed:
        db.add(shop)
        db.commit()
        db.refresh(shop)

    return {
        "status": "success",
        "message": f"Updated: {', '.join(changed) if changed else 'nothing changed'}",
        "data": {
            "shop_category": shop.shop_category or "General",
            "business_category": shop.business_category or "",
            "business_subnote": shop.business_subnote or "",
        }
    }
