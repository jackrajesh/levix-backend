import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt

# =========================
# CONFIG
# =========================
SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-key-for-local-dev-only")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Support both bcrypt (new) and argon2 (old users)
pwd_context = CryptContext(
    schemes=["bcrypt", "argon2"],
    deprecated="auto"
)

# =========================
# PASSWORD HELPERS
# =========================
def _clean_password(password: str) -> str:
    """
    Clean and safely truncate password for bcrypt (max 72 bytes)
    """
    if not password:
        raise ValueError("Password cannot be empty")

    # remove spaces + hidden chars
    password = password.strip()

    # encode → truncate → decode safely
    password_bytes = password.encode("utf-8")[:72]
    return password_bytes.decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    cleaned = _clean_password(password)
    return pwd_context.hash(cleaned)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        cleaned = _clean_password(plain_password)
        return pwd_context.verify(cleaned, hashed_password)
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