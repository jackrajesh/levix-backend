from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, cast, String
from typing import Optional, List
from datetime import datetime, timedelta
import io
import pandas as pd
from fastapi.responses import StreamingResponse

from .. import models
from ..database import get_db
from .auth import UserIdentity, require_permission
from ..services.logger import LoggerService

router = APIRouter(prefix="/api/logs", tags=["Logs"])

@router.get("")
async def get_logs(
    search: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    user_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    identity: UserIdentity = Depends(require_permission("logs_view"))
):
    try:
        shop_id = identity.id
        query = db.query(models.ActivityLog).filter(models.ActivityLog.shop_id == shop_id)

        if category and category != "All Logs":
            query = query.filter(models.ActivityLog.category == category)
        
        if severity and severity != "All":
            query = query.filter(models.ActivityLog.severity == severity.lower())
            
        if user_filter and user_filter != "All Users":
            query = query.filter(models.ActivityLog.user_name == user_filter)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(or_(
                models.ActivityLog.action.ilike(search_filter),
                models.ActivityLog.target.ilike(search_filter),
                models.ActivityLog.user_name.ilike(search_filter),
                models.ActivityLog.category.ilike(search_filter),
                models.ActivityLog.entity_name.ilike(search_filter),
                models.ActivityLog.action_type.ilike(search_filter),
                cast(models.ActivityLog.old_values, String).ilike(search_filter),
                cast(models.ActivityLog.new_values, String).ilike(search_filter),
                cast(models.ActivityLog.log_metadata, String).ilike(search_filter),
            ))

        if start_date:
            try:
                sd = datetime.strptime(start_date[:10], "%Y-%m-%d")
                query = query.filter(models.ActivityLog.created_at >= sd)
            except: pass
            
        if end_date:
            try:
                ed = datetime.strptime(end_date[:10], "%Y-%m-%d") + timedelta(days=1)
                query = query.filter(models.ActivityLog.created_at < ed)
            except: pass

        total = query.count()
        logs = query.order_by(desc(models.ActivityLog.created_at)).offset((page - 1) * limit).limit(limit).all()

        users = db.query(models.ActivityLog.user_name).filter(models.ActivityLog.shop_id == shop_id).distinct().all()
        user_names = [u[0] for u in users if u[0]]

        return {
            "logs": [
                {
                    "id": l.id,
                    "timestamp": l.created_at.isoformat() if l.created_at else None,
                    "user_name": l.user_name,
                    "role": l.role,
                    "category": l.category,
                    "action": l.action,
                    "target": l.target,
                    "action_type": l.action_type,
                    "entity_name": l.entity_name,
                    "old_value": l.old_value,
                    "new_value": l.new_value,
                    "severity": l.severity,
                    "ip_address": l.ip_address
                }
                for l in logs
            ],
            "total": total,
            "page": page,
            "limit": limit,
            "users": user_names
        }
    except Exception as e:
        print(f"[LOGS API ERROR] {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch logs")

@router.delete("/clear")
async def clear_logs(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("logs_clear"))):
    if identity.user_type != "owner":
        raise HTTPException(status_code=403, detail="Only owners can clear logs")
    
    shop_id = identity.shop.id
    db.query(models.ActivityLog).filter(models.ActivityLog.shop_id == shop_id).delete()
    db.commit()
    
    LoggerService.log(
        db, shop_id, identity, "System Events", "Cleared all activity logs", severity="critical"
    )
    
    return {"success": True}

@router.get("/export")
async def export_logs(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    identity: UserIdentity = Depends(require_permission("logs_export"))
):
    shop_id = identity.shop.id
    query = db.query(models.ActivityLog).filter(models.ActivityLog.shop_id == shop_id)
    
    if category and category != "All Logs":
        query = query.filter(models.ActivityLog.category == category)
        
    logs = query.order_by(desc(models.ActivityLog.created_at)).all()
    
    data = []
    for l in logs:
        data.append({
            "Date": l.created_at.strftime("%Y-%m-%d"),
            "Time": l.created_at.strftime("%H:%M:%S"),
            "User": l.user_name,
            "Role": l.role,
            "Category": l.category,
            "Action": l.action,
            "Target": l.target,
            "Old": l.old_value,
            "New": l.new_value,
            "Severity": l.severity
        })
        
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if data:
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='Activity Logs', index=False)
        else:
            pd.DataFrame([{"Message": "No logs found"}]).to_excel(writer, index=False)
            
    output.seek(0)
    filename = f"Levix_Logs_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/{log_id}")
async def get_log_details(
    log_id: int,
    db: Session = Depends(get_db),
    identity: UserIdentity = Depends(require_permission("logs_view"))
):
    try:
        shop_id = identity.id
        log = db.query(models.ActivityLog).filter(
            models.ActivityLog.id == log_id,
            models.ActivityLog.shop_id == shop_id
        ).first()

        if not log:
            raise HTTPException(status_code=404, detail="Log entry not found")

        return {
            "id": str(log.id),
            "category": log.category,
            "action": log.action,
            "target": log.target,
            "user_name": log.user_name,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "action_type": log.action_type or (log.category.lower().replace(" / ", "_").replace(" ", "_")),
            "entity_type": log.entity_type,
            "entity_name": log.entity_name or log.target,
            "actor_name": log.actor_name or log.user_name,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "severity": (log.severity or "info").lower(),
            "old_values": log.old_values,
            "new_values": log.new_values,
            "metadata": log.log_metadata or ({
                "ip": log.ip_address
            } if log.ip_address else None)
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[LOG DETAILS API ERROR] {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch log details")
