import logging
from sqlalchemy.orm import Session
from .. import models
from .whatsapp_service import send_whatsapp_message

logger = logging.getLogger("levix.order_notify")

class OrderNotificationService:

    @staticmethod
    def _get_shop_and_validate(db: Session, order: models.Order):
        """
        Helper method to fetch shop and validate order details.
        """
        if not order:
            logger.error("[ORDER_NOTIFY] Cannot send notification: Order object is None")
            return None, None
            
        if not order.phone:
            logger.warning(f"[ORDER_NOTIFY] Missing customer phone number for order {order.booking_id}")
            return None, None
            
        shop = db.query(models.Shop).filter(models.Shop.id == order.shop_id).first()
        if not shop:
            logger.error(f"[ORDER_NOTIFY] Shop {order.shop_id} not found for order {order.booking_id}")
            return None, None
            
        return shop, order.phone

    @classmethod
    def send_order_created_message(cls, order: models.Order, db: Session) -> bool:
        """
        Sends WhatsApp notification when an order is created.
        """
        try:
            logger.info(f"[ORDER_NOTIFY] Sending created message for {order.booking_id if order else 'None'}")
            shop, phone = cls._get_shop_and_validate(db, order)
            if not shop or not phone:
                return False
                
            booking_id = order.booking_id
            order_number = order.order_id
            total = int(order.total_amount)
            
            message = (
                f"✅ *Your order has been received successfully.*\n\n"
                f"📦 *Booking ID:* {booking_id}\n"
                f"🧾 *Order Number:* #{order_number}\n"
                f"💰 *Total:* ₹{total}\n\n"
                f"⏳ *Your order is currently under review by the store.*\n\n"
                f"🔔 *You will automatically receive updates when:*\n"
                f"• Order is accepted\n"
                f"• Order is rejected\n"
                f"• Order is completed\n\n"
                f"Thank you for choosing LEVIX 🙌"
            )
            
            send_whatsapp_message(shop, phone, message)
            logger.info(f"[ORDER_NOTIFY] Created message sent successfully for {booking_id}")
            return True
        except Exception as e:
            logger.error(f"[ORDER_NOTIFY] Failed to send created message for order: {e}")
            return False

    @classmethod
    def send_order_accepted_message(cls, order: models.Order, db: Session) -> bool:
        """
        Sends WhatsApp notification when an order is accepted.
        """
        try:
            logger.info(f"[ORDER_NOTIFY] Sending accepted message for {order.booking_id if order else 'None'}")
            shop, phone = cls._get_shop_and_validate(db, order)
            if not shop or not phone:
                return False
                
            booking_id = order.booking_id
            order_number = order.order_id
            delivery_type = "Delivery" if order.delivery_type == "DELIVERY" else "Pickup"
            total = int(order.total_amount)
            
            message = (
                f"🟢 *Your order has been ACCEPTED!*\n\n"
                f"📦 *Booking ID:* {booking_id}\n"
                f"🧾 *Order Number:* #{order_number}\n\n"
                f"🏪 *LEVIX has started preparing your order.*\n\n"
                f"📍 *Delivery Type:* {delivery_type}\n"
                f"💰 *Amount:* ₹{total}\n\n"
                f"Thank you for shopping with us 🙌"
            )
            
            send_whatsapp_message(shop, phone, message)
            logger.info(f"[ORDER_NOTIFY] Accepted message sent successfully for {booking_id}")
            return True
        except Exception as e:
            logger.error(f"[ORDER_NOTIFY] Failed to send accepted message for order: {e}")
            return False

    @classmethod
    def send_order_rejected_message(cls, order: models.Order, db: Session) -> bool:
        """
        Sends WhatsApp notification when an order is rejected (cancelled).
        """
        try:
            logger.info(f"[ORDER_NOTIFY] Sending rejected message for {order.booking_id if order else 'None'}")
            shop, phone = cls._get_shop_and_validate(db, order)
            if not shop or not phone:
                return False
                
            booking_id = order.booking_id
            order_number = order.order_id
            
            message = (
                f"🔴 *Your order has been declined by the store.*\n\n"
                f"📦 *Booking ID:* {booking_id}\n"
                f"🧾 *Order Number:* #{order_number}\n\n"
                f"If you have questions, please contact the store directly."
            )
            
            send_whatsapp_message(shop, phone, message)
            logger.info(f"[ORDER_NOTIFY] Rejected message sent successfully for {booking_id}")
            return True
        except Exception as e:
            logger.error(f"[ORDER_NOTIFY] Failed to send rejected message for order: {e}")
            return False

    @classmethod
    def send_order_completed_message(cls, order: models.Order, db: Session) -> bool:
        """
        Sends WhatsApp notification when an order is completed (delivered).
        """
        try:
            logger.info(f"[ORDER_NOTIFY] Sending completed message for {order.booking_id if order else 'None'}")
            shop, phone = cls._get_shop_and_validate(db, order)
            if not shop or not phone:
                return False
                
            booking_id = order.booking_id
            order_number = order.order_id
            
            message = (
                f"✅ *Your order has been completed successfully!*\n\n"
                f"📦 *Booking ID:* {booking_id}\n"
                f"🧾 *Order Number:* #{order_number}\n\n"
                f"🙏 Thank you for shopping with LEVIX.\n\n"
                f"We hope to serve you again soon!"
            )
            
            send_whatsapp_message(shop, phone, message)
            logger.info(f"[ORDER_NOTIFY] Completed message sent successfully for {booking_id}")
            return True
        except Exception as e:
            logger.error(f"[ORDER_NOTIFY] Failed to send completed message for order: {e}")
            return False
