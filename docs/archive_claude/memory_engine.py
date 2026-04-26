"""
memory_engine.py — LEVIX Session & Customer Memory Layer
Handles per-session state and cross-session customer history via PostgreSQL.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey,
    Integer, Numeric, String, Text, create_engine, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "levix_customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(120))
    default_address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sessions = relationship("ChatSession", back_populates="customer", lazy="dynamic")
    orders = relationship("OrderRecord", back_populates="customer", lazy="dynamic")


class ChatSession(Base):
    __tablename__ = "levix_chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("levix_customers.id"), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    state = Column(String(60), default="idle")           # FSM state
    cart = Column(JSONB, default=list)                   # list of CartItem dicts
    preferences = Column(JSONB, default=dict)            # spice, dietary flags etc.
    delivery_type = Column(String(20))                   # 'delivery' | 'pickup'
    delivery_address = Column(Text)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    active = Column(Boolean, default=True)

    customer = relationship("Customer", back_populates="sessions")


class OrderRecord(Base):
    __tablename__ = "levix_order_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("levix_customers.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("levix_chat_sessions.id"), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    items_snapshot = Column(JSONB, nullable=False)        # cart at time of order
    total_amount = Column(Numeric(10, 2))
    delivery_type = Column(String(20))
    delivery_address = Column(Text)
    status = Column(String(30), default="placed")        # placed|confirmed|delivered|cancelled
    placed_at = Column(DateTime, default=datetime.utcnow)
    idempotency_key = Column(String(120), unique=True)   # prevents duplicate placement

    customer = relationship("Customer", back_populates="orders")


# ---------------------------------------------------------------------------
# Engine factory (call once at startup)
# ---------------------------------------------------------------------------

_db_session_factory: sessionmaker | None = None


def init_db(database_url: str, echo: bool = False) -> None:
    """
    Call at application startup.
    database_url example:
        postgresql+psycopg2://user:pass@localhost:5432/levix_db
    """
    global _db_session_factory
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    _db_session_factory = sessionmaker(bind=engine, expire_on_commit=False)


def _get_db() -> Session:
    if _db_session_factory is None:
        raise RuntimeError("Call init_db() before using MemoryEngine.")
    return _db_session_factory()


# ---------------------------------------------------------------------------
# Session TTL
# ---------------------------------------------------------------------------

SESSION_TTL_MINUTES = 45


# ---------------------------------------------------------------------------
# MemoryEngine
# ---------------------------------------------------------------------------

class MemoryEngine:
    """
    Provides get/set for per-message session state and customer history.
    All methods open/close their own DB sessions (safe for async workers).
    """

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    def get_or_create_customer(self, phone: str, name: str | None = None) -> dict[str, Any]:
        with _get_db() as db:
            customer = db.query(Customer).filter_by(phone=phone).first()
            if not customer:
                customer = Customer(phone=phone, name=name)
                db.add(customer)
                db.commit()
                db.refresh(customer)
            elif name and not customer.name:
                customer.name = name
                db.commit()
            return {
                "id": str(customer.id),
                "phone": customer.phone,
                "name": customer.name,
                "default_address": customer.default_address,
            }

    def update_customer_address(self, phone: str, address: str) -> None:
        with _get_db() as db:
            db.query(Customer).filter_by(phone=phone).update(
                {"default_address": address, "last_active": datetime.utcnow()}
            )
            db.commit()

    def update_customer_name(self, phone: str, name: str) -> None:
        with _get_db() as db:
            db.query(Customer).filter_by(phone=phone).update({"name": name})
            db.commit()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_active_session(self, phone: str) -> dict[str, Any] | None:
        with _get_db() as db:
            session = (
                db.query(ChatSession)
                .filter_by(phone=phone, active=True)
                .filter(ChatSession.expires_at > datetime.utcnow())
                .order_by(ChatSession.last_message_at.desc())
                .first()
            )
            if not session:
                return None
            return self._session_to_dict(session)

    def create_session(self, phone: str, customer_id: str) -> dict[str, Any]:
        with _get_db() as db:
            # Expire old sessions
            db.query(ChatSession).filter_by(phone=phone, active=True).update(
                {"active": False}
            )
            new_session = ChatSession(
                customer_id=customer_id,
                phone=phone,
                state="idle",
                cart=[],
                preferences={},
                expires_at=datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES),
            )
            db.add(new_session)
            db.commit()
            db.refresh(new_session)
            return self._session_to_dict(new_session)

    def save_session(self, session_id: str, updates: dict[str, Any]) -> None:
        """Persist partial session updates."""
        allowed = {
            "state", "cart", "preferences",
            "delivery_type", "delivery_address",
            "last_message_at", "expires_at",
        }
        safe_updates = {k: v for k, v in updates.items() if k in allowed}
        safe_updates["last_message_at"] = datetime.utcnow()
        # Bump TTL on activity
        safe_updates["expires_at"] = datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES)

        with _get_db() as db:
            db.query(ChatSession).filter_by(id=session_id).update(safe_updates)
            db.commit()

    def close_session(self, session_id: str) -> None:
        with _get_db() as db:
            db.query(ChatSession).filter_by(id=session_id).update({"active": False})
            db.commit()

    # ------------------------------------------------------------------
    # Order history
    # ------------------------------------------------------------------

    def get_last_order(self, phone: str) -> dict[str, Any] | None:
        with _get_db() as db:
            order = (
                db.query(OrderRecord)
                .filter_by(phone=phone)
                .filter(OrderRecord.status != "cancelled")
                .order_by(OrderRecord.placed_at.desc())
                .first()
            )
            if not order:
                return None
            return {
                "id": str(order.id),
                "items": order.items_snapshot,
                "total": float(order.total_amount or 0),
                "delivery_type": order.delivery_type,
                "delivery_address": order.delivery_address,
                "placed_at": order.placed_at.isoformat(),
                "status": order.status,
            }

    def record_order(
        self,
        phone: str,
        customer_id: str,
        session_id: str,
        cart: list[dict],
        total: float,
        delivery_type: str,
        delivery_address: str | None,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """
        Persists a new order.  Returns None if idempotency_key already exists
        (duplicate order guard).
        """
        with _get_db() as db:
            existing = db.query(OrderRecord).filter_by(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return None  # duplicate

            order = OrderRecord(
                customer_id=customer_id,
                session_id=session_id,
                phone=phone,
                items_snapshot=cart,
                total_amount=total,
                delivery_type=delivery_type,
                delivery_address=delivery_address,
                idempotency_key=idempotency_key,
            )
            db.add(order)
            db.commit()
            db.refresh(order)
            return {
                "id": str(order.id),
                "status": order.status,
                "placed_at": order.placed_at.isoformat(),
            }

    def get_order_history(self, phone: str, limit: int = 5) -> list[dict[str, Any]]:
        with _get_db() as db:
            orders = (
                db.query(OrderRecord)
                .filter_by(phone=phone)
                .order_by(OrderRecord.placed_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": str(o.id),
                    "items": o.items_snapshot,
                    "total": float(o.total_amount or 0),
                    "delivery_type": o.delivery_type,
                    "placed_at": o.placed_at.isoformat(),
                    "status": o.status,
                }
                for o in orders
            ]

    # ------------------------------------------------------------------
    # Preference helpers
    # ------------------------------------------------------------------

    def get_customer_preferences(self, phone: str) -> dict[str, Any]:
        session = self.get_active_session(phone)
        return session.get("preferences", {}) if session else {}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _session_to_dict(session: ChatSession) -> dict[str, Any]:
        return {
            "id": str(session.id),
            "customer_id": str(session.customer_id),
            "phone": session.phone,
            "state": session.state,
            "cart": session.cart or [],
            "preferences": session.preferences or {},
            "delivery_type": session.delivery_type,
            "delivery_address": session.delivery_address,
            "last_message_at": (
                session.last_message_at.isoformat() if session.last_message_at else None
            ),
            "expires_at": (
                session.expires_at.isoformat() if session.expires_at else None
            ),
        }
