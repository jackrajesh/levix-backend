from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Numeric, Text, JSON, Float
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

    # Phase 4: Pilot Settings
    settings = Column(JSON, nullable=True, default=dict)

    reset_tokens = relationship("PasswordResetToken", back_populates="shop", cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="shop", cascade="all, delete-orphan")
    logs = relationship("LogEntry", back_populates="shop", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="shop", cascade="all, delete-orphan")
    pending_requests = relationship("PendingRequest", back_populates="shop", cascade="all, delete-orphan")
    sales = relationship("SalesRecord", back_populates="shop", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="shop", cascade="all, delete-orphan")
    
    # SaaS features
    subscription = relationship("Subscription", back_populates="shop", uselist=False, cascade="all, delete-orphan")
    team_members = relationship("TeamMember", back_populates="shop", cascade="all, delete-orphan")
    billing_history = relationship("BillingHistory", back_populates="shop", cascade="all, delete-orphan")
    activated_addons = relationship("ShopAddon", back_populates="shop", cascade="all, delete-orphan")

    # AI Assistant features
    ai_leads = relationship("AILead", back_populates="shop", cascade="all, delete-orphan")
    ai_sessions = relationship("AIConversationSession", back_populates="shop", cascade="all, delete-orphan")
    ai_analytics = relationship("AIAnalyticsEvent", back_populates="shop", cascade="all, delete-orphan")

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
    # AI Assistant fields
    product_details = Column(Text, nullable=True)  # Human-readable AI context (sizes, variants, delivery info)
    category = Column(String, nullable=True)        # footwear | food | service | apparel | custom | general
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
    performed_by = Column(String, nullable=True)
    user_type = Column(String, nullable=True)
    
    shop = relationship("Shop", back_populates="logs")

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    user_id = Column(Integer, nullable=True) # ID of team member or owner
    user_name = Column(String, nullable=True)
    role = Column(String, nullable=True)
    category = Column(String, nullable=False, index=True) # Sales, Orders, Inventory, etc.
    action = Column(String, nullable=False) # "New sale recorded", "Qty reduced", etc.
    target = Column(String, nullable=True) # Product name, Order ID, etc.
    action_type = Column(String, nullable=True, index=True)  # inventory_edit, login, delete, etc.
    entity_type = Column(String, nullable=True)  # product, user, order, etc.
    entity_name = Column(String, nullable=True)  # Human-readable entity label
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    actor_name = Column(String, nullable=True)
    severity = Column(String, default="info") # info, warning, critical
    log_metadata = Column("metadata", JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    shop = relationship("Shop", back_populates="activity_logs")

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
    performed_by = Column(String, nullable=True)
    user_type = Column(String, nullable=True)
    
    shop = relationship("Shop", back_populates="sales")
    inventory_item = relationship("InventoryItem", back_populates="sales")

class CustomerSession(Base):
    __tablename__ = "customer_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    customer_phone = Column(String(20), index=True, nullable=False)
    is_ordering = Column(Boolean, default=False)
    can_order = Column(Boolean, default=False)
    step = Column(String, nullable=True) # "name", "phone", "address", "confirm"
    session_data = Column(String, nullable=True) # JSON string of name, phone, address, product
    booking_id = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class CustomerProfile(Base):
    """Phase 1: Long Term Persistent Customer Memory."""
    __tablename__ = "customer_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    customer_phone = Column(String(20), index=True, nullable=False)
    customer_name = Column(String, nullable=True)
    
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    
    visit_count = Column(Integer, default=1)
    message_count = Column(Integer, default=1)
    total_orders = Column(Integer, default=0)
    total_leads = Column(Integer, default=0)
    
    favorite_products = Column(JSON, nullable=True, default=dict)
    favorite_categories = Column(JSON, nullable=True, default=dict)
    
    avg_budget = Column(Float, nullable=True)
    max_budget = Column(Float, nullable=True)
    preferred_spice_level = Column(String, nullable=True)
    veg_preference = Column(String, nullable=True)
    usual_people_count = Column(Integer, nullable=True)
    
    last_order_summary = Column(Text, nullable=True)
    last_order_at = Column(DateTime(timezone=True), nullable=True)
    last_5_orders = Column(JSON, nullable=True, default=list)
    
    conversion_score = Column(Integer, default=0) # 0-100
    vip_tier = Column(String, default="NEW") # NEW, REGULAR, VIP
    notes = Column(JSON, nullable=True, default=dict)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    booking_id = Column(String, unique=True, index=True, nullable=False)
    order_id = Column(String, unique=True, index=True, nullable=False)
    customer_name = Column(String, nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(String, nullable=False)
    product = Column(String, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), default=0, nullable=False)
    total_amount = Column(Numeric(10, 2), default=0, nullable=False)
    status = Column(String, default="pending", index=True) # "pending", "accepted", "rejected", "completed"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    shop = relationship("Shop", back_populates="orders")

class OrderLog(Base):
    __tablename__ = "order_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    order_id = Column(String, index=True, nullable=False)
    action = Column(String, nullable=False) # order_created, order_accepted, etc.
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    performed_by = Column(String, nullable=True)
    user_type = Column(String, nullable=True)

# --- NEW SAAS MODELS ---

class Plan(Base):
    __tablename__ = "plans"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # e.g., "Core Levix", "All Access Bundle"
    price = Column(Numeric(10, 2), nullable=False)
    interval = Column(String, default="monthly") # monthly, yearly
    features = Column(JSON, nullable=True) # List of features for display
    limits = Column(JSON, nullable=True) # { "messages": 1000, "staff": 1 }
    is_active = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)

