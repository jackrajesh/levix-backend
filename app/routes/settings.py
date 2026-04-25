from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Dict, Any

from .. import models, schemas
from ..database import get_db
from .auth import get_current_shop, require_permission, UserIdentity

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="templates")

@router.get("/ai", response_class=HTMLResponse)
async def ai_settings_page(
    request: Request,
    identity: UserIdentity = Depends(require_permission("settings_view")),
    db: Session = Depends(get_db)
):
    """Render the AI Assistant settings page for the shop owner."""
    shop = identity.shop
    
    # We could fetch custom AI settings from the database if a model existed.
    # For now, we render the template with basic context.
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
    # Placeholder for fetching actual DB settings
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
    # Placeholder for updating actual DB settings
    return {"status": "success", "message": "AI Settings updated successfully"}
