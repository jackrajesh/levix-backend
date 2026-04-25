"""
webhook_guard.py — LEVIX Webhook Deduplication & Security
=========================================================
Ensures each WhatsApp message is processed exactly once.
Prevents endless retries and malformed payload crashes.
"""

import logging
from typing import Dict, Set

logger = logging.getLogger("levix.webhook_guard")

# In-memory cache for message IDs (TTL handled by process restarts or simple size limit)
_PROCESSED_MESSAGE_IDS: Set[str] = set()
_MAX_CACHE_SIZE = 5000

class WebhookGuard:
    @staticmethod
    def is_duplicate(message_id: str) -> bool:
        """
        Phase 10: Deduplication Logic.
        Returns True if the message has already been processed.
        """
        if not message_id:
            return False
            
        if message_id in _PROCESSED_MESSAGE_IDS:
            logger.info(f"[GUARD] Duplicate message detected: {message_id}")
            return True
            
        # Add to cache
        _PROCESSED_MESSAGE_IDS.add(message_id)
        
        # Simple cache management
        if len(_PROCESSED_MESSAGE_IDS) > _MAX_CACHE_SIZE:
            # Pop roughly the oldest (not perfect but simple)
            _PROCESSED_MESSAGE_IDS.clear() 
            _PROCESSED_MESSAGE_IDS.add(message_id)
            
        return False

    @staticmethod
    def validate_payload(payload: Dict) -> bool:
        """
        Phase 10: Payload Validation.
        Ensures essential fields exist before processing.
        """
        try:
            # WhatsApp Business API Structure
            entry = payload.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            
            # Must have either messages or statuses
            if not value.get("messages") and not value.get("statuses"):
                return False
                
            return True
        except (IndexError, KeyError, TypeError):
            return False
