import uuid
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Numeric, Text, JSON, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class Shop(Base):
    __tablename__ = "shops"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
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

    # Phase 5: Universal Retail Settings
    business_category = Column(String, nullable=True)
    business_subnote = Column(Text, nullable=True)
    shop_category = Column(String(50), nullable=True, default="General")

    # Approval / Lifecycle fields (Phase: Production Readiness)
    # Values: 'pending' | 'approved' | 'rejected' | 'banned' | 'trial'
    approval_status = Column(String(20), nullable=False, default="pending", index=True)
    rejection_reason = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(String, nullable=True)   # admin email who approved
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # soft delete timestamp

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
    ai_usage = relationship("AIUsage", back_populates="shop", cascade="all, delete-orphan")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False)
    otp_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    attempt_count = Column(Integer, default=0)
    
    shop = relationship("Shop", back_populates="reset_tokens")

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    barcode = Column(String, nullable=True, index=True)
    category = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (UniqueConstraint('shop_id', 'barcode', name='_shop_barcode_uc'),)

    shop = relationship("Shop", back_populates="inventory")
    sales = relationship("SalesRecord", back_populates="inventory_item")

class Product(Base):
    __tablename__ = "products"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    status = Column(String, default="available")
    category = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    

class LogEntry(Base):
    __tablename__ = "log_entries"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False)
    product_id = Column(String, nullable=True)
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
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    user_id = Column(String, nullable=True) # ID of team member or owner
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
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False)
    product_id = Column(String, ForeignKey("inventory_items.id"), nullable=True)
    customer_message = Column(String, nullable=True)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String(20), nullable=True)
    request_type = Column(String, default="customer") # 'customer' or 'oos_warning'
    category_context = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="pending_requests")

class ConversationCategory(Base):
    __tablename__ = "conversation_categories"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True, default="#3b82f6")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop")

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    inquiry_number = Column(String, index=True, unique=True, nullable=True)
    customer_phone = Column(String(20), index=True, nullable=False)
    customer_name = Column(String, nullable=True)
    status = Column(String, default="NEW", index=True) # NEW, ONGOING, WAITING_CUSTOMER, RESOLVED, ARCHIVED
    category_id = Column(String, ForeignKey("conversation_categories.id"), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # New Inquiry Lifecycle columns
    inquiry_status = Column(String, default="ACTIVE", index=True) # ACTIVE, PAUSED, WAITING_SUPPORT, WAITING_CUSTOMER, RESOLVED, CANCELLED
    inquiry_context_id = Column(String, nullable=True)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    resumed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Operational Hardening Columns
    conversation_type = Column(String, default="INQUIRY", index=True) # INQUIRY, ORDER
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    shop = relationship("Shop")
    category = relationship("ConversationCategory")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan", order_by="ConversationMessage.timestamp")

    @classmethod
    def generate_unique_number(cls, db_session):
        import random
        while True:
            num = random.randint(10000, 99999)
            inq_num = f"INQ-{num}"
            exists = db_session.query(cls).filter(cls.inquiry_number == inq_num).first()
            if not exists:
                return inq_num

    @classmethod
    def generate_unique_order_number(cls, db_session):
        import random
        while True:
            num = random.randint(10000, 99999)
            ord_num = f"ORD-{num}"
            exists = db_session.query(cls).filter(cls.inquiry_number == ord_num).first()
            if not exists:
                return ord_num

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("conversation_sessions.id"), index=True, nullable=False)
    sender_type = Column(String, nullable=False) # CUSTOMER, OWNER, SYSTEM
    message = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    whatsapp_message_id = Column(String, nullable=True, unique=True)
    
    session = relationship("ConversationSession", back_populates="messages")

