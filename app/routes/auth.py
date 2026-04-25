import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import smtplib
from email.message import EmailMessage
import secrets

from .. import models, schemas, auth
from ..database import get_db
from ..services.logger import LoggerService
from ..permissions import normalize_permissions, normalize_permission_key

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

from fastapi import Query
from typing import Optional
from ..auth import UserIdentity

async def get_current_shop(token: Optional[str] = Depends(oauth2_scheme), token_query: Optional[str] = Query(None, alias="token"), db: Session = Depends(get_db)):
    actual_token = token or token_query
    if not actual_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth.jwt.decode(actual_token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        team_member_id: int = payload.get("team_member_id")
        if email is None:
            raise credentials_exception
    except auth.JWTError:
        raise credentials_exception

    # ── Team Member login path
    if team_member_id:
        member = db.query(models.TeamMember).filter(models.TeamMember.id == team_member_id).first()
        if not member or not member.is_active or member.status == 'disabled':
            raise HTTPException(status_code=403, detail="Account is disabled. Contact your shop owner.")
        shop = db.query(models.Shop).filter(models.Shop.id == member.shop_id).first()
        if shop is None:
            raise credentials_exception
        return UserIdentity(
            shop=shop,
            user_type='team_member',
            user_id=member.id,
            name=member.name,
            role=member.role,
            permissions=normalize_permissions(member.permissions)
        )

    # ── Owner login path
    shop = db.query(models.Shop).filter(models.Shop.email == email).first()
    if shop is None:
        raise credentials_exception
    return UserIdentity(
        shop=shop,
        user_type='owner',
        user_id=shop.id,
        name=shop.owner_name,
        role="Owner",
        permissions=["*"]
    )

def require_permission(permission: str):
    def dependency(identity: UserIdentity = Depends(get_current_shop)):
        canonical_permission = normalize_permission_key(permission)
        if not identity.has_permission(canonical_permission):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return identity
    return dependency

@router.get("/me", response_model=schemas.MeResponse)
def get_current_user_info(
    identity: UserIdentity = Depends(get_current_shop)
):
    print(f"[AUTH] Fetching info for {identity.name} (Shop: {identity.shop.shop_name})")
    try:
        data = {
            "shop_id": identity.shop.id,
            "shop_name": identity.shop.shop_name,
            "role": identity.role,
            "user_name": identity.name,
            "user_type": identity.user_type,
            "is_team_member": identity.user_type == 'team_member',
            "permissions": identity.permissions
        }
        print(f"[AUTH] Identity confirmed for {identity.name}")
        return data
    except Exception as e:
        print(f"[AUTH] Error in /me endpoint: {e}")
        raise

import urllib.request
import json

from dotenv import load_dotenv

def send_email_otp(email: str, otp: str):
    # Ensure env variables are explicitly loaded in this context to avoid import sequence bugs
    load_dotenv()
    
    resend_key = os.getenv("RESEND_API_KEY")

    if not resend_key:
        print(f"[AUTH LOG] Error: RESEND_API_KEY not set in environment. Mock sending OTP {otp} to {email}")
        return

    html_content = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f5f5f5;
                margin: 0;
                padding: 0;
            }}
            .email-container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background-color: #000000;
                color: #ffffff;
                text-align: center;
                padding: 30px 20px;
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                letter-spacing: 2px;
                font-weight: bold;
            }}
            .header p {{
                margin: 5px 0 0 0;
                font-size: 14px;
                opacity: 0.9;
            }}
            .content {{
                padding: 30px 40px;
                color: #333333;
                text-align: left;
            }}
            .content h2 {{
                font-size: 20px;
                font-weight: normal;
                margin-top: 0;
            }}
            .content p {{
                font-size: 16px;
                line-height: 1.5;
                margin-bottom: 20px;
            }}
            .otp-box {{
                background-color: #f5f5f5;
                border: 2px dashed #3b82f6;
                padding: 20px;
                margin: 30px 0;
                border-radius: 8px;
                text-align: center;
            }}
            .otp-number {{
                font-size: 32px;
                font-weight: bold;
                color: #3b82f6;
                letter-spacing: 6px;
                margin: 0;
            }}
            .security-note {{
                font-size: 14px;
                color: #666666;
                margin-top: 30px;
                text-align: center;
            }}
            .security-note p {{
                margin: 5px 0;
            }}
            .footer {{
                background-color: #f5f5f5;
                text-align: center;
                padding: 20px;
                font-size: 13px;
                color: #888888;
                border-top: 1px solid #eeeeee;
            }}
            .footer p {{
                margin: 5px 0;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <h1>LEVI<span style="color: #3b82f6;">X</span></h1>
                <p>Intelligent Store Management</p>
            </div>
            
            <div class="content">
                <h2>Hello,</h2>
                <p>Use the following OTP to continue your verification.</p>
                
                <div class="otp-box">
                    <p class="otp-number">{otp}</p>
                </div>
                
                <div class="security-note">
                    <p>This OTP is valid for 10 minutes.</p>
                    <p>Never share this OTP with anyone.</p>
                </div>
            </div>
            
            <div class="footer">
                <p><strong>Powered by Levix</strong></p>
                <p>Helping businesses automate smarter.</p>
            </div>
        </div>
    </body>
    </html>
    """

    data = {
        "from": "Levix <support@levixapp.in>",
        "to": [email],
        "subject": "Levix OTP Verification",
        "html": html_content
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resend_key}",
            "Content-Type": "application/json",
            "User-Agent": "Levix-Backend/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            print(f"[AUTH LOG] OTP email sent successfully via RESEND API to {email}")
    except urllib.error.HTTPError as e:
        error_details = e.read().decode()
        print(f"[AUTH LOG] ERROR: Failed to send email OTP via Resend API to {email}. Status: {e.code}, Response: {error_details}")
    except Exception as e:
        print(f"[AUTH LOG] ERROR: Network or API failure sending OTP via Resend to {email}: {e}")

@router.post("/resend-otp")
def resend_otp(req: schemas.ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    print(f"[AUTH LOG] Resend OTP requested for: {req.email}")
    response_msg = {"status": "success", "message": "If that email is registered, you will receive a new OTP shortly."}
    
    shop = db.query(models.Shop).filter(models.Shop.email == req.email).first()
    if not shop:
        return response_msg
        
    now = datetime.now(timezone.utc)
    
    # Check for 5-minute spam shield (more than 3 requests in 5 minutes)
    five_min_ago = now - timedelta(minutes=5)
    request_count = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.created_at >= five_min_ago
    ).count()
    
    if request_count >= 3:
        raise HTTPException(
            status_code=429, 
            detail="Too many requests. Please wait 5 minutes before requesting another OTP."
        )

    # Check for 30-second cooldown
    thirty_sec_ago = now - timedelta(seconds=30)
    recent_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.created_at >= thirty_sec_ago
    ).first()
    
    if recent_token:
        raise HTTPException(
            status_code=429,
            detail="Please wait 30 seconds before requesting another OTP."
        )

    # Invalidate old unused tokens
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.used == False
    ).update({"used": True})
    
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = auth.hash_otp(otp)
    
    expires_at = now + timedelta(minutes=10)
    
    new_token = models.PasswordResetToken(
        shop_id=shop.id,
        otp_hash=otp_hash,
        expires_at=expires_at
    )
    db.add(new_token)
    db.commit()
    
    background_tasks.add_task(send_email_otp, shop.email, otp)
    
    return response_msg

@router.post("/register", response_model=schemas.ShopResponse)
def register_shop(shop: schemas.ShopCreate, db: Session = Depends(get_db)):
    db_shop_email = db.query(models.Shop).filter(models.Shop.email == shop.email).first()
    if db_shop_email:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    db_shop_phone = db.query(models.Shop).filter(models.Shop.phone_number == shop.phone_number).first()
    if db_shop_phone:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    
    hashed_password = auth.hash_password(shop.password)
    new_shop = models.Shop(
        shop_name=shop.shop_name,
        owner_name=shop.owner_name,
        email=shop.email,
        phone_number=shop.phone_number,
        password_hash=hashed_password
    )
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)
    return new_shop

@router.post("/login", response_model=schemas.Token)
def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form_data.username.strip().lower()
    password = form_data.password
    ip = request.client.host if request.client else "unknown"

    # ── 1. Try owner (Shop) login first
    shop = db.query(models.Shop).filter(models.Shop.email == email).first()
    if shop and auth.verify_password(password, shop.password_hash):
        access_token = auth.create_access_token(data={
            "sub": shop.email,
            "shop_id": shop.id,
            "user_type": "owner"
        })
        
        # Log successful owner login
        identity = UserIdentity(shop, "owner", shop.id, shop.owner_name, "Owner", ["*"])
        LoggerService.log(
            db, shop.id, identity, "Login / Logout", 
            "Shop owner logged in",
            ip=ip,
            action_type="login",
            entity_type="user",
            entity_name=shop.owner_name,
            metadata={"ip": ip, "browser": request.headers.get("user-agent")},
        )
        
        return {"access_token": access_token, "token_type": "bearer"}

    # ── 2. Try team member login
    member = db.query(models.TeamMember).filter(models.TeamMember.email == email).first()
    if member and auth.verify_password(password, member.password_hash):
        if not member.is_active or member.status == 'disabled':
            raise HTTPException(
                status_code=403,
                detail="This account has been disabled. Please contact your shop owner."
            )
        
        shop = db.query(models.Shop).filter(models.Shop.id == member.shop_id).first()
        
        # Update last_login timestamp
        from datetime import datetime, timezone
        member.last_login = datetime.now(timezone.utc)
        db.commit()

        access_token = auth.create_access_token(data={
            "sub": f"tm_{member.id}",
            "shop_id": member.shop_id,
            "team_member_id": member.id,
            "user_type": "team_member"
        })
        
        # Log successful member login
        identity = UserIdentity(shop, "team_member", member.id, member.name, member.role, normalize_permissions(member.permissions))
        LoggerService.log(
            db, shop.id, identity, "Login / Logout", 
            f"Staff member logged in: {member.name}",
            ip=ip,
            action_type="login",
            entity_type="user",
            entity_name=member.name,
            metadata={"ip": ip, "browser": request.headers.get("user-agent")},
        )
        
        return {"access_token": access_token, "token_type": "bearer"}

    # ── 3. Both failed
    # We can't log to ActivityLog easily here because we don't have a verified shop_id context safely 
    # (or we could try using the shop we found, but if email is wrong we don't have it).
    # For security, we log failed attempts silently in backend logs or a special system log if needed.
    
    raise HTTPException(
        status_code=401,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/forgot-password")
def forgot_password(req: schemas.ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    print(f"[AUTH LOG] Forgot password requested for: {req.email}")
    response_msg = {"status": "success", "message": "If that email is registered, you will receive an OTP shortly."}
    
    shop = db.query(models.Shop).filter(models.Shop.email == req.email).first()
    if not shop:
        print(f"[AUTH LOG] Shop not found for email: {req.email}. Silently ignoring to prevent enumeration.")
        return response_msg
        
    now = datetime.now(timezone.utc)
    
    # Check for 5-minute spam shield (more than 3 requests in 5 minutes)
    five_min_ago = now - timedelta(minutes=5)
    request_count = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.created_at >= five_min_ago
    ).count()
    
    if request_count >= 3:
        print(f"[AUTH LOG] Blocked {req.email}: Too many requests in 5 mins.")
        raise HTTPException(
            status_code=429, 
            detail="Too many requests. Please wait 5 minutes before trying again."
        )

    # Check for 30-second cooldown
    thirty_sec_ago = now - timedelta(seconds=30)
    recent_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.created_at >= thirty_sec_ago
    ).first()
    
    if recent_token:
        print(f"[AUTH LOG] Rate limit hit for {req.email}: OTP requested < 30 sec ago.")
        raise HTTPException(
            status_code=429,
            detail="Please wait 30 seconds before requesting another OTP."
        )

    print(f"[AUTH LOG] Generating new OTP for {req.email}...")
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.used == False
    ).update({"used": True})
    
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = auth.hash_otp(otp)
    
    expires_at = now + timedelta(minutes=10)
    
    new_token = models.PasswordResetToken(
        shop_id=shop.id,
        otp_hash=otp_hash,
        expires_at=expires_at
    )
    db.add(new_token)
    db.commit()
    
    print(f"[AUTH LOG] Enqueueing background task to send OTP...")
    background_tasks.add_task(send_email_otp, shop.email, otp)
    
    return response_msg

@router.post("/reset-password")
def reset_password(req: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    shop = db.query(models.Shop).filter(models.Shop.email == req.email).first()
    if not shop:
        raise HTTPException(status_code=400, detail="Invalid request")
        
    now = datetime.now(timezone.utc)
    
    token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.used == False
    ).order_by(models.PasswordResetToken.created_at.desc()).first()
    
    if not token:
        raise HTTPException(status_code=400, detail="No active reset request found. Please request a new OTP.")
        
    if token.expires_at < now:
        token.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")
        
    if token.attempt_count >= 5:
        token.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Maximum verification attempts reached. Please request a new OTP.")
        
    if not auth.verify_otp(req.otp, token.otp_hash):
        token.attempt_count += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    shop.password_hash = auth.hash_password(req.new_password)
    token.used = True
    db.commit()
    
    return {"status": "success", "message": "Password successfully reset"}

