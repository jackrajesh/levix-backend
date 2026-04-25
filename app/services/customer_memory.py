"""
customer_memory.py — Backward-compatibility shim
=================================================
All logic has been moved to customer_profile_engine.py.
This file re-exports CustomerMemoryEngine so existing imports
(ai_router.py, etc.) continue to work without changes.
"""
from .customer_profile_engine import CustomerProfileEngine as CustomerMemoryEngine

__all__ = ["CustomerMemoryEngine"]
