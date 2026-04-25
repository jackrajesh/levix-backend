"""
ai_assistant.py — [DEPRECATED]
=============================
This module is legacy. All AI logic has been migrated to:
- app/services/ai_router.py (The Brain)
- app/services/ai_matcher.py (Match Engine)
- app/services/sales_engine.py (Revenue Logic)
- app/services/session_engine.py (State Machine)

DO NOT USE THIS FILE. It will be removed in the next major release.
"""

def process_customer_message(*args, **kwargs):
    raise DeprecationWarning("ai_assistant.py is deprecated. Use AIRouter instead.")
