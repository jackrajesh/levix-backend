from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import TeamMember, Shop, ShopRole
from ..auth import hash_password
from ..services.logger import LoggerService
from typing import List, Dict
from ..permissions import DEFAULT_ROLE_SUGGESTIONS, ROLE_TEMPLATES, normalize_permissions, PERMISSION_GROUPS

router = APIRouter(prefix="/api/team", tags=["Team"])

from .auth import get_current_shop, UserIdentity, require_permission

def _migrate_legacy_permissions(owner_id: int, db: Session) -> None:
    updated = False
    members = db.query(TeamMember).filter(TeamMember.shop_id == owner_id).all()
    for member in members:
        normalized = normalize_permissions(member.permissions)
        if normalized != (member.permissions or []):
            member.permissions = normalized
            updated = True
    roles = db.query(ShopRole).filter(ShopRole.shop_id == owner_id).all()
    for role in roles:
        normalized = normalize_permissions(role.permissions)
        if normalized != (role.permissions or []):
            role.permissions = normalized
            updated = True
    if updated:
        db.commit()


# ─── SHOP ROLES ───────────────────────────────────────────────────────────────

@router.get("/roles")
async def get_shop_roles(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_view"))):
    """Return all roles for this shop (custom + suggestions)."""
    owner = identity.shop
    _migrate_legacy_permissions(owner.id, db)

    # Saved custom roles for this shop
    saved_roles = db.query(ShopRole).filter(ShopRole.shop_id == owner.id).all()
    saved_names = [r.name for r in saved_roles]

    # Also collect roles currently used by members (auto-created roles)
    used_roles = db.query(TeamMember.role).filter(TeamMember.shop_id == owner.id).distinct().all()
    used_names = [r[0] for r in used_roles]

    # Merge: saved + used + defaults (no duplicates)
    all_roles = list(dict.fromkeys(saved_names + used_names + DEFAULT_ROLE_SUGGESTIONS))

    return {
        "roles": all_roles,
        "saved_roles": [{"id": r.id, "name": r.name, "permissions": normalize_permissions(r.permissions)} for r in saved_roles],
        "templates": ROLE_TEMPLATES,
        "permission_groups": PERMISSION_GROUPS,
    }


@router.post("/roles")
async def create_shop_role(data: Dict, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_manage_permissions"))):
    """Create or update a custom role for this shop."""
    owner = identity.shop

    name = data.get("name", "").strip()
    permissions = normalize_permissions(data.get("permissions", []))

    if not name:
        raise HTTPException(status_code=400, detail="Role name required")

    # Upsert: update if exists, else create
    existing = db.query(ShopRole).filter(
        ShopRole.shop_id == owner.id,
        ShopRole.name == name
    ).first()

    if existing:
        existing.permissions = permissions
    else:
        new_role = ShopRole(shop_id=owner.id, name=name, permissions=permissions)
        db.add(new_role)

    db.commit()
    LoggerService.log(
        db, owner.id, identity, "Team Changes", 
        f"Modified custom role permissions: {name}",
        target=name,
        action_type="staff_permission_changed",
        entity_type="role",
        entity_name=name,
        severity="info",
        new_values={
            "staff_name": name,
            "role": name,
            "change_type": "permission_changed",
            "permissions": permissions,
            "changed_by": identity.name,
        },
        metadata={"event_kind": "staff"}
    )
    return {"success": True, "name": name}


@router.delete("/roles/{role_name}")
async def delete_shop_role(role_name: str, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_manage_permissions"))):
    """Delete a custom role from this shop."""
    owner = identity.shop

    role = db.query(ShopRole).filter(
        ShopRole.shop_id == owner.id,
        ShopRole.name == role_name
    ).first()

    if role:
        db.delete(role)
        db.commit()
        LoggerService.log(
            db, owner.id, identity, "Team Changes", 
            f"Deleted custom role: {role_name}",
            target=role_name,
            action_type="staff_removed",
            entity_type="role",
            entity_name=role_name,
            severity="critical",
            old_values={
                "staff_name": role_name,
                "role": role_name,
                "change_type": "removed",
                "changed_by": identity.name,
            },
            metadata={"event_kind": "staff"}
        )
    return {"success": True}


# ─── TEAM MEMBERS ─────────────────────────────────────────────────────────────

@router.get("/members")
async def get_team_members(db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_view"))):
    owner = identity.shop
    _migrate_legacy_permissions(owner.id, db)

    members = db.query(TeamMember).filter(TeamMember.shop_id == owner.id).all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "email": m.email,
            "role": m.role,
            "permissions": normalize_permissions(m.permissions),
            "is_active": m.is_active,
            "status": m.status or ("active" if m.is_active else "disabled"),
            "last_login": m.last_login.isoformat() if m.last_login else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in members
    ]


@router.post("/members")
async def add_team_member(data: Dict, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_add_member"))):
    owner = identity.shop
    if identity.user_type != "owner":
        # Additional security: only owners can add/manage members for now, or check for specific 'manage_team' permission
        pass

    email = data.get("email", "").strip().lower()
    if not email or not data.get("name") or not data.get("password"):
        raise HTTPException(status_code=400, detail="Name, email and password are required")

    # Check duplicate email
    existing = db.query(TeamMember).filter(TeamMember.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")

    role_name = data.get("role", "Staff").strip() or "Staff"

    # Auto-save new role if not in default suggestions
    if role_name not in DEFAULT_ROLE_SUGGESTIONS:
        exists_role = db.query(ShopRole).filter(
            ShopRole.shop_id == owner.id, ShopRole.name == role_name
        ).first()
        if not exists_role:
            db.add(ShopRole(shop_id=owner.id, name=role_name, permissions=normalize_permissions(data.get("permissions", []))))

    new_member = TeamMember(
        shop_id=owner.id,
        name=data.get("name").strip(),
        email=email,
        password_hash=hash_password(data.get("password")),
        role=role_name,
        permissions=normalize_permissions(data.get("permissions", [])),
        is_active=True,
        status="active",
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    LoggerService.log(
        db, owner.id, identity, "Staff Activity", 
        f"Added new team member: {new_member.name}",
        target=new_member.email,
        new_value=new_member.role,
        action_type="staff_added",
        entity_type="staff",
        entity_name=new_member.name,
        severity="success",
        new_values={
            "staff_name": new_member.name,
            "role": new_member.role,
            "change_type": "added",
            "changed_by": identity.name,
            "permissions": normalize_permissions(new_member.permissions),
        },
        metadata={"event_kind": "staff"}
    )

    return {
        "id": new_member.id,
        "name": new_member.name,
        "email": new_member.email,
        "role": new_member.role,
        "permissions": normalize_permissions(new_member.permissions),
        "is_active": new_member.is_active,
        "status": new_member.status,
        "last_login": None,
        "created_at": new_member.created_at.isoformat() if new_member.created_at else None,
    }


@router.put("/members/{member_id}")
async def update_team_member(member_id: int, data: Dict, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_edit_member"))):
    owner = identity.shop

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.shop_id == owner.id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    before_snapshot = {
        "staff_name": member.name,
        "role": member.role,
        "permissions": normalize_permissions(member.permissions),
        "status": member.status,
    }
    if "name" in data and data["name"]:
        member.name = data["name"].strip()
    if "email" in data and data["email"]:
        member.email = data["email"].strip().lower()
    if "role" in data and data["role"]:
        role_name = data["role"].strip()
        member.role = role_name
        # Auto-save new role
        if role_name not in DEFAULT_ROLE_SUGGESTIONS:
            existing_role = db.query(ShopRole).filter(
                ShopRole.shop_id == owner.id, ShopRole.name == role_name
            ).first()
            if not existing_role:
                db.add(ShopRole(shop_id=owner.id, name=role_name, permissions=normalize_permissions(data.get("permissions", []))))
    if "permissions" in data:
        member.permissions = normalize_permissions(data["permissions"])
    if "password" in data and data["password"]:
        member.password_hash = hash_password(data["password"])
    if "status" in data:
        member.status = data["status"]
        member.is_active = (data["status"] == "active")

    db.commit()
    after_snapshot = {
        "staff_name": member.name,
        "role": member.role,
        "permissions": normalize_permissions(member.permissions),
        "status": member.status,
    }
    LoggerService.log(
        db, owner.id, identity, "Staff Activity", 
        f"Updated profile for {member.name}",
        target=member.email,
        action_type="staff_permission_changed",
        entity_type="staff",
        entity_name=member.name,
        old_values=before_snapshot,
        new_values=after_snapshot,
        severity="info",
        metadata={"event_kind": "staff"}
    )

    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "role": member.role,
        "permissions": normalize_permissions(member.permissions),
        "is_active": member.is_active,
        "status": member.status,
        "last_login": member.last_login.isoformat() if member.last_login else None,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


@router.patch("/members/{member_id}/toggle-status")
async def toggle_member_status(member_id: int, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_edit_member"))):
    owner = identity.shop

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.shop_id == owner.id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.is_active = not member.is_active
    member.status = "active" if member.is_active else "disabled"
    db.commit()
    LoggerService.log(
        db, owner.id, identity, "Staff Activity", 
        f"Toggled status for {member.name} to {member.status}",
        target=member.email,
        action_type="staff_permission_changed",
        entity_type="staff",
        entity_name=member.name,
        severity="warning" if not member.is_active else "info",
        new_values={
            "staff_name": member.name,
            "role": member.role,
            "change_type": "permission_changed",
            "status": member.status,
            "changed_by": identity.name,
        },
        metadata={"event_kind": "staff"}
    )

    return {"id": member.id, "is_active": member.is_active, "status": member.status}


@router.patch("/members/{member_id}/reset-password")
async def reset_member_password(member_id: int, data: Dict, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_edit_member"))):
    owner = identity.shop

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.shop_id == owner.id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    new_password = data.get("password", "").strip()
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    member.password_hash = hash_password(new_password)
    db.commit()

    return {"success": True, "message": "Password reset successfully"}


@router.delete("/members/{member_id}")
async def delete_team_member(member_id: int, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("team_remove_member"))):
    owner = identity.shop

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.shop_id == owner.id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    removed_snapshot = {
        "staff_name": member.name,
        "role": member.role,
        "change_type": "removed",
        "changed_by": identity.name,
        "permissions": normalize_permissions(member.permissions),
    }
    db.delete(member)
    db.commit()
    LoggerService.log(
        db, owner.id, identity, "Staff Activity", 
        f"Removed team member: {member.name}",
        target=member.email,
        action_type="staff_removed",
        entity_type="staff",
        entity_name=member.name,
        severity="critical",
        old_values=removed_snapshot,
        metadata={"event_kind": "staff"}
    )
    return {"message": "Member deleted"}

@router.post("/members/{member_id}/impersonate")
async def impersonate_member(member_id: int, db: Session = Depends(get_db), identity: UserIdentity = Depends(require_permission("owner_impersonation"))):
    owner = identity.shop
    if identity.user_type != 'owner':
        raise HTTPException(status_code=403, detail="Only owners can switch to staff accounts")

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.shop_id == owner.id
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
        
    if not member.is_active or member.status == 'disabled':
        raise HTTPException(status_code=403, detail="Cannot switch to a disabled account")

    # Generate token
    from ..auth import create_access_token
    access_token = create_access_token(data={
        "sub": f"tm_{member.id}",
        "shop_id": member.shop_id,
        "team_member_id": member.id,
        "user_type": "team_member"
    })
    
    LoggerService.log(
        db, owner.id, identity, "Login / Logout", 
        f"Owner impersonated staff: {member.name}",
        target=member.email
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
