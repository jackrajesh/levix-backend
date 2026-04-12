import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import smtplib
from email.message import EmailMessage
import secrets

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

async def get_current_shop(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth.jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = schemas.TokenData(email=email)
    except auth.JWTError:
        raise credentials_exception
    
    shop = db.query(models.Shop).filter(models.Shop.email == token_data.email).first()
    if shop is None:
        raise credentials_exception
        
    # For local testing/webhook visibility: record this shop as "active"
    try:
        with open(".active_shop_id", "w") as f:
            f.write(str(shop.id))
    except:
        pass
    return shop

import urllib.request
import json

def send_email_otp(email: str, otp: str):
    resend_key = os.getenv("RESEND_API_KEY")
    if not resend_key:
        print(f"Error: RESEND_API_KEY not set. Mock sending OTP {otp} to {email}")
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
                    <p>This OTP is valid for 5 minutes.</p>
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
            print(f"OTP email sent successfully via Resend to {email}")
    except Exception as e:
        error_details = e.read().decode() if hasattr(e, 'read') else str(e)
        print(f"Failed to send email OTP via Resend: {error_details}")

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
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    shop = db.query(models.Shop).filter(models.Shop.email == form_data.username).first()
    if not shop or not auth.verify_password(form_data.password, shop.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = auth.create_access_token(
        data={"sub": shop.email, "shop_id": shop.id}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=schemas.MeResponse)
def get_current_user_info(current_shop: models.Shop = Depends(get_current_shop)):
    return {"shop_id": current_shop.id, "shop_name": current_shop.shop_name}

@router.post("/forgot-password")
def forgot_password(req: schemas.ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    response_msg = {"status": "success", "message": "If that email is registered, you will receive an OTP shortly."}
    
    shop = db.query(models.Shop).filter(models.Shop.email == req.email).first()
    if not shop:
        return response_msg
        
    now = datetime.now(timezone.utc)
    recent_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.shop_id == shop.id,
        models.PasswordResetToken.created_at >= now - timedelta(minutes=1)
    ).first()
    
    if recent_token:
        return response_msg

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

@router.patch("/shop/name")
def update_shop_name(req: schemas.ShopNameUpdate, current_shop: models.Shop = Depends(get_current_shop), db: Session = Depends(get_db)):
    new_name = req.shop_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Shop name cannot be empty")
    
    if len(new_name) < 2 or len(new_name) > 50:
        raise HTTPException(status_code=400, detail="Shop name must be between 2 and 50 characters")
    
    current_shop.shop_name = new_name
    db.commit()
    db.refresh(current_shop)
    return {"status": "success", "shop_name": current_shop.shop_name}
