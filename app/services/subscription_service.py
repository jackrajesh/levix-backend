from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from ..models import Shop, Plan, Subscription, Addon, ShopAddon, TeamMember
from typing import List, Optional

class SubscriptionService:
    @staticmethod
    def get_shop_plan(db: Session, shop_id: int):
        sub = db.query(Subscription).filter(Subscription.shop_id == shop_id).first()
        if not sub:
            # Assign default Core Levix plan if not exists
            core_plan = db.query(Plan).filter(Plan.name == "Core Levix").first()
            if not core_plan:
                # Create default plan if DB is empty
                core_plan = Plan(
                    name="Core Levix",
                    price=499.00,
                    interval="monthly",
                    features=["WhatsApp automation", "Orders system", "Basic inventory"],
                    limits={"messages": 5000, "staff": 1}
                )
                db.add(core_plan)
                db.commit()
                db.refresh(core_plan)
            
            sub = Subscription(
                shop_id=shop_id,
                plan_id=core_plan.id,
                renewal_date=datetime.now(timezone.utc) + timedelta(days=30)
            )
            db.add(sub)
            db.commit()
            db.refresh(sub)
        return sub

    @staticmethod
    def get_activated_addons(db: Session, shop_id: int):
        return db.query(ShopAddon).filter(ShopAddon.shop_id == shop_id).all()

    @staticmethod
    def has_addon(db: Session, shop_id: int, addon_name: str) -> bool:
        addon = db.query(Addon).filter(Addon.name == addon_name).first()
        if not addon:
            return False
        shop_addon = db.query(ShopAddon).filter(
            ShopAddon.shop_id == shop_id,
            ShopAddon.addon_id == addon.id
        ).first()
        return shop_addon is not None

    @staticmethod
    def has_analytics_pro(db: Session, shop_id: int) -> bool:
        """
        Source-of-truth entitlement for premium analytics.
        Enabled if:
        - Analytics Pro addon is active, OR
        - Current plan features include Analytics Pro.
        """
        if SubscriptionService.has_addon(db, shop_id, "Analytics Pro"):
            return True

        sub = SubscriptionService.get_shop_plan(db, shop_id)
        plan_features = (sub.plan.features or []) if sub and sub.plan else []
        return any("analytics pro" in str(feature).lower() for feature in plan_features)

    @staticmethod
    def check_permission(user, resource: str, action: str) -> bool:
        """
        Check if a TeamMember or Shop owner has permission.
        Owner has 'full' access to everything.
        Staff/Managers have JSON-based permissions.
        """
        # If user is Shop object (owner)
        if hasattr(user, 'shop_name'):
            return True
            
        # If user is TeamMember object
        if hasattr(user, 'role'):
            if user.role == 'owner': # Fallback if we add owner role to TeamMember
                return True
            
            perms = user.permissions or {}
            resource_perms = perms.get(resource, "hidden")
            
            # Simple hierarchy: full > edit > view > hidden
            hierarchy = {"hidden": 0, "view": 1, "edit": 2, "full": 3}
            required = hierarchy.get(action, 1)
            actual = hierarchy.get(resource_perms, 0)
            
            return actual >= required
            
        return False

    @staticmethod
    def get_all_plans(db: Session):
        return db.query(Plan).filter(Plan.is_active == True).order_by(Plan.display_order).all()

    @staticmethod
    def get_all_addons(db: Session):
        return db.query(Addon).filter(Addon.is_active == True).all()

    @staticmethod
    def seed_initial_data(db: Session):
        # Create Plans if they don't exist
        if not db.query(Plan).first():
            plans = [
                Plan(name="Core Levix", price=499.00, display_order=1, features=["WhatsApp automation", "Human-like AI replies", "Orders system", "Single owner account"]),
                Plan(name="All Access Bundle", price=899.00, display_order=2, features=["Everything in Core", "Smart AI Memory", "Analytics Pro", "Team Access (5 staff)"])
            ]
            db.add_all(plans)
            
        # Create Addons if they don't exist
        if not db.query(Addon).first():
            addons = [
                Addon(name="Smart AI", price=299.00, description="Customer memory, repeat customer context, personalized replies."),
                Addon(name="Analytics Pro", price=299.00, description="Advanced graphs, sales trends, missed demand analysis, Export to Excel."),
                Addon(name="Team Access", price=399.00, description="Unlock multiple staff accounts with granular permissions.")
            ]
            db.add_all(addons)
        
        db.commit()