class SalesRecord(Base):
    __tablename__ = "sales_records"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    product_id = Column(String, ForeignKey("inventory_items.id"), nullable=True)
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
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
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
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
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
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    customer_id = Column(String, ForeignKey("customer_profiles.id"), nullable=True)
    booking_id = Column(String, unique=True, index=True, nullable=False)
    order_id = Column(String, unique=True, index=True, nullable=False)
    
    customer_name = Column(String, nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(String, nullable=False)
    
    # Legacy flat fields (for simple one-item orders or summary)
    product = Column(String, nullable=True)
    quantity = Column(Integer, default=1, nullable=True)
    unit_price = Column(Numeric(10, 2), default=0, nullable=True)
    
    total_amount = Column(Numeric(10, 2), default=0, nullable=False)
    status = Column(String, default="PENDING", index=True) # "PENDING", "CONFIRMED", "CANCELLED", "DELIVERED"
    delivery_type = Column(String(8), nullable=True) # "delivery" or "pickup"
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    shop = relationship("Shop", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    product_id = Column(String, ForeignKey("inventory_items.id"), nullable=False)
    name = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    subtotal = Column(Numeric(10, 2), nullable=False)
    
    order = relationship("Order", back_populates="items")

class OrderLog(Base):
    __tablename__ = "order_logs"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
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
    shop_id = Column(String, ForeignKey("shops.id"), unique=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    status = Column(String, default="active") # active, expired, cancelled
    start_date = Column(DateTime(timezone=True), server_default=func.now())
    renewal_date = Column(DateTime(timezone=True))
    cashfree_subscription_id = Column(String, nullable=True)
    
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
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False)
    addon_id = Column(Integer, ForeignKey("addons.id"), nullable=False)
    activated_at = Column(DateTime(timezone=True), server_default=func.now())
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    
    shop = relationship("Shop", back_populates="activated_addons")
    addon = relationship("Addon")

class ShopRole(Base):
    """Custom roles defined per-shop. Roles are not shared across shops."""
    __tablename__ = "shop_roles"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Cashier", "Inventory Editor"
    permissions = Column(JSON, nullable=True)  # List of permission keys granted
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TeamMember(Base):
    __tablename__ = "team_members"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False)
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
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    plan_name = Column(String, nullable=False)
    status = Column(String, default="paid") # paid, failed, pending
    invoice_id = Column(String, unique=True, nullable=True)
    payment_id = Column(String, nullable=True) # Cashfree payment ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    shop = relationship("Shop", back_populates="billing_history")


# ─────────────────────────────────────────────────────────────────────────────
# AI ASSISTANT MODELS
# ─────────────────────────────────────────────────────────────────────────────

class AIConversationSession(Base):
    """Persists multi-turn conversation state for the AI assistant."""
    __tablename__ = "ai_conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    session_id = Column(String, unique=True, index=True, nullable=False)
    customer_phone = Column(String(20), index=True, nullable=True)
    # What the AI has gathered so far
    collected_fields = Column(JSON, nullable=True, default=dict)
    matched_product_id = Column(String, nullable=True)
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
    __tablename__ = "ai_leads"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    customer_name = Column(String, nullable=True)
    phone = Column(String(20), nullable=True)
    product_id = Column(String, nullable=True)
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


class AIAnalyticsEvent(Base):
    """Tracks AI funnel events: chat_started, lead_created, conversion, abandoned, etc."""
    __tablename__ = "ai_analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    event_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    shop = relationship("Shop", back_populates="ai_analytics")


class MissingProductRequest(Base):
    """Tracks repeated missing product requests for Demand Intelligence."""
    __tablename__ = "missing_product_requests"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    product_name = Column(String, nullable=False, index=True)
    customer_phone = Column(String(20), nullable=True)
    count = Column(Integer, default=1)
    last_requested_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PendingSSEEvent(Base):
    """Gap 7 fix: Persistent queue for SSE events to ensure delivery upon dashboard reconnection."""
    __tablename__ = "pending_sse_events"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    event_type = Column(String, nullable=False) # e.g. "new_order"
    data = Column(JSON, nullable=False)
    delivered = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

class AdminAlert(Base):
    """Task 2 fix: Tracks repeated failures for shop owners/admins."""
    __tablename__ = "admin_alerts"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    alert_type = Column(String, nullable=False, index=True)  # e.g. 'order_failure_burst'
    failure_count = Column(Integer, default=1)
    details = Column(JSON, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

class AIUsage(Base):
    """Tracks daily AI usage and cooldowns for Smart AI sustainability."""
    __tablename__ = "ai_usage"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.id"), index=True, nullable=False)
    date = Column(Date, server_default=func.current_date(), index=True)
    request_count = Column(Integer, default=0)
    total_spend = Column(Numeric(10, 4), default=0) # Tracks equivalent ₹ spend
    cooldown_until = Column(DateTime(timezone=True), nullable=True)

    shop = relationship("Shop", back_populates="ai_usage")


# ─────────────────────────────────────────────────────────────────────────────
# OBSERVABILITY & FORENSICS MODELS
# ─────────────────────────────────────────────────────────────────────────────

class ConversationEventLog(Base):
    """
    Append-only audit trail for all conversation lifecycle events.
    Never mutated after creation. Used for forensics, replay, and diagnostics.
    """
    __tablename__ = "conversation_event_log"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True, nullable=False, default=lambda: f"evt_{uuid.uuid4().hex[:16]}")
    session_id = Column(String, index=True, nullable=True)       # ConversationSession.id or AIConversationSession.session_id
    flow_id = Column(String, index=True, nullable=True)          # Logical flow identifier
    shop_id = Column(String, index=True, nullable=True)
    customer_phone = Column(String(20), index=True, nullable=True)
    event_type = Column(String, nullable=False, index=True)       # From EventType enum
    previous_state = Column(String, nullable=True)
    next_state = Column(String, nullable=True)
    trigger_source = Column(String, nullable=True)                # "webhook", "command", "system", "ai", "owner", "timer"
    trigger_reason = Column(String, nullable=True)                # Human-readable reason
    message_id = Column(String, nullable=True)                    # WhatsApp message ID
    webhook_id = Column(String, nullable=True)                    # Raw webhook event ID
    actor_type = Column(String, nullable=True)                    # "customer", "owner", "system", "ai", "controller"
    actor_id = Column(String, nullable=True)                      # Phone number or user ID
    recovery_type = Column(String, nullable=True)                 # "checkpoint", "fallback", "auto_recover", null
    checkpoint_id = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)                   # Arbitrary structured data
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class WebhookAuditLog(Base):
    """
    Forensic audit trail for every inbound webhook event.
    Tracks dedup, latency, retries, and processing results.
    """
    __tablename__ = "webhook_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    webhook_event_id = Column(String, unique=True, index=True, nullable=False, default=lambda: f"wh_{uuid.uuid4().hex[:16]}")
    shop_id = Column(String, index=True, nullable=True)
    wa_message_id = Column(String, index=True, nullable=True)     # WhatsApp msg ID for dedup
    sender_phone = Column(String(20), nullable=True)
    phone_number_id = Column(String, nullable=True)               # WhatsApp Phone Number ID
    payload_hash = Column(String, nullable=True)                  # SHA256 of raw body for forensics
    message_type = Column(String, nullable=True)                  # "text", "button", "interactive", "status"
    raw_message_text = Column(String, nullable=True)              # Extracted text (truncated 500 chars)
    is_duplicate = Column(Boolean, default=False, index=True)
    processing_result = Column(String, nullable=True)             # "success", "duplicate", "error", "ignored", "no_shop"
    route_target = Column(String, nullable=True)                  # "router_engine", "guided_engine", etc.
    response_status = Column(String, nullable=True)               # "sent", "send_failed", "no_reply"
    outbound_wa_id = Column(String, nullable=True)                # WA message ID of outbound reply
    retry_count = Column(Integer, default=0)
    processing_latency_ms = Column(Integer, nullable=True)        # End-to-end processing time
    error_summary = Column(String, nullable=True)                 # Truncated error message if failed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

