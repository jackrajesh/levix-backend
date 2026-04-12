from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import datetime, date
from typing import Optional

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
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    shop_id: Optional[int] = None

class MeResponse(BaseModel):
    shop_id: int
    shop_name: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

class InventoryAliasBase(BaseModel):
    alias: str

class InventoryAliasResponse(InventoryAliasBase):
    id: int
    inventory_id: int
    model_config = ConfigDict(from_attributes=True)

class InventoryItemBase(BaseModel):
    name: str
    quantity: int = 0
    price: float = 0
    status: str = "out_of_stock"

class InventoryItemCreate(InventoryItemBase):
    aliases: list[str] = []

class InventoryItemResponse(InventoryItemBase):
    id: int
    shop_id: int
    created_at: datetime
    quantity: int = 0
    stock_warning_active: bool = False
    aliases: list[InventoryAliasResponse] = []
    
    model_config = ConfigDict(from_attributes=True)

class LogEntryResponse(BaseModel):
    id: int
    shop_id: int
    product_name: str
    product_id: Optional[int] = None
    status: str
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)

class PendingRequestResponse(BaseModel):
    id: int
    shop_id: int
    product_name: str
    product_id: Optional[int] = None
    customer_message: Optional[str] = None
    request_type: str = "customer"
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class SalesRecordBase(BaseModel):
    product_id: int
    date: date
    quantity: int

class SalesRecordResponse(SalesRecordBase):
    id: int
    shop_id: int
    product_name: str = "" # Injected by the API later usually
    
    model_config = ConfigDict(from_attributes=True)

# --- API Request Models ---

class StatusUpdate(BaseModel):
    status: str

class EditItem(BaseModel):
    name: str
    aliases: list[str]
    quantity: int
    price: float = 0

class QuantityUpdate(BaseModel):
    amount: int

class SalesSetRequest(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    date: str
    quantity: int
    price: Optional[float] = None

class ShopNameUpdate(BaseModel):
    shop_name: str

class BulkDeleteRequest(BaseModel):
    ids: list[int]


# --- WhatsApp Admin ---

class ConnectWhatsAppRequest(BaseModel):
    shop_id: int
    phone_number_id: str
    access_token: str
    business_account_id: Optional[str] = None
