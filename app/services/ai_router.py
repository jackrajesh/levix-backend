import logging
from sqlalchemy.orm import Session

logger = logging.getLogger("levix.ai_router")

class AIRouter:
    @classmethod
    def process_message(cls, db: Session, shop_id: int, customer_phone: str, message: str) -> str:
        from .guided_conversation_engine import GuidedConversationEngine
        return GuidedConversationEngine.process_message(db, str(shop_id), customer_phone, message)
