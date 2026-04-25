import logging
from ..core.ai_client import AIClient

logger = logging.getLogger("levix.quota_guard")

class QuotaGuard:
    """
    Phase 10: Error Immunity System.
    Wraps AIClient to manage availability and thresholds.
    """
    
    @classmethod
    def mark_failure(cls, is_rate_limit: bool = True):
        AIClient.mark_failure(429 if is_rate_limit else 500)

    @classmethod
    def mark_success(cls):
        AIClient.mark_success()

    @classmethod
    def is_ai_available(cls) -> bool:
        return not AIClient.is_on_cooldown()

    @classmethod
    def get_recommended_model(cls) -> str:
        return AIClient.get_active_model()

    @classmethod
    def get_token_cap(cls, tier: str = "free") -> int:
        if tier == "premium":
            return 1000
        return 300 # Strict cap for free tier (Phase 3)
