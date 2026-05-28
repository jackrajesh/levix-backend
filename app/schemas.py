from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import datetime, date
from typing import Optional, Union

class ShopBase(BaseModel):
    shop_name: str
    owner_name: str
    email: EmailStr
    phone_number: Optional[str] = None

class ShopCreate(ShopBase):
    password: str
    phone_number: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{10}$", description="10-digit phone number")

# password_hash is deliberately omitted to prevent leaking credentials
class ShopResponse(ShopBase):
    id: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    shop_id: Optional[str] = None

class MeResponse(BaseModel):
    shop_id: str
    shop_name: Optional[str] = None
    shop_category: Optional[str] = "General / Other"
    role: Optional[str] = "owner"
    user_name: Optional[str] = None
    user_type: Optional[str] = "owner"
    is_team_member: Optional[bool] = False
    permissions: Optional[list] = []

class ShopCategoryUpdate(BaseModel):
    shop_category: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


class InventoryItemBase(BaseModel):
    name: str
    quantity: int = 0
    price: float = 0
    barcode: Optional[str] = None

class InventoryItemCreate(InventoryItemBase):
    category: Optional[str] = None

class InventoryItemResponse(InventoryItemBase):
    id: str
    shop_id: str
    category: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class LogEntryResponse(BaseModel):
    id: str
    shop_id: str
    product_name: str
    product_id: Optional[str] = None
    status: str
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)

class PendingRequestResponse(BaseModel):
    id: str
    shop_id: str
    product_name: str
    product_id: Optional[str] = None
    customer_message: Optional[str] = None
    request_type: str = "customer"
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class SalesRecordBase(BaseModel):
    product_id: Optional[str] = None
    date: date
    quantity: int

class SalesRecordResponse(SalesRecordBase):
    id: str
    shop_id: str
    product_name: str = "" # Injected by the API later usually
    
    model_config = ConfigDict(from_attributes=True)

# --- API Request Models ---

class StatusUpdate(BaseModel):
    status: str

class EditItem(BaseModel):
    name: str
    quantity: int
    price: float = 0
    barcode: Optional[str] = None
    category: Optional[str] = None

class QuantityUpdate(BaseModel):
    amount: int

class SalesSetRequest(BaseModel):
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    date: str
    quantity: int
    price: Optional[float] = None

class ShopNameUpdate(BaseModel):
    shop_name: str

class BulkDeleteRequest(BaseModel):
    order_ids: list[str]


# --- WhatsApp Admin ---

class ConnectWhatsAppRequest(BaseModel):
    shop_id: Optional[str] = None
    phone_number_id: str
    access_token: str
    business_account_id: Optional[str] = None

class OrderResponse(BaseModel):
    id: str
    shop_id: str
    booking_id: str
    order_id: str
    customer_name: str
    phone: str
    address: str
    product: Optional[str] = None
    quantity: Optional[int] = 1
    unit_price: Optional[float] = 0.0
    total_amount: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


