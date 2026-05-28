"""
LEVIX Platform Superadmin Routes
---------------------------------
Access restricted to: levixsupport@gmail.com, founder.levix@gmail.com
These are LEVIX team accounts — NOT shop owners.

Endpoints:
  POST /superadmin/login          — Admin login (returns scoped JWT)
  GET  /superadmin/shops          — List all shops with status
  POST /superadmin/shops/{id}/approve  — Approve a pending shop
  POST /superadmin/shops/{id}/reject   — Reject with reason
  POST /superadmin/shops/{id}/ban      — Ban a shop
  POST /superadmin/shops/{id}/restore  — Restore a soft-deleted shop
  DELETE /superadmin/shops/{id}        — Soft delete a shop
  POST /superadmin/shops/{id}/trial    — Grant trial access
  GET  /superadmin/logs           — View recent activity logs across all shops
"""
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from .. import models, auth

router = APIRouter(prefix="/superadmin", tags=["superadmin"])

# ── Superadmin config ─────────────────────────────────────────────────────────
SUPERADMIN_EMAILS = {"levixsupport@gmail.com", "founder.levix@gmail.com"}

# Read admin password from env. Falls back to a strong default only for local dev.
# In production, LEVIX_ADMIN_PASSWORD MUST be set in the environment.
ADMIN_PASSWORD = os.getenv("LEVIX_ADMIN_PASSWORD", "")

_oauth2 = OAuth2PasswordBearer(tokenUrl="/superadmin/login", auto_error=False)

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _create_admin_token(email: str) -> str:
    return auth.create_access_token(
        data={"sub": email, "scope": "levix_admin"},
        expires_delta=timedelta(hours=8)
    )

def _require_superadmin(token: Optional[str] = Depends(_oauth2)) -> str:
    """Returns the admin email if token is valid and scoped as levix_admin."""
    if not token:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    try:
        payload = auth.jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        scope: str = payload.get("scope")
        if not email or scope != "levix_admin" or email not in SUPERADMIN_EMAILS:
            raise HTTPException(status_code=403, detail="Not authorized as LEVIX admin.")
        return email
    except auth.JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token.")

# ── Request models ────────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    email: str
    password: str

class RejectRequest(BaseModel):
    reason: str

class TrialRequest(BaseModel):
    days: int = 30  # default trial duration

# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login")
def superadmin_login(req: AdminLoginRequest):
    """Authenticates a LEVIX platform admin. Returns a scoped JWT."""
    email = req.email.strip().lower()

    if email not in SUPERADMIN_EMAILS:
        time.sleep(2)  # Mitigation against timing/brute-force
        raise HTTPException(status_code=403, detail="Access denied.")

    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Admin password not configured. Set LEVIX_ADMIN_PASSWORD in environment."
        )

    if req.password != ADMIN_PASSWORD:
        time.sleep(2)  # Slow down brute-force attempts
        raise HTTPException(status_code=401, detail="Incorrect admin credentials.")

    token = _create_admin_token(email)
    return {"access_token": token, "token_type": "bearer", "admin": email}

# ── Shop listing ──────────────────────────────────────────────────────────────

