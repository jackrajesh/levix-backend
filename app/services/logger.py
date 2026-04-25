from sqlalchemy.orm import Session
from ..models import ActivityLog
from ..auth import UserIdentity
from typing import Optional, Any

class LoggerService:
    @staticmethod
    def log(
        db: Session,
        shop_id: int,
        identity: Optional[UserIdentity],
        category: str,
        action: str,
        target: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        severity: str = "info",
        ip: Optional[str] = None,
        action_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_name: Optional[str] = None,
        old_values: Optional[dict[str, Any]] = None,
        new_values: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """
        Creates a new activity log entry.
        """
        user_id = None
        user_name = "System"
        role = "System"

        if identity:
            user_id = identity.user_id
            user_name = identity.name
            role = identity.role

        normalized_action_type = action_type or category.lower().replace(" / ", "_").replace(" ", "_")
        normalized_severity = (severity or "info").lower()

        log_entry = ActivityLog(
            shop_id=shop_id,
            user_id=user_id,
            user_name=user_name,
            role=role,
            category=category,
            action=action,
            target=target,
            action_type=normalized_action_type,
            entity_type=entity_type,
            entity_name=entity_name or target,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            old_values=old_values,
            new_values=new_values,
            actor_name=user_name,
            severity=normalized_severity,
            log_metadata=metadata,
            ip_address=ip,
        )
        
        db.add(log_entry)
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[LOGGER ERROR] Failed to save log: {e}")
