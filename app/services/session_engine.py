import logging
from sqlalchemy.orm import Session
from .. import models
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("levix.session_engine")

class SessionEngine:
    """
    Phase 7: Bulletproof Session State Machine.
    """
    
    STATES = [
        "BROWSING", "ASKING", "READY_TO_ORDER", 
        "AWAITING_NAME", "AWAITING_PHONE", "AWAITING_ADDRESS", 
        "AWAITING_CONFIRM", "ORDER_PLACED", "FOLLOWUP"
    ]

    @staticmethod
    def get_session(db: Session, shop_id: int, customer_phone: str) -> models.AIConversationSession:
        # 1. Clean up stale sessions (Phase 5: 30 min timeout)
        timeout = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        session = db.query(models.AIConversationSession).filter(
            models.AIConversationSession.shop_id == shop_id,
            models.AIConversationSession.customer_phone == customer_phone,
            models.AIConversationSession.is_active == True
        ).first()
        
        # Reset if stale
        if session and session.updated_at < timeout:
            logger.info(f"SESSION_EXPIRED: {customer_phone}")
            session.is_active = False
            db.commit()
            session = None
        
        if not session:
            # Create a unique session ID
            import uuid
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            session = models.AIConversationSession(
                shop_id=shop_id,
                session_id=session_id,
                customer_phone=customer_phone,
                conversation_history=[],
                collected_fields={},
                category="BROWSING", # Default state
                turn_count=0,
                is_active=True
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            logger.info(f"SESSION_CREATED: {session_id} for {customer_phone}")
        else:
            logger.info(f"SESSION_RESTORED: {session.session_id} for {customer_phone}")
            
        return session

    @staticmethod
    def transition(db: Session, session: models.AIConversationSession, next_state: str):
        """Phase 7 Transition Rules."""
        if next_state not in SessionEngine.STATES:
            logger.warning(f"[SESSION] Invalid state transition attempt: {next_state}")
            return

        current = session.category or "BROWSING"
        
        # Rules (Phase 7)
        # Any state -> BROWSING on reset/cancel
        if next_state == "BROWSING":
            session.category = next_state
        elif current == "BROWSING" and next_state == "ASKING":
            session.category = next_state
        elif current == "ASKING" and next_state == "READY_TO_ORDER":
            session.category = next_state
        elif current == "READY_TO_ORDER" and next_state == "AWAITING_NAME":
            session.category = next_state
        # ... and so on
        else:
            # Flexible for now but logged
            session.category = next_state
            
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"[SESSION] {session.customer_phone} transitioned {current} -> {next_state}")

    @staticmethod
    def update_history(db: Session, session: models.AIConversationSession, role: str, content: str, max_history: int = 2):
        history = list(session.conversation_history or [])
        history.append({"role": role, "content": content})
        
        # Aggressively prune history to save tokens (Phase 3: Last 2 messages)
        if len(history) > max_history:
            history = history[-max_history:]
            
        session.conversation_history = history
        session.turn_count += 1
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

    @staticmethod
    def set_intent(db: Session, session: models.AIConversationSession, intent: str):
        session.last_intent = intent
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

    @staticmethod
    def close_session(db: Session, session: models.AIConversationSession):
        session.is_active = False
        session.category = "FOLLOWUP"
        db.add(session)
        db.commit()
