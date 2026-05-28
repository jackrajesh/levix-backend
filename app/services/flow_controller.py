"""
flow_controller.py — LEVIX Flow Transition Validation Controller
================================================================
THE ONLY AUTHORITY for state transitions in the conversation lifecycle.

ARCHITECTURE RULE (NON-NEGOTIABLE):
  AI Layer → Transition Request → FlowController.validate_transition()
             → Audit + Logging → Atomic Commit → SSE Broadcast → CRM Update

The AI NEVER directly mutates flow state.
The AI ONLY submits a TransitionRequest.
This controller decides if it is legal.

NEVER:
- mutate state inside composer
- mutate state during SSE stream
- mutate state inside frontend render functions
- mutate state from webhook helpers directly
- allow freeform AI-generated transitions
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger("levix.flow_controller")

# ─────────────────────────────────────────────────────────────────────────────
# ALLOWED STATE TRANSITION MATRIX
# ─────────────────────────────────────────────────────────────────────────────
# inquiry_status transitions (ConversationSession.inquiry_status)
# Maps: current_state -> set of allowed next_states

INQUIRY_TRANSITION_MATRIX: Dict[str, set] = {
    "ACTIVE":          {"PAUSED", "WAITING_SUPPORT", "WAITING_CUSTOMER", "RESOLVED", "CANCELLED"},
    "PAUSED":          {"ACTIVE", "CANCELLED", "RESOLVED"},          # PAUSED can resume, cancel or complete
    "WAITING_SUPPORT": {"ACTIVE", "RESOLVED", "CANCELLED"},
    "WAITING_CUSTOMER":{"ACTIVE", "RESOLVED", "CANCELLED"},
    "RESOLVED":        set(),                            # TERMINAL — no further transitions
    "CANCELLED":       set(),                            # TERMINAL — no further transitions (strict)
    "NEW":             {"ACTIVE", "CANCELLED"},          # Legacy status compat
    "ONGOING":         {"PAUSED", "RESOLVED", "CANCELLED", "WAITING_CUSTOMER"},
}

# Guided conversation flow state transitions (AIConversationSession guided_state)
GUIDED_FLOW_TRANSITION_MATRIX: Dict[str, set] = {
    "idle":                   {"awaiting_main_menu", "inquiry_flow", "order_flow", "track_flow"},
    "awaiting_main_menu":     {"inquiry_flow", "order_flow", "track_flow", "idle"},
    "inquiry_flow":           {"inquiry_collect_name", "inquiry_collect_phone", "inquiry_complete", "idle"},
    "inquiry_collect_name":   {"inquiry_collect_phone", "inquiry_complete", "idle"},
    "inquiry_collect_phone":  {"inquiry_complete", "idle"},
    "inquiry_complete":       {"idle"},
    "order_flow":             {"awaiting_category", "awaiting_product", "awaiting_qty", "awaiting_confirm", "order_complete", "idle"},
    "awaiting_category":      {"awaiting_product", "idle", "awaiting_main_menu"},
    "awaiting_product":       {"awaiting_qty", "idle", "awaiting_main_menu"},
    "awaiting_qty":           {"awaiting_confirm", "idle"},
    "awaiting_confirm":       {"order_complete", "idle"},
    "order_complete":         {"idle"},
    "track_flow":             {"idle"},
    # Allow any state to recover to idle (fallback)
    "*_recover":              {"idle"},
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TransitionRequest:
    """Submitted by AI or system — never directly committed by AI."""
    current_state: str
    requested_state: str
    flow_type: str            # "inquiry", "guided", "order"
    actor: str                # "customer", "owner", "system", "ai", "controller"
    trigger_source: str       # "command", "webhook", "timeout", "ai", "system"
    session_id: Optional[str] = None
    shop_id: Optional[str] = None
    customer_phone: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransitionResult:
    """Result returned by validate_transition — always inspected before any DB write."""
    allowed: bool
    reason: str
    severity: str                      # "info", "warning", "error", "critical"
    repaired_state: Optional[str] = None  # Set when controller auto-corrects
    should_log: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# FLOW CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

class FlowController:
    """
    Single source of truth for all state transition validation.
    Returns a TransitionResult — callers MUST check result.allowed before writing.
    """

    @staticmethod
    def validate_transition(request: TransitionRequest) -> TransitionResult:
        """
        Validate a requested state transition against the allowed matrix.
        This is the ONLY entry point for state change decisions.

        Returns TransitionResult with allowed=True/False and reason.
        """
        current = (request.current_state or "idle").strip()
        requested = (request.requested_state or "").strip()
        flow_type = (request.flow_type or "inquiry").lower()

        # ── Guard: empty requested state
        if not requested:
            return TransitionResult(
                allowed=False,
                reason="requested_state is empty",
                severity="error",
            )

        # ── Guard: no-op (same state)
        if current == requested:
            return TransitionResult(
                allowed=True,
                reason="no_op: same state",
                severity="info",
                should_log=False,
            )

        # ── TERMINAL STATE PROTECTION (absolute)
        if current in ("CANCELLED", "RESOLVED"):
            logger.warning(
                f"[FLOW_CTRL] BLOCKED: terminal state '{current}' → '{requested}' "
                f"for session={request.session_id} actor={request.actor}"
            )
            return TransitionResult(
                allowed=False,
                reason=f"terminal_state: '{current}' cannot transition to '{requested}'",
                severity="critical",
            )

        # ── INQUIRY FLOW VALIDATION
        if flow_type == "inquiry":
            allowed_next = INQUIRY_TRANSITION_MATRIX.get(current, set())
            if requested not in allowed_next:
                # Special case: AI cannot override to CANCELLED from RESOLVED
                if requested == "ACTIVE" and current == "CANCELLED":
                    logger.error(
                        f"[FLOW_CTRL] AI attempted CANCELLED→ACTIVE recovery for session={request.session_id}"
                    )
                    return TransitionResult(
                        allowed=False,
                        reason="cancelled_to_active_forbidden: CANCELLED is terminal",
                        severity="critical",
                    )

                logger.warning(
                    f"[FLOW_CTRL] BLOCKED inquiry transition: '{current}' → '{requested}' "
                    f"(actor={request.actor}, session={request.session_id})"
                )
                return TransitionResult(
                    allowed=False,
                    reason=f"illegal_inquiry_transition: '{current}' → '{requested}'",
                    severity="warning",
                )

        # ── GUIDED FLOW VALIDATION
        elif flow_type == "guided":
            allowed_next = GUIDED_FLOW_TRANSITION_MATRIX.get(current, set())
            # Guided flows allow any → idle as recovery
            if requested == "idle":
                return TransitionResult(
                    allowed=True,
                    reason="recovery_to_idle_always_permitted",
                    severity="info",
                )
            if requested not in allowed_next:
                # Log but allow with warning — guided flows are more flexible
                logger.warning(
                    f"[FLOW_CTRL] Unregistered guided transition: '{current}' → '{requested}' "
                    f"(session={request.session_id}) — allowing as unknown extension state"
                )
                return TransitionResult(
                    allowed=True,
                    reason=f"guided_unregistered_transition: '{current}' → '{requested}' (allowed with audit)",
                    severity="warning",
                )

        # ── AI ACTOR EXTRA VALIDATION
        # AI may only request transitions, never force them directly
        if request.actor == "ai":
            # AI cannot directly set CANCELLED or RESOLVED without owner/system confirmation
            if requested in ("CANCELLED", "RESOLVED") and request.trigger_source == "ai":
                logger.warning(
                    f"[FLOW_CTRL] AI attempted direct terminal transition to '{requested}' "
                    f"for session={request.session_id} — requiring controller approval"
                )
                return TransitionResult(
                    allowed=False,
                    reason=f"ai_cannot_directly_terminate: requires controller validation",
                    severity="warning",
                )

        logger.info(
            f"[FLOW_CTRL] APPROVED: '{current}' → '{requested}' "
            f"(flow={flow_type}, actor={request.actor}, session={request.session_id})"
        )
        return TransitionResult(
            allowed=True,
            reason=f"transition_approved: '{current}' → '{requested}'",
            severity="info",
        )

    @staticmethod
    def validate_inquiry_command(command: str, current_inquiry_status: str,
                                  session_id: str, actor: str = "customer") -> TransitionResult:
        """
        Convenience validator for the 5 customer-facing inquiry commands.
        Maps command strings to requested states and validates.
        """
        command_state_map = {
            "pause":    "PAUSED",
            "resume":   "ACTIVE",
            "cancel":   "CANCELLED",
            "complete": "RESOLVED",
        }

        if command == "status":
            # Status query — always allowed, never mutates state
            return TransitionResult(allowed=True, reason="status_query_read_only", severity="info", should_log=False)

        requested_state = command_state_map.get(command)
        if not requested_state:
            return TransitionResult(
                allowed=False,
                reason=f"unknown_command: '{command}'",
                severity="error",
            )

        return FlowController.validate_transition(TransitionRequest(
            current_state=current_inquiry_status,
            requested_state=requested_state,
            flow_type="inquiry",
            actor=actor,
            trigger_source="command",
            session_id=session_id,
        ))
