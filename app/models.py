from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class Shop(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, nullable=False)
    owner_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String(15), unique=True, index=True, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # WhatsApp Cloud API credentials (per-shop, token stored encrypted)
    whatsapp_phone_number_id = Column(String, unique=True, nullable=True, index=True)
    whatsapp_access_token = Column(String, nullable=True)  # stored encrypted via utils/encryption.py
    whatsapp_business_account_id = Column(String, nullable=True)

    reset_tokens = relationship("PasswordResetToken", back_populates="shop", cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="shop", cascade="all, delete-orphan")
    logs = relationship("LogEntry", back_populates="shop", cascade="all, delete-orphan")
    pending_requests = relationship("PendingRequest", back_populates="shop", cascade="all, delete-orphan")
    sales = relationship("SalesRecord", back_populates="shop", cascade="all, delete-orphan")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    otp_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    attempt_count = Column(Integer, default=0)
    
    shop = relationship("Shop", back_populates="reset_tokens")

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    status = Column(String, default="out_of_stock")
    stock_warning_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="inventory")
    aliases = relationship("InventoryAlias", back_populates="inventory_item", cascade="all, delete-orphan")
    sales = relationship("SalesRecord", back_populates="inventory_item")
    
class InventoryAlias(Base):
    __tablename__ = "inventory_aliases"
    
    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False)
    alias = Column(String, index=True, nullable=False)
    
    inventory_item = relationship("InventoryItem", back_populates="aliases")

class LogEntry(Base):
    __tablename__ = "log_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False)
    product_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    is_matched = Column(Boolean, default=True) # New: tracked for analytics
    match_source = Column(String, nullable=True) # New: 'direct', 'fuzzy', 'ai', 'pending'
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="logs")

class PendingRequest(Base):
    __tablename__ = "pending_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False)
    product_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)
    customer_message = Column(String, nullable=True)
    request_type = Column(String, default="customer") # 'customer' or 'oos_warning'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="pending_requests")

class SalesRecord(Base):
    __tablename__ = "sales_records"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)
    product_name = Column(String, nullable=True)
    date = Column(Date, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    
    shop = relationship("Shop", back_populates="sales")
    inventory_item = relationship("InventoryItem", back_populates="sales")