class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), unique=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    status = Column(String, default="active") # active, expired, cancelled
    start_date = Column(DateTime(timezone=True), server_default=func.now())
    renewal_date = Column(DateTime(timezone=True))
    razorpay_subscription_id = Column(String, nullable=True)
    
    shop = relationship("Shop", back_populates="subscription")
    plan = relationship("Plan")

class Addon(Base):
    __tablename__ = "addons"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # e.g., "Smart AI", "Analytics Pro", "Team Access"
    price = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    features = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)

class ShopAddon(Base):
    __tablename__ = "shop_addons"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    addon_id = Column(Integer, ForeignKey("addons.id"), nullable=False)
    activated_at = Column(DateTime(timezone=True), server_default=func.now())
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    
    shop = relationship("Shop", back_populates="activated_addons")
    addon = relationship("Addon")

class ShopRole(Base):
    """Custom roles defined per-shop. Roles are not shared across shops."""
    __tablename__ = "shop_roles"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Cashier", "Inventory Editor"
    permissions = Column(JSON, nullable=True)  # List of permission keys granted
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TeamMember(Base):
    __tablename__ = "team_members"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="Staff")  # Free-text custom role name (per shop)
    permissions = Column(JSON, nullable=True)  # List of permission keys: ["inbox", "orders_view", ...]
    is_active = Column(Boolean, default=True)
    status = Column(String, default="active")  # active, disabled
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="team_members")

class BillingHistory(Base):
    __tablename__ = "billing_history"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    plan_name = Column(String, nullable=False)
    status = Column(String, default="paid") # paid, failed, pending
    invoice_id = Column(String, unique=True, nullable=True)
    payment_id = Column(String, nullable=True) # Razorpay payment ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="billing_history")


# ─────────────────────────────────────────────────────────────────────────────
# AI ASSISTANT MODELS
# ─────────────────────────────────────────────────────────────────────────────

class AIConversationSession(Base):
    """Persists multi-turn conversation state for the AI assistant."""
    __tablename__ = "ai_conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    session_id = Column(String, unique=True, index=True, nullable=False)
    customer_phone = Column(String(20), index=True, nullable=True)
    # What the AI has gathered so far
    collected_fields = Column(JSON, nullable=True, default=dict)
    matched_product_id = Column(Integer, nullable=True)
    matched_product_name = Column(String, nullable=True)
    last_intent = Column(String, nullable=True)
    intent_confidence = Column(Numeric(4, 2), nullable=True)
    category = Column(String, nullable=True)
    missing_fields = Column(JSON, nullable=True, default=list)
    turn_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    lead_created = Column(Boolean, default=False)
    source = Column(String, default="web")  # web | whatsapp
    conversation_history = Column(JSON, nullable=True, default=list)  # [{role, content}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    shop = relationship("Shop", back_populates="ai_sessions")


class AILead(Base):
    """Structured lead created by the AI assistant when intent + fields are ready."""
    __tablename__ = "ai_leads_v3"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    customer_name = Column(String, nullable=True)
    phone = Column(String(20), nullable=True)
    product_id = Column(Integer, nullable=True)
    product_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    intent = Column(String, nullable=True)
    collected_data = Column(JSON, nullable=True)   # All collected fields
    summary = Column(Text, nullable=True)           # Human-readable summary for owner
    status = Column(String, default="new", index=True)  # new | accepted | rejected | info_requested
    source = Column(String, default="AI Assistant")
    confidence = Column(Numeric(4, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    shop = relationship("Shop", back_populates="ai_leads")


class AIAnalyticsEvent(Base) :
    """Tracks AI funnel events: chat_started, lead_created, conversion, abandoned, etc."""
    __tablename__ = "ai_analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    event_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    shop = relationship("Shop", back_populates="ai_analytics")


class MissingProductRequest(Base):
    """Tracks repeated missing product requests for Demand Intelligence."""
    __tablename__ = "missing_product_requests"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False, index=True)
    customer_phone = Column(String(20), nullable=True)
    count = Column(Integer, default=1)
    last_requested_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
