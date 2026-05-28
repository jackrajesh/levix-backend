import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
import hashlib
from .permissions import has_effective_permission, normalize_permissions

# =========================
# CONFIG
# =========================
SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-key-for-local-dev-only")
if SECRET_KEY == "super-secret-key-for-local-dev-only":
    print("[AUTH WARNING] JWT_SECRET is using the default insecure development key. "
          "Set JWT_SECRET in your environment for production!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Use argon2 for all hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

class UserIdentity:
    def __init__(self, shop: Any, user_type: str, user_id: Any, name: str, role: str, permissions: List[str]):
        self.shop = shop  # Shop model instance
        self.user_type = user_type # 'owner' or 'team_member'
        self.user_id = user_id
        self.name = name
        self.role = role
        self.permissions = normalize_permissions(permissions or [])
        self.subscription_status = getattr(shop.subscription, 'status', 'active') if shop.subscription else 'active'
        self.renewal_date = getattr(shop.subscription, 'renewal_date', None) if shop.subscription else None
    
    @property
    def id(self):
        return self.shop.id
    
    @property
    def shop_name(self):
        return self.shop.shop_name

    def has_permission(self, permission: str) -> bool:
        if self.user_type == 'owner':
            return True
        return has_effective_permission(self.permissions, permission)

    @property
    def is_subscription_active(self) -> bool:
        """Checks if the shop has an active subscription.
        By default, we assume active if no subscription record exists (legacy or trial grace).
        """
        if self.subscription_status in ['active', 'trial']:
            return True
        
        # Check renewal date if status is 'active' but date passed
        if self.renewal_date and self.renewal_date < datetime.now(timezone.utc):
            return False
            
        return self.subscription_status == 'active'

    @property
    def is_smart_ai_active(self) -> bool:
        """Checks if the shop has an active 'Smart AI' add-on."""
        if not self.shop.activated_addons:
            return False
        
        now = datetime.now(timezone.utc)
        for shop_addon in self.shop.activated_addons:
            # Check if the addon name matches and hasn't expired
            if shop_addon.addon and shop_addon.addon.name == "Smart AI":
                if shop_addon.expiry_date and shop_addon.expiry_date < now:
                    continue
                return True
        return False

# =========================
# PASSWORD HELPERS
# =========================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()

def verify_otp(plain_otp: str, hashed_otp: str) -> bool:
    return hash_otp(plain_otp) == hashed_otp


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False  # prevents crashes


# =========================
# JWT TOKEN
# =========================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)