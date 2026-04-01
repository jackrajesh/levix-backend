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

def send_otp_email(to_email: str, otp: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", "noreply@levix.com")
    
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        print(f"SMTP not fully configured. Mock sending OTP {otp} to {to_email}")
        return

    msg = EmailMessage()
    msg.set_content(f"Your password reset OTP is: {otp}\nIt will expire in 10 minutes.")
    msg['Subject'] = 'Levix Password Reset'
    msg['From'] = smtp_from
    msg['To'] = to_email

    try:
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")

@router.post("/register", response_model=schemas.ShopResponse)
def register_shop(shop: schemas.ShopCreate, db: Session = Depends(get_db)):
    db_shop = db.query(models.Shop).filter(models.Shop.email == shop.email).first()
    if db_shop:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = auth.hash_password(shop.password)
    new_shop = models.Shop(
        shop_name=shop.shop_name,
        owner_name=shop.owner_name,
        email=shop.email,
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
    otp_hash = auth.hash_password(otp)
    
    expires_at = now + timedelta(minutes=10)
    
    new_token = models.PasswordResetToken(
        shop_id=shop.id,
        otp_hash=otp_hash,
        expires_at=expires_at
    )
    db.add(new_token)
    db.commit()
    
    background_tasks.add_task(send_otp_email, shop.email, otp)
    
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
        
    if not auth.verify_password(req.otp, token.otp_hash):
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
