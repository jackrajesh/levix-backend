import logging
import json
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from .. import models
from .sse import broadcast_event
from .customer_profile_engine import CustomerProfileEngine
from .order_engine import OrderEngine
from .order_controller import generate_order_id

logger = logging.getLogger("levix.guided_conversation")

def resolve_shop_category(db: Session, shop_id: str, name: str) -> str:
    """Idempotently resolves a conversation category by name for a given shop."""
    cat = db.query(models.ConversationCategory).filter(
        models.ConversationCategory.shop_id == shop_id,
        models.ConversationCategory.name == name
    ).first()
    if not cat:
        color_map = {
            "ORDER": "#f59e0b",
            "INQUIRY": "#3b82f6",
            "VIP": "#ec4899",
            "FOLLOWUP": "#8b5cf6",
            "SUPPORT": "#10b981",
            "DELIVERY": "#14b8a6",
            "PAYMENT": "#ef4444",
            "CUSTOM": "#6b7280"
        }
        color = color_map.get(name.upper(), "#6b7280")
        cat = models.ConversationCategory(
            shop_id=shop_id,
            name=name,
            color=color
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
    return cat.id

def get_auto_category(db: Session, shop_id: str, customer_phone: str, default_cat: str) -> str:
    """Determines category. If customer has VIP profile, VIP is assigned. Otherwise, default_cat is assigned."""
    profile = db.query(models.CustomerProfile).filter(
        models.CustomerProfile.shop_id == shop_id,
        models.CustomerProfile.customer_phone == customer_phone
    ).first()
    
    is_vip = False
    if profile:
        seg = getattr(profile, "segment", "") or ""
        tags = getattr(profile, "tags_json", []) or []
        if "VIP" in seg.upper() or "VIP" in tags or any("VIP" in str(t).upper() for t in tags):
            is_vip = True
            
    target_name = "VIP" if is_vip else default_cat
    return resolve_shop_category(db, shop_id, target_name)

class GuidedConversationEngine:
    @classmethod
    def process_message(cls, db: Session, shop_id: str, customer_phone: str, raw_message: str) -> str:
        try:
            logger.info(f"[GUIDED] Starting message processing for {customer_phone} in Shop {shop_id}")
            
            # 1. Fetch Shop Details
            shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
            shop_name = shop.shop_name if shop else "our shop"
            
            # 2. Get active session or create a fresh one (Enforcing Single Active Flow Ownership - Rule 4)
            active_sessions = db.query(models.AIConversationSession).filter(
                models.AIConversationSession.shop_id == shop_id,
                models.AIConversationSession.customer_phone == customer_phone,
                models.AIConversationSession.is_active == True
            ).order_by(models.AIConversationSession.created_at.desc()).all()
            
            if len(active_sessions) > 1:
                logger.warning(f"[GUIDED] Found {len(active_sessions)} active sessions. Enforcing single active session ownership.")
                session = active_sessions[0] # Keep the newest one
                for old_sess in active_sessions[1:]:
                    old_sess.is_active = False
                db.commit()
            elif len(active_sessions) == 1:
                session = active_sessions[0]
            else:
                session = None
            
            if not session:
                session_id = f"sess_{uuid.uuid4().hex[:12]}"
                logger.info(f"[GUIDED] No active session found. Creating fresh session: {session_id}")
                session = models.AIConversationSession(
                    shop_id=shop_id,
                    session_id=session_id,
                    customer_phone=customer_phone,
                    conversation_history=[],
                    collected_fields={"guided_state": "idle", "session_data": {}},
                    category="idle",
                    turn_count=0,
                    is_active=True,
                    source="whatsapp"
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                logger.info(f"[GUIDED] Session {session_id} saved to DB.")
                
            fields = session.collected_fields or {}
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except Exception:
                    logger.warning(f"[GUIDED] Failed to parse collected_fields JSON for session {session.session_id}")
                    fields = {}
                
            guided_state = fields.get("guided_state", "idle")
            session_data = fields.get("session_data", {})
            cart = fields.get("cart", [])
            
            # 2.2 Strict Session Expiration and Inactivity Watchdog (Rule 2)
            now = datetime.now(timezone.utc)
            is_expired = False
            elapsed_seconds = 0
            
            # Use updated_at or created_at for elapsed calculation
            updated_at = session.updated_at
            if updated_at and guided_state and guided_state != "idle":
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                elapsed_seconds = (now - updated_at).total_seconds()
                
                # Dynamic timeout limits as per Rule 2
                if guided_state.startswith("order_"):
                    timeout_limit = 15 * 60  # 15 minutes
                elif guided_state.startswith("inquiry_"):
                    timeout_limit = 30 * 60  # 30 minutes
                elif guided_state in ("awaiting_booking_lookup", "track_order_select"):
                    timeout_limit = 5 * 60   # 5 minutes
                else:
                    timeout_limit = 5 * 60   # Default 5 minutes
                
                if elapsed_seconds > timeout_limit:
                    is_expired = True
                    logger.info(f"[GUIDED] Session expired. State: {guided_state}, elapsed: {elapsed_seconds}s, limit: {timeout_limit}s")

            # 2.3 Strict Integrity Verification (Rule 3)
            VALID_GUIDED_STATES = {
                "idle", "awaiting_main_menu", "inquiry_collect_text", "inquiry_collect_name",
                "order_select_category", "order_select_product", "order_select_quantity",
                "order_cart_review", "order_cart_edit_select", "order_cart_edit_qty",
                "order_delivery_type", "order_pickup_collect_name", "order_delivery_collect_name",
                "order_delivery_collect_address", "order_delivery_collect_note", "order_final_confirmation",
                "awaiting_booking_lookup", "track_order_select"
            }
            
            is_corrupted = False
            if guided_state not in VALID_GUIDED_STATES:
                is_corrupted = True
                logger.warning(f"[INTEGRITY] Corrupted state found: {guided_state}")
            elif guided_state == "order_select_quantity" and "selected_product" not in session_data:
                is_corrupted = True
                logger.warning("[INTEGRITY] Missing selected_product in order_select_quantity")
            elif guided_state == "order_cart_edit_qty" and "editing_item" not in session_data:
                is_corrupted = True
                logger.warning("[INTEGRITY] Missing editing_item in order_cart_edit_qty")
            elif guided_state in ("order_pickup_collect_name", "order_delivery_collect_name", "order_delivery_collect_address", "order_delivery_collect_note", "order_final_confirmation") and not cart:
                is_corrupted = True
                logger.warning(f"[INTEGRITY] Empty cart in state {guided_state}")
            elif guided_state == "order_final_confirmation" and "customer_name" not in session_data:
                is_corrupted = True
                logger.warning("[INTEGRITY] Missing customer_name in order_final_confirmation")
            elif guided_state == "inquiry_collect_name" and "inquiry_text" not in session_data:
                is_corrupted = True
                logger.warning("[INTEGRITY] Missing inquiry_text in inquiry_collect_name")

            # 2.4 Fresh Greeting Recognition & Intercept (Rule 1 & Rule 5)
            message = raw_message.strip()
            message_lower = message.lower()
            
            fresh_greetings = {"hi", "hello", "hey", "start", "menu", "home"}
            is_greeting = message_lower in fresh_greetings
            
            # If expired, corrupted, or user sends a fresh greeting, destroy context and reset safely!
            should_reset = is_expired or is_corrupted or (is_greeting and guided_state != "idle")
            
            if should_reset:
                reset_reason = "expired" if is_expired else ("corrupted" if is_corrupted else "fresh_greeting")
                logger.info(f"[GUIDED] Safety Reset Triggered. Reason: {reset_reason}. Previous state: {guided_state}")
                
                # Log forensic event if corrupted or reset
                try:
                    from .event_logger import ConversationEventLogger, EventType
                    metadata = {
                        "reset_reason": reset_reason,
                        "previous_state": guided_state,
                        "elapsed_seconds": elapsed_seconds,
                        "message": raw_message
                    }
                    ConversationEventLogger.log(
                        event_type=EventType.FLOW_ERROR if is_corrupted else EventType.FLOW_TIMED_OUT,
                        session_id=session.session_id,
                        shop_id=shop_id,
                        customer_phone=customer_phone,
                        previous_state=guided_state,
                        next_state="idle" if not is_expired else "awaiting_main_menu",
                        trigger_source="system",
                        trigger_reason=f"session_lifecycle_reset:{reset_reason}",
                        actor_type="system",
                        actor_id="system",
                        metadata=metadata
                    )
                except Exception as log_err:
                    logger.debug(f"[GUIDED] Forensic log failed: {log_err}")
                
                if is_expired:
                    # Return timeout warning text and trigger main menu fresh start
                    session.collected_fields = {
                        "guided_state": "awaiting_main_menu",
                        "session_data": {},
                        "cart": []
                    }
                    session.category = "idle"
                    session.updated_at = now
                    db.commit()
                    
                    return {
                        "type": "button",
                        "body": "⚠️ *Session Expired due to inactivity.*\nYour previous conversation timed out. Let's start fresh!\n\nPlease choose an option below:",
                        "buttons": [
                            {"id": "btn_order", "title": "Place Order"},
                            {"id": "btn_inquiry", "title": "Inquiry"},
                            {"id": "btn_track_order", "title": "Track Order"}
                        ]
                    }

                # Reset to clean idle state
                guided_state = "idle"
                session_data = {}
                cart = []
                session.collected_fields = {
                    "guided_state": "idle",
                    "session_data": {},
                    "cart": []
                }
                session.category = "idle"
                session.updated_at = now
                db.commit()
            
            logger.info(f"[GUIDED] Session loaded: {session.session_id} | State: {guided_state} | Cart Items: {len(cart)}")
            
            # 3. Clean and normalize message
            message = raw_message.strip()
            message_lower = message.lower()
            
            now = datetime.now(timezone.utc)

            # 3.2 System Commands Intercept
            import re
            cmd_match = re.match(r"^\s*(pause|resume|cancel|complete|status)\s+((?:inq|ord)-\d+)\s*$", message_lower)
            if cmd_match:
                cmd = cmd_match.group(1)
                inq_num = cmd_match.group(2).upper()
                logger.info(f"[GUIDED] System Command Intercepted: {cmd} {inq_num} from phone {customer_phone}")
                
                # Look up the inquiry session across the shop
                target_inq = db.query(models.ConversationSession).filter(
                    models.ConversationSession.shop_id == shop_id,
                    models.ConversationSession.inquiry_number == inq_num
                ).first()
                
                if not target_inq:
                    return f"⚠️ Inquiry *{inq_num}* was not found. Please verify the ID and try again."
                
                # Strict ownership validation
                if target_inq.customer_phone != customer_phone:
                    return f"🚫 Access denied. Inquiry *{inq_num}* does not belong to your phone number."
                
                # ── FLOW CONTROLLER VALIDATION (surgical addition) ──────────
                # Log the intercepted command regardless of outcome
                try:
                    from .event_logger import ConversationEventLogger
                    from .flow_controller import FlowController
                    ConversationEventLogger.log_command_intercepted(
                        session_id=target_inq.id,
                        shop_id=shop_id,
                        customer_phone=customer_phone,
                        command=cmd,
                        inq_num=inq_num,
                        metadata={"raw_message": raw_message},
                    )
                    # Validate transition through controller
                    transition_result = FlowController.validate_inquiry_command(
                        command=cmd,
                        current_inquiry_status=target_inq.inquiry_status or "ACTIVE",
                        session_id=target_inq.id,
                        actor="customer",
                    )
                    if not transition_result.allowed:
                        # Log the block
                        ConversationEventLogger.log_state_transition_blocked(
                            session_id=target_inq.id,
                            shop_id=shop_id,
                            current_state=target_inq.inquiry_status or "ACTIVE",
                            requested_state=cmd,
                            reason=transition_result.reason,
                            actor_type="customer",
                        )
                        # Return user-friendly message based on severity
                        if transition_result.severity == "critical":
                            return f"⚠️ This action is not allowed on *{inq_num}*. Inquiry is already {target_inq.inquiry_status}."
                        return f"ℹ️ Cannot *{cmd}* inquiry *{inq_num}*. Current state: {target_inq.inquiry_status}."
                except ImportError:
                    pass  # Observability layer not available — let business logic continue
                except Exception as ctrl_err:
                    logger.warning(f"[GUIDED] FlowController check failed (non-blocking): {ctrl_err}")
                # ── END FLOW CONTROLLER VALIDATION ──────────────────────────

                # Perform state transition based on command
                prev_status = target_inq.inquiry_status or "ACTIVE"
                system_message_text = None
                reply_text = ""
                
                if cmd == "pause":
                    target_inq.inquiry_status = "PAUSED"
                    target_inq.status = "PAUSED"
                    target_inq.paused_at = now
                    system_message_text = "Inquiry paused"
                    reply_text = f"⏸ Inquiry *{inq_num}* paused successfully.\n\nYou can resume anytime by replying with *Resume {inq_num}*."
                elif cmd == "resume":
                    target_inq.inquiry_status = "ACTIVE"
                    target_inq.status = "ONGOING"
                    target_inq.resumed_at = now
                    system_message_text = "Inquiry resumed"
                    reply_text = f"▶ Inquiry *{inq_num}* resumed.\n\nPlease continue your inquiry."
                elif cmd == "cancel":
                    target_inq.inquiry_status = "CANCELLED"
                    target_inq.status = "RESOLVED"
                    target_inq.cancelled_at = now
                    system_message_text = "Inquiry cancelled"
                    reply_text = f"❌ Inquiry *{inq_num}* has been cancelled."
                elif cmd == "complete":
                    target_inq.inquiry_status = "RESOLVED"
                    target_inq.status = "RESOLVED"
                    target_inq.completed_at = now
                    system_message_text = "Inquiry completed"
                    reply_text = f"✅ Inquiry *{inq_num}* has been marked as completed.\n\nThank you for contacting us!"
                elif cmd == "status":
                    status_mapping = {
                        "ACTIVE": "Active 🟢",
                        "PAUSED": "Paused ⏸",
                        "WAITING_SUPPORT": "Waiting for Support ⏳",
                        "WAITING_CUSTOMER": "Waiting for You 👤",
                        "RESOLVED": "Resolved ✅",
                        "CANCELLED": "Cancelled ❌"
                    }
                    curr_status = status_mapping.get(target_inq.inquiry_status, target_inq.inquiry_status or "Active 🟢")
                    return f"ℹ️ *Inquiry Status for {inq_num}*:\n\nStatus: *{curr_status}*"
                
                if system_message_text:
                    # Write system message to the timeline
                    sys_msg = models.ConversationMessage(
                        session_id=target_inq.id,
                        sender_type="SYSTEM",
                        message=system_message_text,
                        timestamp=now
                    )
                    db.add(sys_msg)
                    target_inq.updated_at = now
                    
                db.commit()
                
                # ── POST-COMMIT EVENT LOG (surgical addition) ────────────────
                # Log the successful transition AFTER commit to ensure consistency
                try:
                    from .event_logger import ConversationEventLogger, EventType
                    event_type_map = {
                        "pause":    EventType.FLOW_PAUSED,
                        "resume":   EventType.FLOW_RESUMED,
                        "cancel":   EventType.FLOW_CANCELLED,
                        "complete": EventType.FLOW_COMPLETED,
                    }
                    if cmd in event_type_map:
                        ConversationEventLogger.log(
                            event_type=event_type_map[cmd],
                            session_id=target_inq.id,
                            shop_id=shop_id,
                            customer_phone=customer_phone,
                            previous_state=prev_status,
                            next_state=target_inq.inquiry_status,
                            trigger_source="command",
                            trigger_reason=f"customer_command:{cmd}",
                            actor_type="customer",
                            actor_id=customer_phone,
                            metadata={"inquiry_number": inq_num, "command": cmd},
                        )
                except Exception as log_err:
                    logger.warning(f"[GUIDED] Post-commit event log failed (non-blocking): {log_err}")
                # ── END POST-COMMIT EVENT LOG ────────────────────────────────

                # Broadcast the updates to the CRM UI in real time
                try:
                    from .sse import broadcast_event
                    broadcast_event(shop_id, "conversation_updated")
                except Exception as sse_err:
                    logger.error(f"[GUIDED] SSE broadcast error: {sse_err}")
                
                return reply_text


            # 3.3 Direct keyword routing for multitasking & Intelligent Bypass Routing
            bypass_keywords = {"order", "place order", "buy", "cart", "menu", "track", "track order", "inquiry", "ask", "cancel", "reset", "quit", "exit"}
            is_bypass = (
                message in ["btn_order", "btn_inquiry", "btn_track_order", "btn_track"]
                or message_lower in bypass_keywords
                or (message.upper().startswith("LEV-") and len(message) >= 12)
            )

            # Direct intent mapping from keywords when state is idle or awaiting_main_menu
            if guided_state in ("idle", "awaiting_main_menu"):
                if message_lower in ("order", "place order", "buy", "cart"):
                    message = "btn_order"
                    message_lower = "btn_order"
                    guided_state = "awaiting_main_menu"
                elif message_lower in ("inquiry", "ask"):
                    message = "btn_inquiry"
                    message_lower = "btn_inquiry"
                    guided_state = "awaiting_main_menu"
                elif message_lower in ("track", "track order"):
                    message = "btn_track_order"
                    message_lower = "btn_track_order"
                    guided_state = "awaiting_main_menu"
                elif message.upper().startswith("LEV-") and len(message) >= 12:
                    message = message.upper()
                    # Let the direct booking lookup interceptor catch it downstream

            # 3.5 Active Conversation Intercept (Human Handover)
            # If the user is not actively in an order flow, and there is an active session, pipe message to owner.
            # Exclude PAUSED status and bypass keywords/buttons
            if guided_state == "idle" and not is_bypass:
                active_conversation = db.query(models.ConversationSession).filter(
                    models.ConversationSession.shop_id == shop_id,
                    models.ConversationSession.customer_phone == customer_phone,
                    models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
                ).first()
                if active_conversation:
                    try:
                        # Handle legacy commands
                        if message_lower == "pauseconvo":
                            active_conversation.status = "PAUSED"
                            active_conversation.inquiry_status = "PAUSED"
                            active_conversation.paused_at = now
                            sys_msg = models.ConversationMessage(
                                session_id=active_conversation.id,
                                sender_type="SYSTEM",
                                message="Inquiry paused",
                                timestamp=now
                            )
                            db.add(sys_msg)
                            db.commit()
                            from .sse import broadcast_event
                            broadcast_event(shop_id, "conversation_updated")
                            return "⏸️ Your conversation has been paused. Send any message anytime to continue."
                            
                        elif message_lower == "stopconvo":
                            active_conversation.status = "RESOLVED"
                            active_conversation.inquiry_status = "RESOLVED"
                            active_conversation.completed_at = now
                            sys_msg = models.ConversationMessage(
                                session_id=active_conversation.id,
                                sender_type="SYSTEM",
                                message="Inquiry completed",
                                timestamp=now
                            )
                            db.add(sys_msg)
                            db.commit()
                            from .sse import broadcast_event
                            broadcast_event(shop_id, "conversation_updated")
                            return "✅ Your inquiry has been closed. Thank you for contacting us."
                            
                        is_resumed = False
                        if active_conversation.status == "PAUSED":
                            active_conversation.status = "ONGOING"
                            active_conversation.inquiry_status = "ACTIVE"
                            active_conversation.resumed_at = now
                            is_resumed = True
                        else:
                            active_conversation.status = "ONGOING"
                            active_conversation.inquiry_status = "ACTIVE"
                            
                        new_msg = models.ConversationMessage(
                            session_id=active_conversation.id,
                            sender_type="CUSTOMER",
                            message=message,
                            timestamp=now
                        )
                        db.add(new_msg)
                        active_conversation.updated_at = now
                        active_conversation.last_message_at = now
                        db.commit()
                        
                        from .sse import broadcast_event
                        broadcast_event(shop_id, "conversation_updated")
                        
                        if is_resumed:
                            return "▶️ Conversation Resumed. Your message has been sent to the owner."
                            
                        # Help Footer Logic (every 5 messages)
                        help_count = session_data.get("help_footer_count", 0) + 1
                        session_data["help_footer_count"] = help_count
                        session.collected_fields = {
                            "guided_state": guided_state,
                            "session_data": session_data,
                            "cart": cart
                        }
                        db.commit()
                        
                        if help_count % 5 == 0:
                            return (
                                "━━━━━━━━━━━━━━━\n"
                                "💬 *LEVIX Support Active*\n\n"
                                "Type:\n"
                                "• *pauseconvo* → pause inquiry\n"
                                "• *stopconvo* → close inquiry\n\n"
                                "You can continue anytime.\n"
                                "━━━━━━━━━━━━━━━"
                            )
                        
                        return "" # Silent, human owner will reply
                    except Exception as e:
                        db.rollback()
                        logger.error(f"[CONV ERROR] {e}")
            
            # 4. Check for Inactivity Timeouts (Rule 2)
            updated_at = session.updated_at
            if updated_at and guided_state and guided_state != "idle":
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                elapsed = (now - updated_at).total_seconds()
                
                logger.info(f"[GUIDED] Elapsed time since last update: {elapsed:.1f}s")
                
                # Inquiry Timeout: 30 minutes (1800 seconds)
                if guided_state.startswith("inquiry_") and elapsed > 1800:
                    logger.info(f"[GUIDED] Inquiry session timeout triggered for {session.session_id}")
                    session.collected_fields = {
                        "guided_state": "idle",
                        "session_data": {},
                        "cart": cart,
                        "last_activity_at": now.isoformat(),
                        "context_timeout_minutes": 30
                    }
                    session.category = "idle"
                    session.updated_at = now
                    db.commit()
                    return "⏰ Your inquiry session has timed out due to 30 minutes of inactivity. Send any message to start a new request."
                
                # Order Timeout: 15 minutes (900 seconds)
                elif guided_state.startswith("order_") and elapsed > 900:
                    logger.info(f"[GUIDED] Order session timeout triggered for {session.session_id}")
                    session.collected_fields = {
                        "guided_state": "idle",
                        "session_data": {},
                        "cart": [],
                        "last_activity_at": now.isoformat(),
                        "context_timeout_minutes": 15
                    }
                    session.category = "idle"
                    session.updated_at = now
                    db.commit()
                    return "⏰ Your ordering session has timed out due to 15 minutes of inactivity, and your cart has been cleared. Send any message to start a new request."
                
                # Booking / Tracking Timeout: 5 minutes (300 seconds)
                elif (guided_state in ("awaiting_booking_lookup", "track_order_select")) and elapsed > 300:
                    logger.info(f"[GUIDED] Booking tracking lookup session timeout triggered for {session.session_id}")
                    session.collected_fields = {
                        "guided_state": "idle",
                        "session_data": {},
                        "cart": cart,
                        "last_activity_at": now.isoformat(),
                        "context_timeout_minutes": 5
                    }
                    session.category = "idle"
                    session.updated_at = now
                    db.commit()
                    return "⏰ Your booking tracking session has timed out due to 5 minutes of inactivity. Send any message to start a new request."

            # 5. Check Daily Session Limits (Maximum 5 total requests/sessions in last 12 hours)
            if guided_state == "idle":
                cutoff = now - timedelta(hours=12)
                
                order_count = db.query(models.Order).filter(
                    models.Order.shop_id == shop_id,
                    models.Order.phone == customer_phone,
                    models.Order.created_at >= cutoff
                ).count()

                inquiry_count = db.query(models.PendingRequest).filter(
                    models.PendingRequest.shop_id == shop_id,
                    models.PendingRequest.customer_phone == customer_phone,
                    models.PendingRequest.created_at >= cutoff
                ).count()

                logger.info(f"[GUIDED] Usage check: Orders={order_count}, Inquiries={inquiry_count} in last 12h")

                if (order_count + inquiry_count) >= 5:
                    logger.warning(f"[GUIDED] Rate limit exceeded for {customer_phone}")
                    return "🚫 You have reached today's request limit. Please try again later."

            # 6. Global Reset/Cancel handling
            if message_lower in ("cancel", "reset", "quit", "exit") and guided_state != "idle":
                logger.info(f"[GUIDED] User requested cancel/reset for session {session.session_id}")
                session.collected_fields = {
                    "guided_state": "idle",
                    "session_data": {},
                    "cart": []
                }
                session.category = "idle"
                session.updated_at = now
                db.commit()
                return "❌ Request cancelled. Send any message to start a new request."

            # ==========================================
            # GLOBAL TRACKING INTERCEPTORS
            # ==========================================
            is_track_request = message in ("btn_track", "btn_track_order") or message_lower in ("track order", "track", "track_order")
            
            if is_track_request:
                logger.info("[TRACK_ORDER] button clicked")
                logger.info("[TRACK_ORDER] entering tracking flow")
                
                # Query DB for active orders
                active_orders = db.query(models.Order).filter(
                    models.Order.shop_id == shop_id,
                    models.Order.phone == customer_phone,
                    models.Order.status.in_(["PENDING", "CONFIRMED"])
                ).order_by(models.Order.created_at.desc()).all()
                
                logger.info(f"[TRACK_ORDER] active_orders_found={len(active_orders)}")
                
                if len(active_orders) > 0:
                    sections = [
                        {
                            "title": "Your Active Orders",
                            "rows": [
                                {
                                    "id": f"track_order_{order.id}",
                                    "title": f"#{order.order_id}",
                                    "description": f"{order.booking_id} • {'Pending' if order.status == 'PENDING' else 'Accepted'} • ₹{int(order.total_amount)}"
                                } for order in active_orders
                            ]
                        }
                    ]
                    reply = {
                        "type": "list",
                        "body": "🔔 *Automatic status updates are enabled for your orders.*\n\nSelect an active order below to track, or type a completed order's Booking ID directly to look up details:",
                        "button_text": "View Orders",
                        "sections": sections,
                        "header": "🔍 Track Orders"
                    }
                    session.collected_fields = {
                        "guided_state": "track_order_select",
                        "session_data": session_data,
                        "cart": cart
                    }
                else:
                    logger.info("[TRACK_ORDER] active_orders_found=0")
                    reply = (
                        "📦 *No active orders found.*\n\n"
                        "To track completed or cancelled orders, please type your *Booking ID* (e.g., LEV-XXXXXXXX):"
                    )
                    session.collected_fields = {
                        "guided_state": "awaiting_booking_lookup",
                        "session_data": session_data,
                        "cart": cart
                    }
                session.category = "track"
                session.updated_at = now
                db.commit()
                return reply

            # Global interactive active order row selection interceptor
            if message.startswith("track_order_"):
                order_id_uuid = message.replace("track_order_", "")
                logger.info(f"[TRACK_ORDER] Global intercept for track_order_{order_id_uuid}")
                order = db.query(models.Order).filter(
                    models.Order.shop_id == shop_id,
                    models.Order.id == order_id_uuid
                ).first()
                if order:
                    if order.phone != customer_phone:
                        logger.warning(f"[TRACK_ORDER] Intercept ownership check failed for order {order_id_uuid}")
                        reply = "🚫 Access denied. This order does not belong to your phone number."
                    else:
                        logger.info(f"[TRACK_ORDER] Intercept ownership check success")
                        order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
                        if order_items:
                            items_str = "\n".join(f"• {item.quantity}x {item.name}" for item in order_items)
                        else:
                            items_str = order.product or "No items listed."
                        
                        status_lbl = {
                            "PENDING": "Pending 🟡",
                            "CONFIRMED": "Accepted 🟢",
                            "DELIVERED": "Completed ✅",
                            "CANCELLED": "Rejected ❌"
                        }.get(order.status, order.status)
                        
                        date_str = order.created_at.strftime("%d-%m-%Y %I:%M %p")
                        
                        body_text = (
                            f"🧾 *Order Details*\n\n"
                            f"🔖 *Booking ID:* {order.booking_id}\n"
                            f"🧾 *Order Number:* #{order.order_id}\n"
                            f"📦 *Status:* {status_lbl}\n"
                            f"📅 *Date:* {date_str}\n"
                            f"💰 *Amount:* ₹{int(order.total_amount)}\n\n"
                            f"🛍️ *Items:*\n{items_str}\n\n"
                            f"🚚 *Delivery Information:*\n"
                            f"👤 Name: {order.customer_name}\n"
                            f"📍 Address: {order.address}"
                        )
                        if order.notes:
                            body_text += f"\n📝 Note: {order.notes}"
                            
                        if order.status == "PENDING":
                            reply = {
                                "type": "button",
                                "body": body_text,
                                "buttons": [{"id": f"cancel_order_{order.id}", "title": "❌ Cancel Order"}]
                            }
                        elif order.status == "CONFIRMED":
                            reply = {
                                "type": "button",
                                "body": body_text,
                                "buttons": [{"id": f"request_cancel_{order.id}", "title": "❌ Request Cancel"}]
                            }
                        else:
                            reply = body_text
                else:
                    reply = "⚠️ Order details not found."
                
                # Reset state
                session.collected_fields = {
                    "guided_state": "idle",
                    "session_data": {},
                    "cart": cart
                }
                session.category = "idle"
                session.updated_at = now
                db.commit()
                return reply

            # Global Direct Booking ID lookup interceptor
            if message.upper().startswith("LEV-") and len(message) >= 12:
                logger.info(f"[TRACK_ORDER] Direct booking lookup intercept: {message}")
                order = db.query(models.Order).filter(
                    models.Order.shop_id == shop_id,
                    models.Order.booking_id == message.upper().strip()
                ).first()
                if order:
                    if order.phone != customer_phone:
                        logger.warning(f"[TRACK_ORDER] Direct lookup ownership check failed for {message}")
                        reply = "🚫 Access denied. This order does not belong to your phone number."
                    else:
                        logger.info(f"[TRACK_ORDER] Direct lookup ownership check success")
                        order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
                        if order_items:
                            items_str = "\n".join(f"• {item.quantity}x {item.name}" for item in order_items)
                        else:
                            items_str = order.product or "No items listed."
                        
                        status_lbl = {
                            "PENDING": "Pending 🟡",
                            "CONFIRMED": "Accepted 🟢",
                            "DELIVERED": "Completed ✅",
                            "CANCELLED": "Rejected ❌"
                        }.get(order.status, order.status)
                        
                        date_str = order.created_at.strftime("%d-%m-%Y %I:%M %p")
                        
                        body_text = (
                            f"🧾 *Order Details*\n\n"
                            f"🔖 *Booking ID:* {order.booking_id}\n"
                            f"🧾 *Order Number:* #{order.order_id}\n"
                            f"📦 *Status:* {status_lbl}\n"
                            f"📅 *Date:* {date_str}\n"
                            f"💰 *Amount:* ₹{int(order.total_amount)}\n\n"
                            f"🛍️ *Items:*\n{items_str}\n\n"
                            f"🚚 *Delivery Information:*\n"
                            f"👤 Name: {order.customer_name}\n"
                            f"📍 Address: {order.address}"
                        )
                        if order.notes:
                            body_text += f"\n📝 Note: {order.notes}"
                            
                        if order.status == "PENDING":
                            reply = {
                                "type": "button",
                                "body": body_text,
                                "buttons": [{"id": f"cancel_order_{order.id}", "title": "❌ Cancel Order"}]
                            }
                        elif order.status == "CONFIRMED":
                            reply = {
                                "type": "button",
                                "body": body_text,
                                "buttons": [{"id": f"request_cancel_{order.id}", "title": "❌ Request Cancel"}]
                            }
                        else:
                            reply = body_text
                else:
                    logger.warning(f"[TRACK_ORDER] invalid_booking_id={message}")
                    reply = f"⚠️ Booking ID *{message}* was not found. Please verify the code and try again."
                
                # Reset state
                session.collected_fields = {
                    "guided_state": "idle",
                    "session_data": {},
                    "cart": cart
                }
                session.category = "idle"
                session.updated_at = now
                db.commit()
                return reply

            # Global cancellation request interceptors
            if message.startswith("cancel_order_") or message.startswith("request_cancel_"):
                is_direct_cancel = message.startswith("cancel_order_")
                order_id_uuid = message.replace("cancel_order_", "") if is_direct_cancel else message.replace("request_cancel_", "")
                logger.info(f"[TRACK_ORDER] Cancellation intercept: {message}")
                
                order = db.query(models.Order).filter(
                    models.Order.shop_id == shop_id,
                    models.Order.id == order_id_uuid
                ).first()
                
                if order and order.phone == customer_phone:
                    if is_direct_cancel and order.status == "PENDING":
                        # Instant Cancel
                        order.status = "CANCELLED"
                        db.commit()
                        reply = f"❌ Your order *{order.booking_id}* has been successfully cancelled."
                        from .sse import broadcast_event
                        broadcast_event(shop_id, "orders_updated")
                    elif not is_direct_cancel and order.status == "CONFIRMED":
                        # Request Cancel via ConversationSession
                        active_conversation = db.query(models.ConversationSession).filter(
                            models.ConversationSession.shop_id == shop_id,
                            models.ConversationSession.customer_phone == customer_phone,
                            models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
                        ).first()
                        
                        try:
                            if not active_conversation:
                                inq_num = models.ConversationSession.generate_unique_number(db)
                                active_conversation = models.ConversationSession(
                                    shop_id=shop_id,
                                    customer_name=order.customer_name or "Customer",
                                    customer_phone=customer_phone,
                                    status="NEW",
                                    inquiry_number=inq_num
                                )
                                db.add(active_conversation)
                                db.flush()
                            else:
                                active_conversation.status = "NEW"
                                
                            new_msg = models.ConversationMessage(
                                session_id=active_conversation.id,
                                sender_type="CUSTOMER",
                                message=f"Cancellation Request for Order: {order.booking_id}\n\nPlease cancel my order."
                            )
                            db.add(new_msg)
                            active_conversation.updated_at = now
                            active_conversation.last_message_at = now
                            db.commit()
                            
                            from .sse import broadcast_event
                            broadcast_event(shop_id, "conversation_updated")
                            reply = f"⏳ Your cancellation request for *{order.booking_id}* has been sent to the store owner."
                        except Exception as e:
                            db.rollback()
                            logger.error(f"[CANCEL ERROR] {e}")
                            reply = "⚠️ Failed to process cancellation request. Please try again."
                    else:
                        reply = "⚠️ This order cannot be cancelled at this time."
                else:
                    reply = "🚫 Access denied or order not found."
                
                # Reset state
                session.collected_fields = {
                    "guided_state": "idle",
                    "session_data": {},
                    "cart": cart
                }
                session.category = "idle"
                session.updated_at = now
                db.commit()
                return reply


            reply = ""
            logger.info(f"[GUIDED] Routing message based on state: {guided_state}")
            logger.info(f"[STATE] Current state: {guided_state}")
            logger.info(f"[STATE] Incoming action ID: {message}")
            
            # --- IDEMPOTENT ROUTING INTERCEPTOR (WhatsApp Replays & Stale Session Auto-Heal) ---
            is_category_payload = message.startswith("category_") or message.startswith("cat_")
            if not is_category_payload and guided_state != "order_select_category":
                try:
                    active_cats = [c[0].lower() for c in db.query(models.InventoryItem.category).filter(
                        models.InventoryItem.shop_id == shop_id,
                        models.InventoryItem.quantity > 0
                    ).distinct().all() if c[0]]
                    if message_lower in active_cats:
                        is_category_payload = True
                except Exception:
                    pass
            
            if is_category_payload and guided_state != "order_select_category":
                logger.info(f"[GUIDED] Interceptor triggered: Aligning stale state {guided_state} -> order_select_category")
                guided_state = "order_select_category"
                # Ensure categories are loaded
                items = db.query(models.InventoryItem).filter(
                    models.InventoryItem.shop_id == shop_id,
                    models.InventoryItem.quantity > 0
                ).all()
                categories = sorted(list(set(item.category for item in items if item.category)))
                if not categories:
                    categories = ["General"]
                session_data["categories"] = categories

            is_product_payload = message.startswith("product_")
            if is_product_payload and guided_state != "order_select_product":
                logger.info(f"[GUIDED] Interceptor triggered: Aligning stale state {guided_state} -> order_select_product")
                guided_state = "order_select_product"
                try:
                    target_prod_id = message.split("_")[1]
                    db_item = db.query(models.InventoryItem).filter(models.InventoryItem.id == target_prod_id).first()
                    if db_item:
                        selected_cat = db_item.category or "General"
                        session_data["selected_category"] = selected_cat
                        products = db.query(models.InventoryItem).filter(
                            models.InventoryItem.shop_id == shop_id,
                            models.InventoryItem.category == selected_cat,
                            models.InventoryItem.quantity > 0
                        ).all()
                        session_data["products_in_category"] = [{
                            "id": p.id,
                            "name": p.name,
                            "price": float(p.price),
                            "stock": p.quantity
                        } for p in products]
                except Exception:
                    pass

            # ==========================================
            # STATE MACHINE ROUTING
            # ==========================================
            try:
                if guided_state == "idle":
                    logger.info("[GUIDED] State is 'idle'. Triggering main menu.")
                    # Start guided flow (UNIVERSAL TRIGGER)
                    guided_state = "awaiting_main_menu"
                    reply = {
                        "type": "button",
                        "body": f"Welcome to *{shop_name}* 👋\nPlease choose an option below:",
                        "buttons": [
                            {"id": "btn_order", "title": "Place Order"},
                            {"id": "btn_inquiry", "title": "Inquiry"},
                            {"id": "btn_track_order", "title": "Track Order"}
                        ]
                    }
    
                elif guided_state == "awaiting_main_menu":
                    # Determine selection
                    is_order = message == "btn_order"
                    is_inquiry = message == "btn_inquiry"
                    
                    logger.info(f"[GUIDED] Main Menu selection: message='{message}', is_order={is_order}, is_inquiry={is_inquiry}")
                    
                    if is_order:
                        # START STRUCTURED ORDER SESSION
                        # Instantly create or lookup active ORDER conversation session
                        try:
                            active_session = db.query(models.ConversationSession).filter(
                                models.ConversationSession.shop_id == shop_id,
                                models.ConversationSession.customer_phone == customer_phone,
                                models.ConversationSession.conversation_type == "ORDER",
                                models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
                            ).first()
                            
                            if not active_session:
                                ord_num = models.ConversationSession.generate_unique_order_number(db)
                                category_id = get_auto_category(db, shop_id, customer_phone, "ORDER")
                                
                                active_session = models.ConversationSession(
                                    shop_id=shop_id,
                                    customer_name=session_data.get("customer_name") or "Order Customer",
                                    customer_phone=customer_phone,
                                    status="NEW",
                                    inquiry_number=ord_num,
                                    conversation_type="ORDER",
                                    category_id=category_id
                                )
                                db.add(active_session)
                                db.flush()
                                
                                # Add initial SYSTEM message to order timeline
                                initial_msg = models.ConversationMessage(
                                    session_id=active_session.id,
                                    sender_type="SYSTEM",
                                    message="Customer entered checkout ordering flow"
                                )
                                db.add(initial_msg)
                                db.commit()
                                
                                # Broadcast SSE
                                from .sse import broadcast_event
                                broadcast_event(shop_id, "conversation_updated")
                        except Exception as e:
                            logger.error(f"[ORDER FLOW INITIALIZATION ERROR] {e}")
                            db.rollback()

                        # Fetch Categories
                        items = db.query(models.InventoryItem).filter(
                            models.InventoryItem.shop_id == shop_id,
                            models.InventoryItem.quantity > 0
                        ).all()
                        
                        categories = sorted(list(set(item.category for item in items if item.category)))
                        if not categories:
                            categories = ["General"]
                            
                        session_data["categories"] = categories
                        guided_state = "order_select_category"
                        
                        sections = [
                            {
                                "title": "Categories",
                                "rows": [
                                    {
                                        "id": f"category_{idx}", 
                                        "title": cat[:20], 
                                        "description": f"View items in {cat}"
                                    } for idx, cat in enumerate(categories)
                                ]
                            }
                        ]
                        reply = {
                            "type": "list",
                            "body": "Please select a category below:",
                            "button_text": "View Categories",
                            "sections": sections,
                            "header": "🛍️ Select Category"
                        }
                        
                    elif is_inquiry:
                        # START INQUIRY FLOW
                        guided_state = "inquiry_collect_text"
                        reply = (
                            f"💬 *Inquiry Section*\n"
                            f"----------------------------------\n"
                            f"Please type your inquiry below:"
                        )
                    else:
                        reply = {
                            "type": "button",
                            "body": "⚠️ Invalid selection. Please use the buttons below:",
                            "buttons": [
                                {"id": "btn_order", "title": "Place Order"},
                                {"id": "btn_inquiry", "title": "Inquiry"},
                                {"id": "btn_track_order", "title": "Track Order"}
                            ]
                        }
    
                # ----------------------------------------------------
                # INQUIRY FLOW STATES
                # ----------------------------------------------------
                elif guided_state == "inquiry_collect_text":
                    session_data["inquiry_text"] = message
                    guided_state = "inquiry_collect_name"
                    reply = "👤 Please enter your name:"
    
                elif guided_state == "inquiry_collect_name":
                    session_data["customer_name"] = message
                    
                    # Deduplication guard & Auto-linking: Check if there's an active session
                    active_session = db.query(models.ConversationSession).filter(
                        models.ConversationSession.shop_id == shop_id,
                        models.ConversationSession.customer_phone == customer_phone,
                        models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
                    ).first()
                    
                    try:
                        if not active_session:
                            # Start a ConversationSession
                            inq_num = models.ConversationSession.generate_unique_number(db)
                            category_id = get_auto_category(db, shop_id, customer_phone, "INQUIRY")
                            active_session = models.ConversationSession(
                                shop_id=shop_id,
                                customer_name=session_data["customer_name"],
                                customer_phone=customer_phone,
                                status="NEW",
                                inquiry_number=inq_num,
                                conversation_type="INQUIRY",
                                category_id=category_id
                            )
                            db.add(active_session)
                            db.flush() # Get ID
                        else:
                            # Update existing active session status to ONGOING when customer sends a follow-up
                            active_session.status = "ONGOING"
                        
                        # Add message to the session
                        initial_msg = models.ConversationMessage(
                            session_id=active_session.id,
                            sender_type="CUSTOMER",
                            message=session_data["inquiry_text"]
                        )
                        db.add(initial_msg)
                        active_session.updated_at = datetime.now(timezone.utc)
                        active_session.last_message_at = datetime.now(timezone.utc)
                        db.commit()
                    except Exception as e:
                        db.rollback()
                        logger.error(f"[INQUIRY ERROR] Failed to save conversation for {customer_phone}: {str(e)}")
                    
                    # Reset state
                    guided_state = "idle"
                    session_data = {}
                    session.category = "idle"
                    
                    # Broadcast events
                    from .sse import broadcast_event
                    broadcast_event(shop_id, "conversation_updated")
                    broadcast_event(shop_id, "new_ai_lead")
                    
                    reply = "✅ Thank you! Your inquiry has been received. Our team will get back to you shortly."
    
                # ----------------------------------------------------
                # ORDER FLOW STATES
                # ----------------------------------------------------
                elif guided_state == "order_select_category":
                        categories = session_data.get("categories", [])
                        if not categories:
                            # Auto-heal: fetch categories from DB
                            items = db.query(models.InventoryItem).filter(
                                models.InventoryItem.shop_id == shop_id,
                                models.InventoryItem.quantity > 0
                            ).all()
                            categories = sorted(list(set(item.category for item in items if item.category)))
                            if not categories:
                                categories = ["General"]
                            session_data["categories"] = categories

                        selected_cat = None
                        
                        # 1. Match by prefix category_ or cat_
                        if message.startswith("category_") or message.startswith("cat_"):
                            prefix = "category_" if message.startswith("category_") else "cat_"
                            try:
                                idx = int(message.split(prefix)[1])
                                if 0 <= idx < len(categories):
                                    selected_cat = categories[idx]
                            except (ValueError, IndexError):
                                pass
                                    
                        # 2. Match by exact category name
                        if not selected_cat:
                            for cat in categories:
                                if cat.lower() == message_lower:
                                    selected_cat = cat
                                    break
                                    
                        # 3. Match by fuzzy case-insensitive substring
                        if not selected_cat:
                            for cat in categories:
                                if message_lower in cat.lower() or cat.lower() in message_lower:
                                    selected_cat = cat
                                    break

                        if selected_cat:
                            logger.info(f"[GUIDED] Category selected: {selected_cat}")
                            session_data["selected_category"] = selected_cat
                            
                            # Fetch products
                            products = db.query(models.InventoryItem).filter(
                                models.InventoryItem.shop_id == shop_id,
                                models.InventoryItem.category == selected_cat,
                                models.InventoryItem.quantity > 0
                            ).all()
                            
                            prod_dicts = []
                            prod_lines = []
                            for idx, p in enumerate(products):
                                stock_status = " *(Only few left)*" if p.quantity <= 5 else ""
                                prod_lines.append(f"{idx+1}️⃣ {p.name} - ₹{float(p.price):.0f}{stock_status}")
                                prod_dicts.append({
                                    "id": p.id,
                                    "name": p.name,
                                    "price": float(p.price),
                                    "stock": p.quantity
                                })
                                
                            session_data["products_in_category"] = prod_dicts
                            guided_state = "order_select_product"
                            
                            sections = [
                                {
                                    "title": "Products",
                                    "rows": [
                                        {
                                            "id": f"product_{p['id']}", 
                                            "title": p["name"][:20], 
                                            "description": f"₹{p['price']:.0f} • Stock: {p['stock']}"
                                        } for p in prod_dicts
                                    ]
                                }
                            ]
                            reply = {
                                "type": "list",
                                "body": f"Select a product from {selected_cat} below:",
                                "button_text": "View Products",
                                "sections": sections,
                                "header": f"📦 Products in {selected_cat}"
                            }
                        else:
                            sections = [
                                {
                                    "title": "Categories",
                                    "rows": [
                                        {
                                            "id": f"category_{idx}", 
                                            "title": cat[:20], 
                                            "description": f"View items in {cat}"
                                        } for idx, cat in enumerate(categories)
                                    ]
                                }
                            ]
                            reply = {
                                "type": "list",
                                "body": "⚠️ Invalid selection. Please select a category below:",
                                "button_text": "View Categories",
                                "sections": sections,
                                "header": "🛍️ Select Category"
                            }
    
                elif guided_state == "order_select_product":
                    products = session_data.get("products_in_category", [])
                    
                    selected_prod = None
                    if message.startswith("product_"):
                        prod_id = message.split("_")[1]
                        for p in products:
                            if str(p["id"]) == prod_id:
                                selected_prod = p
                                break
                                    
                    if selected_prod:
                        logger.info(f"[GUIDED] Product selected: {selected_prod['name']}")
                        
                        # Requirement 1: Product Validation Layer
                        db_prod = db.query(models.InventoryItem).filter(
                            models.InventoryItem.id == selected_prod["id"],
                            models.InventoryItem.shop_id == shop_id,
                            models.InventoryItem.quantity > 0
                        ).first()
                        
                        if not db_prod:
                            logger.warning(f"[GUIDED] Product {selected_prod['id']} no longer available in DB.")
                            # Fetch products again to refresh list
                            selected_cat = session_data.get("selected_category")
                            products = db.query(models.InventoryItem).filter(
                                models.InventoryItem.shop_id == shop_id,
                                models.InventoryItem.category == selected_cat,
                                models.InventoryItem.quantity > 0
                            ).all()
                            
                            prod_dicts = []
                            for p in products:
                                prod_dicts.append({
                                    "id": p.id,
                                    "name": p.name,
                                    "price": float(p.price),
                                    "stock": p.quantity
                                })
                            session_data["products_in_category"] = prod_dicts
                            
                            sections = [
                                {
                                    "title": "Products",
                                    "rows": [
                                        {
                                            "id": f"product_{p['id']}", 
                                            "title": p["name"][:20], 
                                            "description": f"₹{p['price']:.0f} • Stock: {p['stock']}"
                                        } for p in prod_dicts
                                    ]
                                }
                            ]
                            reply = {
                                "type": "list",
                                "body": "⚠️ This product is no longer available. Please select another product:",
                                "button_text": "View Products",
                                "sections": sections,
                                "header": f"📦 Products in {selected_cat}"
                            }
                        else:
                            session_data["selected_product"] = selected_prod
                            logger.info(f"[STATE] Selected product saved: {selected_prod['name']}")
                            logger.info(f"[STATE] Transitioning to quantity selection")
                            guided_state = "order_select_quantity"
                            reply = {
                                "type": "button",
                                "body": f"🛒 You selected: *{selected_prod['name']}* (₹{selected_prod['price']:.0f})\n\nPlease select quantity:",
                                "buttons": [
                                    {"id": "qty_1", "title": "1️⃣"},
                                    {"id": "qty_2", "title": "2️⃣"},
                                    {"id": "qty_custom", "title": "✍ Custom"}
                                ]
                            }
                    else:
                        sections = [
                            {
                                "title": "Products",
                                "rows": [
                                    {
                                        "id": f"product_{p['id']}", 
                                        "title": p["name"][:20], 
                                        "description": f"₹{p['price']:.0f} • Stock: {p['stock']}"
                                    } for p in products
                                ]
                            }
                        ]
                        reply = {
                            "type": "list",
                            "body": "⚠️ Invalid selection. Please select a product from the list below:",
                            "button_text": "View Products",
                            "sections": sections,
                            "header": "📦 Products"
                        }
    
                elif guided_state == "order_select_quantity":
                    if message == "qty_1":
                        qty = 1
                    elif message == "qty_2":
                        qty = 2
                    elif message == "qty_custom":
                        return "✍ Please type the quantity you want (as a number):"
                    else:
                        try:
                            qty = int(message)
                        except ValueError:
                            qty = -1
                        
                    if qty <= 0:
                        logger.info(f"[GUIDED] Invalid quantity entered: {message}")
                        reply = "⚠️ Please enter a valid positive number for quantity (e.g. 1, 2, 3...):"
                    else:
                        logger.info(f"[GUIDED] Quantity entered: {qty}")
                        selected_prod = session_data["selected_product"]
                        
                        # Update cart
                        product_dict = {
                            "id": selected_prod["id"],
                            "name": selected_prod["name"],
                            "price": selected_prod["price"],
                            "stock": selected_prod["stock"],
                            "max_qty_per_order": selected_prod["stock"]
                        }
                        
                        cart, result = OrderEngine.cart_add(cart, product_dict, qty)
                        
                        # Transition to Cart Review
                        guided_state = "order_cart_review"
                        
                        summary = OrderEngine.cart_summary(cart)
                        cart_lines = "\n".join(f"• {i['qty']}x {i['name']} (₹{i['unit_price']:.0f} each) - ₹{i['subtotal']:.0f}" for i in summary.items)
                        
                        reply = {
                            "type": "button",
                            "body": f"🛒 *Your Cart*\n{cart_lines}\n\nSubtotal: *₹{summary.total:.0f}*\n\nPlease select an option:",
                            "buttons": [
                                {"id": "btn_checkout", "title": "✅ Checkout"},
                                {"id": "btn_edit_cart", "title": "✏ Edit Cart"},
                                {"id": "btn_add_more", "title": "➕ Add More"}
                            ]
                        }
    
                elif guided_state == "order_cart_review":
                    if message == "btn_checkout":
                        # Go to Delivery Selection
                        guided_state = "order_delivery_type"
                        reply = {
                            "type": "button",
                            "body": "🛵 *Choose Delivery Method*\nPlease select:",
                            "buttons": [
                                {"id": "btn_pickup", "title": "🏪 Pickup"},
                                {"id": "btn_delivery", "title": "🛵 Delivery"}
                            ]
                        }
                    elif message == "btn_edit_cart":
                        # Go to edit select
                        summary = OrderEngine.cart_summary(cart)
                        
                        session_data["cart_items_to_edit"] = summary.items
                        guided_state = "order_cart_edit_select"
                        
                        sections = [
                            {
                                "title": "Cart Items",
                                "rows": [
                                    {
                                        "id": f"edit_{idx}", 
                                        "title": i["name"][:20], 
                                        "description": f"Qty: {i['qty']} • Subtotal: ₹{i['subtotal']:.0f}"
                                    } for idx, i in enumerate(summary.items)
                                ]
                            }
                        ]
                        reply = {
                            "type": "list",
                            "body": "Select an item to edit or remove below:",
                            "button_text": "View Items",
                            "sections": sections,
                            "header": "✏️ Edit Cart"
                        }
                    elif message == "btn_add_more":
                        # Add more products: Go back to categories
                        items = db.query(models.InventoryItem).filter(
                            models.InventoryItem.shop_id == shop_id,
                            models.InventoryItem.quantity > 0
                        ).all()
                        
                        categories = sorted(list(set(item.category for item in items if item.category)))
                        if not categories:
                            categories = ["General"]
                            
                        session_data["categories"] = categories
                        guided_state = "order_select_category"
                        
                        sections = [
                            {
                                "title": "Categories",
                                "rows": [
                                    {
                                        "id": f"category_{idx}", 
                                        "title": cat[:20], 
                                        "description": f"View items in {cat}"
                                    } for idx, cat in enumerate(categories)
                                ]
                            }
                        ]
                        reply = {
                            "type": "list",
                            "body": "Select a category below:",
                            "button_text": "View Categories",
                            "sections": sections,
                            "header": "🛍️ Select Category"
                        }
                    elif message == "4" or message_lower == "cancel":
                        guided_state = "idle"
                        session_data = {}
                        cart = []
                        reply = "❌ Order cancelled."
                    else:
                        summary = OrderEngine.cart_summary(cart)
                        cart_lines = "\n".join(f"• {i['qty']}x {i['name']} (₹{i['unit_price']:.0f} each) - ₹{i['subtotal']:.0f}" for i in summary.items)
                        reply = {
                            "type": "button",
                            "body": f"⚠️ Invalid selection. Please use the buttons below:\n\n🛒 *Your Cart*\n{cart_lines}\n\nSubtotal: *₹{summary.total:.0f}*",
                            "buttons": [
                                {"id": "btn_checkout", "title": "✅ Checkout"},
                                {"id": "btn_edit_cart", "title": "✏ Edit Cart"},
                                {"id": "btn_add_more", "title": "➕ Add More"}
                            ]
                        }
    
                elif guided_state == "order_cart_edit_select":
                    edit_items = session_data.get("cart_items_to_edit", [])
                    
                    selected_item = None
                    # Try matching by ID (from list reply)
                    if message.startswith("edit_"):
                        try:
                            idx = int(message.split("_")[1])
                            if 0 <= idx < len(edit_items):
                                selected_item = edit_items[idx]
                        except ValueError:
                            pass
                            
                        if selected_item:
                            session_data["editing_item"] = selected_item
                            guided_state = "order_cart_edit_qty"
                            reply = {
                                "type": "button",
                                "body": f"✏️ Editing *{selected_item['name']}* (Current Quantity: {selected_item['qty']})\n\nPlease select an action:",
                                "buttons": [
                                    {"id": "action_increase", "title": "➕ Increase"},
                                    {"id": "action_decrease", "title": "➖ Decrease"},
                                    {"id": "action_remove", "title": "🗑 Remove"}
                                ]
                            }
                        else:
                            sections = [
                                {
                                    "title": "Cart Items",
                                    "rows": [
                                        {
                                            "id": f"edit_{idx}", 
                                            "title": i["name"][:20], 
                                            "description": f"Qty: {i['qty']} • Subtotal: ₹{i['subtotal']:.0f}"
                                        } for idx, i in enumerate(edit_items)
                                    ]
                                }
                            ]
                            reply = {
                                "type": "list",
                                "body": "⚠️ Invalid selection. Select an item to edit or remove below:",
                                "button_text": "View Items",
                                "sections": sections,
                                "header": "✏️ Edit Cart"
                            }
    
                elif guided_state == "order_cart_edit_qty":
                    editing_item = session_data["editing_item"]
                    current_qty = editing_item["qty"]
                    
                    # Handle buttons
                    if message == "action_increase":
                        qty = current_qty + 1
                    elif message == "action_decrease":
                        qty = max(0, current_qty - 1)
                    elif message == "action_remove":
                        qty = 0
                    else:
                        try:
                            qty = int(message)
                        except ValueError:
                            qty = -1
                            
                    if qty < 0:
                        reply = "⚠️ Please enter a valid non-negative number (e.g. 0 to remove, 1, 2...):"
                    else:
                        
                        if qty == 0:
                            # Remove item
                            cart = [i for i in cart if i["product_id"] != editing_item["product_id"]]
                        else:
                            # Update quantity
                            for i in cart:
                                if i["product_id"] == editing_item["product_id"]:
                                    i["quantity"] = qty
                                    i["qty"] = qty
                                    i["subtotal"] = round(i["unit_price"] * qty, 2)
                                    
                        guided_state = "order_cart_review"
                        
                        summary = OrderEngine.cart_summary(cart)
                        if summary.is_empty:
                            # Cart became empty
                            guided_state = "idle"
                            session_data = {}
                            session.category = "idle"
                            reply = "🛒 Your cart is now empty. Send any message to start a new request."
                        else:
                            cart_lines = "\n".join(f"• {i['qty']}x {i['name']} (₹{i['unit_price']:.0f} each) - ₹{i['subtotal']:.0f}" for i in summary.items)
                            reply = (
                                f"🛒 *Your Current Cart*\n"
                                f"----------------------------------\n"
                                f"{cart_lines}\n"
                                f"----------------------------------\n"
                                f"Total Items: *{sum(i['qty'] for i in summary.items)}*\n"
                                f"Subtotal: *₹{summary.total:.0f}*\n\n"
                                f"Please select an option:\n"
                                f"1️⃣ Confirm Order (Checkout)\n"
                                f"2️⃣ Edit Cart (Modify quantities/Remove)\n"
                                f"3️⃣ Add another product\n"
                                f"4️⃣ Cancel Order"
                            )
    
                elif guided_state == "order_delivery_type":
                    if message == "btn_pickup":
                        session_data["delivery_mode"] = "pickup"
                        guided_state = "order_pickup_collect_name"
                        reply = "👤 Please enter your name for the pickup:"
                    elif message == "btn_delivery":
                        session_data["delivery_mode"] = "delivery"
                        guided_state = "order_delivery_collect_name"
                        reply = "👤 Please enter your name for the delivery:"
                    else:
                        reply = {
                            "type": "button",
                            "body": "⚠️ Invalid selection. Please choose a delivery method:",
                            "buttons": [
                                {"id": "btn_pickup", "title": "🏪 Pickup"},
                                {"id": "btn_delivery", "title": "🛵 Delivery"}
                            ]
                        }
    
                elif guided_state == "order_pickup_collect_name":
                    session_data["customer_name"] = message
                    guided_state = "order_final_confirmation"
                    
                    # Show review screen
                    summary = OrderEngine.cart_summary(cart)
                    cart_lines = "\n".join(f"• {i['qty']}x {i['name']} - ₹{i['subtotal']:.0f}" for i in summary.items)
                    
                    now_in = datetime.now()
                    date_str = now_in.strftime("%d-%m-%Y")
                    time_str = now_in.strftime("%I:%M %p")
                    
                    reply = {
                        "type": "button",
                        "body": f"📋 *FINAL ORDER REVIEW*\n\n👤 *Name:* {session_data['customer_name']}\n📦 *Method:* Pickup\n\nItems:\n{cart_lines}\n\nTotal: *₹{summary.total:.0f}*\n\nPlease confirm:",
                        "buttons": [
                            {"id": "btn_confirm_order", "title": "✅ Confirm Order"},
                            {"id": "btn_edit_order", "title": "✏ Edit Order"},
                            {"id": "btn_cancel_order", "title": "❌ Cancel"}
                        ]
                    }
    
                elif guided_state == "order_delivery_collect_name":
                    session_data["customer_name"] = message
                    guided_state = "order_delivery_collect_address"
                    reply = "📍 Please enter your delivery address:"
    
                elif guided_state == "order_delivery_collect_address":
                    session_data["customer_address"] = message
                    guided_state = "order_delivery_collect_note"
                    reply = "📝 Please enter any landmark, floor, or special notes (or reply *none* to skip):"
    
                elif guided_state == "order_delivery_collect_note":
                    if message_lower == "none":
                        session_data["customer_note"] = ""
                    else:
                        session_data["customer_note"] = message
                        
                    guided_state = "order_final_confirmation"
                    
                    # Show review screen
                    summary = OrderEngine.cart_summary(cart)
                    cart_lines = "\n".join(f"• {i['qty']}x {i['name']} - ₹{i['subtotal']:.0f}" for i in summary.items)
                    
                    now_in = datetime.now()
                    date_str = now_in.strftime("%d-%m-%Y")
                    time_str = now_in.strftime("%I:%M %p")
                    
                    note_str = f"📝 *Note:* {session_data['customer_note']}\n" if session_data['customer_note'] else ""
                    reply = {
                        "type": "button",
                        "body": f"📋 *FINAL ORDER REVIEW*\n\nItems:\n{cart_lines}\n\nTotal: *₹{summary.total:.0f}*\n\nPlease confirm:",
                        "buttons": [
                            {"id": "btn_confirm_order", "title": "✅ Confirm Order"},
                            {"id": "btn_edit_order", "title": "✏ Edit Order"},
                            {"id": "btn_cancel_order", "title": "❌ Cancel"}
                        ]
                    }
    
                elif guided_state == "order_final_confirmation":
                    if message == "btn_confirm_order":
                        logger.info(f"[GUIDED] User confirmed order for {customer_phone}")
                        try:
                            # PLACE ORDER
                            b_id = f"LEV-{str(uuid.uuid4())[:8].upper()}"
                            o_id = generate_order_id()
                            
                            logger.info(f"[CHECKOUT] Creating order. Booking ID: {b_id}, Order ID: {o_id}")
                            
                            profile = CustomerProfileEngine.get_or_create(db, shop_id, customer_phone)
                            profile.customer_name = session_data["customer_name"]
                            db.commit()
                            logger.info(f"[CHECKOUT] Customer profile updated.")
                            
                            summary = OrderEngine.cart_summary(cart)
                            method = session_data["delivery_mode"].upper()
                            address = session_data.get("customer_address", "PICKUP") if method == "DELIVERY" else "PICKUP"
                            notes = session_data.get("customer_note", "")
                            
                            product_summary = "\n".join([f"{i['qty']}x {i['name']} - ₹{i['subtotal']:.0f}" for i in summary.items])
                            
                            logger.info(f"[CHECKOUT] Saving order object")
                            new_order = models.Order(
                                shop_id=shop_id,
                                customer_id=None,
                                booking_id=b_id,
                                order_id=o_id,
                                customer_name=session_data["customer_name"],
                                phone=customer_phone,
                                total_amount=summary.total,
                                status="PENDING",
                                address=address,
                                delivery_type=method,
                                product=product_summary[:200],
                                notes=notes,
                                created_at=datetime.now(timezone.utc),
                                updated_at=datetime.now(timezone.utc)
                            )
                            db.add(new_order)
                            db.flush()
                            logger.info(f"[CHECKOUT] Order flushed to DB. Generated ID: {new_order.id}")
                            
                            logger.info(f"[CHECKOUT] Saving order items. Adding {len(summary.items)} items.")
                            for item in summary.items:
                                p_id = item.get("product_id") or item.get("id")
                                logger.info(f"[CHECKOUT] Adding item: {item['name']} (ID: {p_id})")
                                
                                # Requirement 5: Checkout Pipeline Hardening
                                db_prod = db.query(models.InventoryItem).filter(models.InventoryItem.id == p_id).first()
                                if not db_prod:
                                    logger.error(f"[CHECKOUT] Product {p_id} not found in DB at checkout!")
                                    db.rollback()
                                    return "🙏 One or more items in your cart are no longer available. Please try again."
                                
                                if db_prod.quantity < item["quantity"]:
                                    logger.error(f"[CHECKOUT] Product {p_id} has insufficient stock ({db_prod.quantity} < {item['quantity']})")
                                    db.rollback()
                                    return f"🙏 Sorry, *{db_prod.name}* has insufficient stock. Available: {db_prod.quantity}. Please edit your cart."
                                
                                oi = models.OrderItem(
                                    order_id=new_order.id,
                                    product_id=p_id,
                                    name=item["name"],
                                    price=item["unit_price"],
                                    quantity=item["quantity"],
                                    subtotal=item["subtotal"]
                                )
                                db.add(oi)
                                
                            db.commit()
                            db.refresh(new_order)
                            logger.info(f"[CHECKOUT] Commit success. Order and items saved.")
                            
                            # Unified Conversation + Order Experience
                            try:
                                active_conversation = db.query(models.ConversationSession).filter(
                                    models.ConversationSession.shop_id == shop_id,
                                    models.ConversationSession.customer_phone == customer_phone,
                                    models.ConversationSession.conversation_type == "ORDER",
                                    models.ConversationSession.status.in_(["NEW", "ONGOING", "WAITING_CUSTOMER"])
                                ).first()
                                
                                if not active_conversation:
                                    ord_num = models.ConversationSession.generate_unique_order_number(db)
                                    category_id = get_auto_category(db, shop_id, customer_phone, "ORDER")
                                    active_conversation = models.ConversationSession(
                                        shop_id=shop_id,
                                        customer_name=session_data["customer_name"],
                                        customer_phone=customer_phone,
                                        status="NEW",
                                        inquiry_number=ord_num,
                                        conversation_type="ORDER",
                                        category_id=category_id
                                    )
                                    db.add(active_conversation)
                                    db.flush()
                                else:
                                    active_conversation.status = "NEW"
                                    
                                order_payload = {
                                    "type": "order_card",
                                    "order_id": new_order.id,
                                    "booking_id": new_order.booking_id,
                                    "total_amount": float(new_order.total_amount),
                                    "status": new_order.status,
                                    "items": [{"name": i["name"], "qty": i["quantity"]} for i in summary.items]
                                }
                                
                                order_msg = models.ConversationMessage(
                                    session_id=active_conversation.id,
                                    sender_type="SYSTEM",
                                    message=json.dumps(order_payload)
                                )
                                db.add(order_msg)
                                active_conversation.updated_at = datetime.now(timezone.utc)
                                active_conversation.last_message_at = datetime.now(timezone.utc)
                                db.commit()
                                from .sse import broadcast_event
                                broadcast_event(shop_id, "conversation_updated")
                            except Exception as e:
                                db.rollback()
                                logger.error(f"[ORDER CONVO LINK ERROR] {e}")

                            # Trigger production-grade centralized notification
                            try:
                                from .order_notification_service import OrderNotificationService
                                OrderNotificationService.send_order_created_message(new_order, db)
                            except Exception as notify_err:
                                logger.error(f"[CHECKOUT] Centralized notification failed to send: {notify_err}")
                            
                        except Exception as e:
                            import traceback
                            logger.error(f"[CHECKOUT] CRITICAL FAILURE: {e}")
                            logger.error(traceback.format_exc())
                            db.rollback()
                            return "🙏 We are experiencing an issue processing your order. Our team has been notified. Your cart is safe."
                        
                        reply = ""
                        
                        # Clean session state
                        guided_state = "idle"
                        session_data = {}
                        cart = []
                        session.category = "idle"
                        
                        # Broadcast updates
                        logger.info(f"[GUIDED] Broadcasting events for Shop {shop_id}")
                        broadcast_event(shop_id, "pending_updated")
                        broadcast_event(shop_id, "new_order")
                        
                    elif message == "2" or message_lower == "edit":
                        # Back to Cart Review
                        guided_state = "order_cart_review"
                        summary = OrderEngine.cart_summary(cart)
                        cart_lines = "\n".join(f"• {i['qty']}x {i['name']} (₹{i['unit_price']:.0f} each) - ₹{i['subtotal']:.0f}" for i in summary.items)
                        reply = {
                            "type": "button",
                            "body": f"🛒 *Your Cart*\n{cart_lines}\n\nSubtotal: *₹{summary.total:.0f}*\n\nPlease select an option:",
                            "buttons": ["✅ Checkout", "✏ Edit Cart", "➕ Add More"]
                        }
                    elif message == "3" or message_lower == "cancel":
                        guided_state = "idle"
                        session_data = {}
                        cart = []
                        reply = "❌ Order cancelled."
                    else:
                        summary = OrderEngine.cart_summary(cart)
                        cart_lines = "\n".join(f"• {i['qty']}x {i['name']} - ₹{i['subtotal']:.0f}" for i in summary.items)
                        now_in = datetime.now()
                        date_str = now_in.strftime("%d-%m-%Y")
                        time_str = now_in.strftime("%I:%M %p")
                        note_str = f"📝 *Note:* {session_data['customer_note']}\n" if session_data.get('customer_note') else ""
                        addr_str = f"📍 *Address:* {session_data['customer_address']}\n" if session_data.get('delivery_mode') == 'delivery' else ""
                        
                        reply = {
                            "type": "button",
                            "body": f"⚠️ Invalid choice.\n\n📋 *FINAL ORDER REVIEW*\n\n👤 *Name:* {session_data['customer_name']}\n📦 *Method:* {session_data['delivery_mode'].capitalize()}\n\nItems:\n{cart_lines}\n\nTotal: *₹{summary.total:.0f}*\n\nPlease confirm:",
                            "buttons": [
                                {"id": "btn_confirm_order", "title": "✅ Confirm Order"},
                                {"id": "btn_edit_order", "title": "✏ Edit Order"},
                                {"id": "btn_cancel_order", "title": "❌ Cancel"}
                            ]
                        }

                elif guided_state == "awaiting_booking_lookup":
                    booking_id_input = message.strip().upper()
                    logger.info(f"[TRACK_ORDER] booking_lookup={booking_id_input}")
                    
                    order = db.query(models.Order).filter(
                        models.Order.shop_id == shop_id,
                        models.Order.booking_id == booking_id_input
                    ).first()
                    
                    if not order:
                        # Maybe they omitted the LEV- prefix? Let's check
                        if not booking_id_input.startswith("LEV-") and len(booking_id_input) == 8:
                            potential_id = f"LEV-{booking_id_input}"
                            logger.info(f"[TRACK_ORDER] Trying with LEV- prefix: {potential_id}")
                            order = db.query(models.Order).filter(
                                models.Order.shop_id == shop_id,
                                models.Order.booking_id == potential_id
                            ).first()
                            
                    if not order:
                        logger.warning(f"[TRACK_ORDER] invalid_booking_id={booking_id_input}")
                        reply = "⚠️ Invalid Booking ID. Please verify your code and enter it again:"
                        # Keep state as awaiting_booking_lookup
                    elif order.phone != customer_phone:
                        logger.warning(f"[TRACK_ORDER] ownership_verified=FAILED for booking {booking_id_input}")
                        reply = "🚫 Access denied. This order does not belong to your phone number."
                        guided_state = "idle"
                        session_data = {}
                    else:
                        logger.info(f"[TRACK_ORDER] ownership_verified=SUCCESS for booking {booking_id_input}")
                        logger.info(f"[TRACK_ORDER] completed_order_lookup status={order.status}")
                        order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
                        if order_items:
                            items_str = "\n".join(f"• {item.quantity}x {item.name}" for item in order_items)
                        else:
                            items_str = order.product or "No items listed."
                        
                        status_lbl = {
                            "PENDING": "Pending 🟡",
                            "CONFIRMED": "Accepted 🟢",
                            "DELIVERED": "Completed ✅",
                            "CANCELLED": "Rejected ❌"
                        }.get(order.status, order.status)
                        
                        date_str = order.created_at.strftime("%d-%m-%Y %I:%M %p")
                        
                        reply = (
                            f"🧾 *Order Details*\n\n"
                            f"🔖 *Booking ID:* {order.booking_id}\n"
                            f"🧾 *Order Number:* #{order.order_id}\n"
                            f"📦 *Status:* {status_lbl}\n"
                            f"📅 *Date:* {date_str}\n"
                            f"💰 *Amount:* ₹{int(order.total_amount)}\n\n"
                            f"🛍️ *Items:*\n{items_str}\n\n"
                            f"🚚 *Delivery Information:*\n"
                            f"👤 Name: {order.customer_name}\n"
                            f"📍 Address: {order.address}"
                        )
                        if order.notes:
                            reply += f"\n📝 Note: {order.notes}"
                        
                        guided_state = "idle"
                        session_data = {}

                elif guided_state == "track_order_select":
                    # They might have typed something else or a booking ID instead of choosing from the list.
                    active_orders = db.query(models.Order).filter(
                        models.Order.shop_id == shop_id,
                        models.Order.phone == customer_phone,
                        models.Order.status.in_(["PENDING", "CONFIRMED"])
                    ).order_by(models.Order.created_at.desc()).all()
                    
                    if active_orders:
                        sections = [
                            {
                                "title": "Your Active Orders",
                                "rows": [
                                    {
                                        "id": f"track_order_{order.id}",
                                        "title": f"#{order.order_id}",
                                        "description": f"{order.booking_id} • {'Pending' if order.status == 'PENDING' else 'Accepted'} • ₹{int(order.total_amount)}"
                                    } for order in active_orders
                                ]
                            }
                        ]
                        reply = {
                            "type": "list",
                            "body": "⚠️ Invalid selection. Please choose an order from the list below, or type a completed order's Booking ID directly to look up details:",
                            "button_text": "View Orders",
                            "sections": sections,
                            "header": "🔍 Track Orders"
                        }
                    else:
                        reply = "📦 No active orders found. Type 'cancel' to return to main menu."
                        guided_state = "idle"
    
            except Exception as e:
                import traceback
                logger.error(f"[STATE] CRITICAL FAILURE in state machine: {e}")
                logger.error(traceback.format_exc())
                logger.error(f"[STATE] Current session state: {guided_state}")
                logger.error(f"[STATE] Incoming action ID: {message}")
                reply = f"🙏 State Machine Error at state '{guided_state}'. Please type 'cancel' to reset."
            # 7. Persist session state
            logger.info(f"[GUIDED] Persisting session state: {guided_state}, cart items: {len(cart)}")
            # Store dynamic timeout metadata as per Rule 2
            timeout_mins = 5
            if guided_state.startswith("order_"):
                timeout_mins = 15
            elif guided_state.startswith("inquiry_"):
                timeout_mins = 30
                
            session.collected_fields = {
                "guided_state": guided_state,
                "session_data": session_data,
                "cart": cart,
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "context_timeout_minutes": timeout_mins
            }
            flag_modified(session, "collected_fields")
            session.category = guided_state
            session.updated_at = datetime.now(timezone.utc)
            
            logger.info(f"[GUIDED] Attempting DB commit for session {session.session_id}")
            db.commit()
            logger.info(f"[GUIDED] DB commit successful.")
            
            return reply

        except Exception as e:
            import traceback
            logger.error(f"[GUIDED CONVERSATION CRASH] {e}\n{traceback.format_exc()}")
            db.rollback()
            return f"🙏 System Error during {guided_state}. Cart safe. Please try again or type 'cancel'."