@router.get("/shops")
def list_shops(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    """Returns all shops. Filter by approval_status if ?status=pending etc."""
    print(f"[ADMIN DEBUG] Fetching shops... Filter: {status}")
    query = db.query(models.Shop)
    if status:
        query = query.filter(models.Shop.approval_status == status)
    shops = query.order_by(models.Shop.created_at.desc()).all()
    print(f"[ADMIN DEBUG] Found {len(shops)} shops.")

    return [
        {
            "id": s.id,
            "shop_name": s.shop_name,
            "owner_name": s.owner_name,
            "email": s.email,
            "phone_number": s.phone_number,
            "shop_category": s.shop_category,
            "approval_status": s.approval_status,
            "rejection_reason": s.rejection_reason,
            "approved_at": s.approved_at.isoformat() if s.approved_at else None,
            "approved_by": s.approved_by,
            "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in shops
    ]

# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/shops/{shop_id}/approve")
def approve_shop(
    shop_id: str,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")

    shop.approval_status = "approved"
    shop.approved_at = datetime.now(timezone.utc)
    shop.approved_by = admin
    shop.rejection_reason = None
    db.commit()
    return {"success": True, "message": f"Shop '{shop.shop_name}' approved.", "shop_id": shop_id}

# ── Reject ────────────────────────────────────────────────────────────────────

@router.post("/shops/{shop_id}/reject")
def reject_shop(
    shop_id: str,
    req: RejectRequest,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    if not req.reason or not req.reason.strip():
        raise HTTPException(status_code=400, detail="Rejection reason is required.")

    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")

    shop.approval_status = "rejected"
    shop.rejection_reason = req.reason.strip()
    db.commit()
    return {"success": True, "message": f"Shop '{shop.shop_name}' rejected.", "shop_id": shop_id}

# ── Ban ───────────────────────────────────────────────────────────────────────

@router.post("/shops/{shop_id}/ban")
def ban_shop(
    shop_id: str,
    req: RejectRequest,  # reuse — reason is mandatory for ban too
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    if not req.reason or not req.reason.strip():
        raise HTTPException(status_code=400, detail="Ban reason is required.")

    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")

    shop.approval_status = "banned"
    shop.rejection_reason = req.reason.strip()
    db.commit()
    return {"success": True, "message": f"Shop '{shop.shop_name}' banned.", "shop_id": shop_id}

# ── Soft delete ───────────────────────────────────────────────────────────────

@router.delete("/shops/{shop_id}")
def soft_delete_shop(
    shop_id: str,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    if shop.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Shop is already deleted.")

    shop.deleted_at = datetime.now(timezone.utc)
    shop.approval_status = "banned"
    db.commit()
    return {"success": True, "message": f"Shop '{shop.shop_name}' soft-deleted. Restorable within 30 days.", "shop_id": shop_id}

# ── Restore ───────────────────────────────────────────────────────────────────

@router.post("/shops/{shop_id}/restore")
def restore_shop(
    shop_id: str,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    if shop.deleted_at is None:
        raise HTTPException(status_code=400, detail="Shop is not deleted.")

    # Enforce 30-day restore window
    window = timedelta(days=30)
    if datetime.now(timezone.utc) - shop.deleted_at > window:
        raise HTTPException(
            status_code=400,
            detail="Restore window (30 days) has expired. Cannot restore this shop."
        )

    shop.deleted_at = None
    shop.approval_status = "approved"
    shop.approved_by = admin
    shop.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "message": f"Shop '{shop.shop_name}' restored successfully.", "shop_id": shop_id}

# ── Trial grant ───────────────────────────────────────────────────────────────

@router.post("/shops/{shop_id}/trial")
def grant_trial(
    shop_id: str,
    req: TrialRequest,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    if req.days < 1 or req.days > 90:
        raise HTTPException(status_code=400, detail="Trial days must be between 1 and 90.")

    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")

    shop.approval_status = "trial"
    shop.approved_by = admin
    shop.approved_at = datetime.now(timezone.utc)
    shop.rejection_reason = f"Trial: {req.days} days from {datetime.now(timezone.utc).date()}"
    db.commit()
    return {
        "success": True,
        "message": f"Trial of {req.days} days granted to '{shop.shop_name}'.",
        "shop_id": shop_id,
        "trial_days": req.days
    }

# ── Activity logs ─────────────────────────────────────────────────────────────

@router.get("/logs")
def get_recent_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    """Returns the most recent activity logs across all shops."""
    logs = (
        db.query(models.ActivityLog)
        .order_by(models.ActivityLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id": l.id,
            "shop_id": l.shop_id,
            "user_name": l.user_name,
            "role": l.role,
            "category": l.category,
            "action": l.action,
            "action_type": l.action_type,
            "entity_type": l.entity_type,
            "entity_name": l.entity_name,
            "severity": l.severity,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]

# ── Dashboard stats ───────────────────────────────────────────────────────────

@router.get("/stats")
def get_platform_stats(
    db: Session = Depends(get_db),
    admin: str = Depends(_require_superadmin)
):
    """Quick platform overview for the admin dashboard."""
    total = db.query(models.Shop).count()
    pending = db.query(models.Shop).filter(models.Shop.approval_status == "pending").count()
    approved = db.query(models.Shop).filter(models.Shop.approval_status == "approved").count()
    trial = db.query(models.Shop).filter(models.Shop.approval_status == "trial").count()
    rejected = db.query(models.Shop).filter(models.Shop.approval_status == "rejected").count()
    banned = db.query(models.Shop).filter(models.Shop.approval_status == "banned").count()
    deleted = db.query(models.Shop).filter(models.Shop.deleted_at.isnot(None)).count()

    return {
        "total_shops": total,
        "pending": pending,
        "approved": approved,
        "trial": trial,
        "rejected": rejected,
        "banned": banned,
        "soft_deleted": deleted,
    }
