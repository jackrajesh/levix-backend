from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.subscription_service import SubscriptionService
from ..models import Shop, Plan, Addon, TeamMember
from ..services.logger import LoggerService
from typing import List

router = APIRouter(prefix="/api/plans", tags=["Plans"])

from .auth import get_current_shop, UserIdentity, require_permission

@router.get("/current")
async def get_current_plan(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("billing_view"))):
    user = identity.shop
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    sub = SubscriptionService.get_shop_plan(db, user.id)
    addons = SubscriptionService.get_activated_addons(db, user.id)
    
    return {
        "plan": {
            "name": sub.plan.name,
            "status": sub.status,
            "billing_cycle": sub.plan.interval,
            "renewal_date": sub.renewal_date,
            "shop_id": user.id
        },
        "activated_addons": [{"id": a.addon.id, "name": a.addon.name} for a in addons]
    }

@router.get("/all")
async def get_all_plans_and_addons(db: Session = Depends(get_db)):
    plans = SubscriptionService.get_all_plans(db)
    addons = SubscriptionService.get_all_addons(db)
    
    return {
        "plans": plans,
        "addons": addons
    }

@router.get("/billing-history")
async def get_billing_history(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("billing_view"))):
    user = identity.shop
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    history = user.billing_history
    return history

@router.get("/usage")
async def get_usage_limits(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("billing_view"))):
    user = identity.shop
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    from sqlalchemy import func
    from ..models import LogEntry, Order, SalesRecord, ShopAddon, Addon
    
    # Real Counts
    messages_count = db.query(LogEntry).filter(LogEntry.shop_id == user.id).count()
    orders_count = db.query(Order).filter(Order.shop_id == user.id).count()
    
    # Real Revenue
    revenue_sum = db.query(func.sum(SalesRecord.quantity * SalesRecord.price)).filter(SalesRecord.shop_id == user.id).scalar() or 0
    
    # Team Check
    staff_count = len(user.team_members)
    
    # Check if "Team Access" addon (id 3 or named) is active
    has_team_access = db.query(ShopAddon).join(Addon).filter(
        ShopAddon.shop_id == user.id,
        Addon.name.contains("Team")
    ).first() is not None
    
    # Get plan limits (default to Core limits)
    sub = SubscriptionService.get_shop_plan(db, user.id)
    msg_limit = sub.plan.limits.get("messages", 1000) if sub.plan.limits else 1000
    
    # Logic: Core has 0 staff slots by default. Addon unlocks slots.
    staff_limit = 10 if has_team_access else 0 # 0 means "Locked" in UI

    return {
        "messages_used": messages_count,
        "messages_limit": msg_limit,
        "orders_processed": orders_count,
        "revenue_tracked": round(float(revenue_sum), 2),
        "staff_users_used": staff_count,
        "staff_users_limit": staff_limit,
        "has_team_access": has_team_access
    }

@router.post("/upgrade")
async def upgrade_plan(plan_id: int = None, addon_type: str = None, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("billing_manage"))):
    if identity.user_type != 'owner' and not identity.has_permission("billing_manage"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    user = identity.shop
    
    from ..models import Plan, Addon, ShopAddon
    from datetime import datetime, timedelta, timezone

    if addon_type:
        # Map string ID to real name
        name_map = {
            "smart_ai": "Smart AI",
            "analytics_pro": "Analytics Pro",
            "team_access": "Team Access"
        }
        addon_name = name_map.get(addon_type)
        if not addon_name:
            raise HTTPException(status_code=400, detail="Invalid addon type")
            
        addon = db.query(Addon).filter(Addon.name == addon_name).first()
        if not addon:
            raise HTTPException(status_code=404, detail="Addon not found in database")
            
        # Check if already active
        existing = db.query(ShopAddon).filter(ShopAddon.shop_id == user.id, ShopAddon.addon_id == addon.id).first()
        if existing:
            return {"message": f"{addon_name} is already active.", "checkout_url": None}

        # Simulate Payment & Activation
        new_addon = ShopAddon(
            shop_id=user.id,
            addon_id=addon.id,
            expiry_date=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db.add(new_addon)
        db.commit()
        LoggerService.log(
            db, user.id, identity, "Plan & Billing", 
            f"Activated add-on: {addon_name}",
            target=addon_name,
            action_type="billing_addon_activated",
            entity_type="billing",
            entity_name=addon_name,
            severity="warning",
            new_values={
                "plan_name": addon_name,
                "amount": float(addon.price) if addon.price is not None else 0.0,
                "payment_status": "paid",
                "transaction_id": None,
                "renewal_date": new_addon.expiry_date.isoformat() if new_addon.expiry_date else None,
            },
            metadata={"event_kind": "billing"}
        )
        
        return {
            "message": f"{addon_name} activated successfully!",
            "checkout_url": "#payment-success"
        }

    if plan_id:
        plan = db.query(Plan).filter(Plan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Simulate subscription update
        sub = user.subscription
        if sub:
            sub.plan_id = plan.id
            sub.renewal_date = datetime.now(timezone.utc) + timedelta(days=30)
            db.commit()
            LoggerService.log(
                db, user.id, identity, "Plan & Billing", 
                f"Upgraded plan to: {plan.name}",
                target=plan.name,
                action_type="billing_plan_upgraded",
                entity_type="billing",
                entity_name=plan.name,
                severity="warning",
                new_values={
                    "plan_name": plan.name,
                    "amount": float(plan.price) if plan.price is not None else 0.0,
                    "payment_status": "paid",
                    "transaction_id": sub.razorpay_subscription_id,
                    "renewal_date": sub.renewal_date.isoformat() if sub.renewal_date else None,
                },
                metadata={"event_kind": "billing"}
            )
            return {"message": f"Upgraded to {plan.name}!", "checkout_url": "#payment-success"}

    return {"message": "Specify a plan or addon to upgrade.", "checkout_url": None}
