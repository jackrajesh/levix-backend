import logging
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from .. import models
from .sse import broadcast_event

logger = logging.getLogger("levix.sales_engine")

class SalesEngine:
    """
    SALES ENGINE: Lead capture and priority scoring.
    """

    @staticmethod
    def analyze_revenue_potential(message: str, intent: str) -> Dict[str, Any]:
        """Detects high-value signals and sets PRIORITY according to Phase 8."""
        msg = message.lower()
        signals = []
        priority = "LOW"
        
        # 1. High Priority Signals
        if any(k in msg for k in ["wedding", "party", "bulk", "event", "corporate", "premium", "urgent", "asap", "emergency", "pcs"]):
            priority = "HIGH"
            signals.append("HIGH_VALUE_LEAD")
        
        # 2. Medium Priority Signals
        elif intent in ["ORDER_START", "RECOMMENDATION", "PRODUCT_QUERY"] or any(k in msg for k in ["dinner", "lunch", "family", "soon"]):
            priority = "MEDIUM"
            signals.append("WARM_LEAD")
            
        # 3. Low Priority
        else:
            priority = "LOW"
            signals.append("COLD_LEAD")

        return {
            "probability": 90 if priority == "HIGH" else 50 if priority == "MEDIUM" else 10,
            "signals": signals,
            "urgency": "HIGH" if "urgent" in msg else "LOW",
            "priority": priority
        }

    @staticmethod
    def create_lead(db: Session, shop_id: int, session: models.AIConversationSession, message: str, intent: str, matched_product: Any = None):
        """AI LEAD ENGINE."""
        try:
            rev_intel = SalesEngine.analyze_revenue_potential(message, intent)
            
            summary = f"[{rev_intel['priority']} PRIORITY] Customer inquiring about {matched_product.name if matched_product else message}."
            if "BULK_INTEREST" in rev_intel["signals"]:
                summary = "🔥 [BULK ORDER] " + summary

            # Metadata to store in JSON
            lead_metadata = {
                "signals": rev_intel["signals"]
            }

            # Deduplicate
            existing = db.query(models.AILead).filter(
                models.AILead.session_id == session.session_id,
                models.AILead.status == "new"
            ).first()

            if existing:
                existing.summary = summary
                existing.collected_data = lead_metadata
                existing.intent = intent
                db.commit()
                return existing

            new_lead = models.AILead(
                shop_id=shop_id,
                session_id=session.session_id,
                phone=session.customer_phone,
            customer_name=((session.collected_fields or {}).get("customer_name", "Valued Customer")),
                product_name=matched_product.name if matched_product else "Inquiry",
                intent=intent,
                summary=summary,
                collected_data=lead_metadata,
                status="new",
                source="WhatsApp"
            )
            
            db.add(new_lead)
            db.commit()
            
            logger.info(f"LEAD_CREATED: {new_lead.id} | Priority: {rev_intel['priority']}")
            
            # LIVE UPDATE
            try:
                broadcast_event(shop_id, "new_ai_lead", {
                    "id": new_lead.id,
                    "phone": new_lead.phone,
                    "summary": summary,
                    "priority": rev_intel["priority"]
                })
            except: pass
            
            return new_lead
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"[LEAD ENGINE ERROR] {e}")
            return None

    @staticmethod
    def get_upsell_suggestion(product: models.InventoryItem, db: Session, shop_id: int) -> Optional[str]:
        if not product: return None
        upsell = db.query(models.InventoryItem).filter(
            models.InventoryItem.shop_id == shop_id,
            models.InventoryItem.id != product.id,
            models.InventoryItem.quantity > 0
        ).limit(1).first()
        if upsell:
            return f"Customers also liked *{upsell.name}*. Want to add it?"
        return None

    @staticmethod
    def recover_abandoned_carts(db: Session, shop_id: int):
        """Phase 4: Abandoned Cart Recovery."""
        from datetime import datetime, timedelta, timezone
        from ..core.whatsapp import send_whatsapp_message
        
        ten_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
        
        # Find sessions with an active cart, updated > 10 mins ago, and not recovered yet
        abandoned_sessions = db.query(models.AIConversationSession).filter(
            models.AIConversationSession.shop_id == shop_id,
            models.AIConversationSession.updated_at < ten_mins_ago,
            models.AIConversationSession.collected_fields.op("->")("cart") != None
        ).all()
        
        recovered_count = 0
        for s in abandoned_sessions:
            if s.collected_fields.get("abandoned_reminder_sent") or s.collected_fields.get("last_order_token"):
                continue
                
            cart = s.collected_fields.get("cart", [])
            if not cart: continue
            
            # Send reminder
            msg = f"Hi there! You left {len(cart)} items in your cart. 🛒\nReply ORDER to complete your checkout before they run out of stock!"
            try:
                send_whatsapp_message(s.customer_phone, msg)
                s.collected_fields = {**s.collected_fields, "abandoned_reminder_sent": True}
                db.commit()
                recovered_count += 1
                logger.info(f"ABANDONED_CART_RECOVERY_SENT: {s.customer_phone}")
            except Exception as e:
                logger.error(f"Failed to send abandoned cart recovery: {e}")
                
        return recovered_count

    @staticmethod
    def get_dashboard_metrics(db: Session, shop_id: int) -> Dict[str, Any]:
        """Phase 5: Owner Dashboard Intelligence."""
        from datetime import datetime, date, timezone
        
        # 1. Daily Orders & Revenue
        today = date.today()
        daily_orders = db.query(models.Order).filter(
            models.Order.shop_id == shop_id,
            models.Order.created_at >= today
        ).all()
        
        daily_revenue = sum(o.total_amount for o in daily_orders) if daily_orders else 0
        avg_order_value = (daily_revenue / len(daily_orders)) if daily_orders else 0
        
        # 2. Top Ordered Items & Combos
        all_orders = db.query(models.Order).filter(models.Order.shop_id == shop_id).all()
        item_counts = {}
        top_combos = {}
        
        for o in all_orders:
            item_counts[o.product] = item_counts.get(o.product, 0) + o.quantity
            if " + " in o.product or "\n" in o.product:
                top_combos[o.product] = top_combos.get(o.product, 0) + o.quantity
                
        top_items = sorted(item_counts.items(), key=lambda x: -x[1])[:5]
        top_combos = sorted(top_combos.items(), key=lambda x: -x[1])[:3]

        # 3. Conversion Rate & by Hour
        sessions = db.query(models.AIConversationSession).filter(models.AIConversationSession.shop_id == shop_id).all()
        total_sessions = len(sessions)
        
        conversion_by_hour = {str(i): {"total": 0, "converted": 0} for i in range(24)}
        for s in sessions:
            hr = str(s.created_at.hour) if s.created_at else "0"
            if hr in conversion_by_hour:
                conversion_by_hour[hr]["total"] += 1
                if s.collected_fields and s.collected_fields.get("last_order_token"):
                    conversion_by_hour[hr]["converted"] += 1
                    
        sessions_with_orders = sum(1 for s in sessions if s.collected_fields and s.collected_fields.get("last_order_token"))
        conversion_rate = (sessions_with_orders / total_sessions * 100) if total_sessions > 0 else 0

        # 4. Abandoned Carts
        abandoned_sessions = sum(1 for s in sessions if s.collected_fields and s.collected_fields.get("cart") and not s.collected_fields.get("last_order_token"))
        
        # 5. Repeat Customers & Revenue
        profiles = db.query(models.CustomerProfile).filter(models.CustomerProfile.shop_id == shop_id).all()
        repeat_customers = sum(1 for p in profiles if p.visit_count > 1)
        total_customers = len(profiles)
        repeat_rate = (repeat_customers / total_customers * 100) if total_customers > 0 else 0
        
        # Approximate repeat revenue (sum of budgets or actual historic data)
        repeat_revenue = sum(p.total_orders * (p.avg_budget or avg_order_value) for p in profiles if p.visit_count > 1)

        return {
            "daily_orders": len(daily_orders),
            "daily_revenue": float(daily_revenue),
            "avg_order_value": round(float(avg_order_value), 2),
            "repeat_revenue": round(float(repeat_revenue), 2),
            "top_items": top_items,
            "top_combos": top_combos,
            "conversion_rate": round(conversion_rate, 1),
            "conversion_by_hour": conversion_by_hour,
            "abandoned_carts": abandoned_sessions,
            "repeat_customers_pct": round(repeat_rate, 1),
            "repeat_customers_count": repeat_customers
        }

    @staticmethod
    def get_admin_reports(db: Session, shop_id: int) -> Dict[str, Any]:
        """Phase 5: Admin Level Reports for Pilot Shops."""
        from datetime import datetime, timedelta, timezone
        
        # 1. Weekly Revenue
        one_week_ago = datetime.now(timezone.utc).date() - timedelta(days=7)
        weekly_orders = db.query(models.Order).filter(
            models.Order.shop_id == shop_id,
            models.Order.created_at >= one_week_ago
        ).all()
        weekly_revenue = sum(o.total_amount for o in weekly_orders)
        
        # 2. Repeat Rate
        profiles = db.query(models.CustomerProfile).filter(models.CustomerProfile.shop_id == shop_id).all()
        total_customers = len(profiles)
        repeat_customers = sum(1 for p in profiles if p.visit_count > 1)
        repeat_rate = (repeat_customers / total_customers * 100) if total_customers > 0 else 0
        
        # 3. Best Hour
        sessions = db.query(models.AIConversationSession).filter(models.AIConversationSession.shop_id == shop_id).all()
        hour_counts = {}
        for s in sessions:
            if s.collected_fields and s.collected_fields.get("last_order_token"):
                hr = s.created_at.hour if s.created_at else 0
                hour_counts[hr] = hour_counts.get(hr, 0) + 1
        best_hour = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else None
        
        # 4. Missed Requests (Unknown products)
        missed_requests = db.query(models.MissingProductRequest).filter(models.MissingProductRequest.shop_id == shop_id).order_by(models.MissingProductRequest.count.desc()).limit(5).all()
        missed_data = [{"product": m.product_name, "count": m.count} for m in missed_requests]
        
        # 5. Cancel Reasons
        cancel_events = db.query(models.AIAnalyticsEvent).filter(
            models.AIAnalyticsEvent.shop_id == shop_id,
            models.AIAnalyticsEvent.event_type == "ORDER_CANCELLED"
        ).all()
        cancel_reasons = {}
        for e in cancel_events:
            reason = e.event_data.get("reason", "Unknown") if e.event_data else "Unknown"
            cancel_reasons[reason] = cancel_reasons.get(reason, 0) + 1

        return {
            "weekly_revenue": float(weekly_revenue),
            "repeat_rate": round(repeat_rate, 1),
            "best_hour": f"{best_hour}:00" if best_hour is not None else "N/A",
            "missed_requests": missed_data,
            "cancel_reasons": cancel_reasons
        }
