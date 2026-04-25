import os
import json
import logging
from typing import Dict, Any, Optional


logger = logging.getLogger("levix.order_controller")

# ══════════════════════════════════════════════════════════════════════════════
# LEVIX SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

LEVIX_SYSTEM_PROMPT = """
You are LEVIX, an AI order assistant.

Your job is to collect customer order details through a strict, step-by-step reservation flow and return structured JSON output for backend processing.

========================
TRIGGER RULE
============

* Do NOT start reservation automatically
* Start ONLY when:
  1. session.can_order = true
  2. user message = "ORDER" (case-insensitive)

* If ORDER but can_order = false:
  reply: "Ordering is currently unavailable. Please wait."

* If not ORDER and not in flow:
  respond normally (do NOT collect details)

========================
SYSTEM STATE (injected per message)
===================================

You will receive:
1. SESSION JSON: Current state (is_ordering, step, session_data, booking_id).
2. USER MESSAGE: The text sent by the customer.

RULES:
1. Strictly follow the steps: name -> phone -> address -> confirm.
2. The `booking_id` is provided by the backend and MUST NOT be changed.
3. RETURN STRICT JSON ONLY.

OUTPUT FORMAT:
{
  "reply": "message string",
  "session": {
    "shop_id": "SHOP_ID",
    "is_ordering": true/false,
    "step": "step_name",
    "can_order": true/false,
    "booking_id": "BOOKING_ID",
    "session_data": {
      "name": "string or null",
      "phone": "string or null",
      "address": "string or null",
      "product": "string or null"
    },
    "updated_at": "ISO_TIMESTAMP"
  },
  "order": null
}

========================
FAILSAFE RULES
==============

* If user types CANCEL → stop flow and return "CANCELLED" in reply.
* If input is invalid for the current step → repeat current step clearly.
* Never SKIP steps (name -> phone -> address -> confirm).
* Never collect MULTIPLE fields at once (one field per message only).
* Never create order without YES confirmation from the user.

STEP-BY-STEP FLOW:

STEP: name
* Goal: Get customer's name.
* Action: Save to session_data.name.
* Logic: Move to step "phone".
* Reply: "Thanks, [name]! What is your phone number?" (Replace [name] with the actual name).

STEP: phone
* Goal: Get customer's 10-digit phone number.
* Validation: Must be exactly 10 digits.
* Invalid Logic: If not 10 digits, set reply to "Please enter a valid 10-digit phone number." and stay on step "phone".
* Success Logic: Save to session_data.phone and move to step "address".
* Reply: "Got it! Enter your delivery address."

STEP: quantity
* Goal: Get the number of items.
* Action: Save to session_data.quantity.
* Logic: If quantity present in user message before flow, skip this.
* Reply: "How many would you like?"

STEP: address
* Goal: Get delivery address.
* Action: Save to session_data.address.
* Logic: Move to step "confirm".
* Reply: Inform the user you have all details and show the summary.

STEP: confirm
* Goal: Final verification.
* Action: Display the collected details:
  Name: [name]
  Phone: [phone]
  Address: [address]
  Product: [product]
  Qty: [quantity]
  Total: ₹[total]
  
  Ask: "Confirm your order? Type YES to confirm or NO to cancel."
  
* Logic for YES:
  - Return "CONFIRMED" in the reply text (to be intercepted by backend).
  - The backend will generate order_id, set status to pending, and provide the final confirmation message.
  
* Logic for NO:
  - Return "CANCELLED" in the reply text (to be intercepted by backend).
  - The backend will handle the cancellation.

* Else:
  - Reply: "Please type YES to confirm or NO to cancel."
"""

def handle_order_flow(session: Dict[str, Any], user_message: str) -> Dict[str, Any]:
    """
    Pure Python order flow handling (No AI Dependency).
    Steps: name -> phone -> address -> confirm
    """
    step = session.get("step")
    session_data = session.get("session_data", {})
    reply = ""

    # Normalize input
    msg_clean = user_message.strip()
    msg_upper = msg_clean.upper()

    # --- PART 2: FULL SESSION RESET (Safety) ---
    valid_steps = ["name", "phone", "address", "confirm"]
    if step not in valid_steps or not isinstance(session_data, dict):
        print(f"[SAFETY RESET] Invalid step '{step}' or corrupted session_data. Resetting.")
        session.update({
            "is_ordering": False,
            "step": None,
            "can_order": False,
            "booking_id": None,
            "session_data": {"name": None, "phone": None, "address": None, "product": None, "quantity": 1, "unit_price": 0}
        })
        return {
            "reply": "I'm sorry, something went wrong with the session. Let's start over if you need anything!",
            "session": session
        }

    if step == "name":
        session_data["name"] = msg_clean
        session["step"] = "phone"
        reply = f"Thanks, {msg_clean}! What is your phone number?"
    
    elif step == "phone":
        # Validate 10 digits
        digits = "".join(filter(str.isdigit, msg_clean))
        if len(digits) == 10:
            session_data["phone"] = digits
            # Check if quantity is already set
            if session_data.get("quantity") and int(session_data.get("quantity", 0)) > 0:
                session["step"] = "address"
                reply = "Got it! Enter your delivery address."
            else:
                session["step"] = "quantity"
                reply = "How many would you like?"
        else:
            reply = "Please enter a valid 10-digit phone number."
    
    elif step == "quantity":
        digits = "".join(filter(str.isdigit, msg_clean))
        if digits and int(digits) > 0:
            session_data["quantity"] = int(digits)
            session["step"] = "address"
            reply = "Got it! Enter your delivery address."
        else:
            reply = "Please enter a valid number for quantity."

    elif step == "address":
        session_data["address"] = msg_clean
        session["step"] = "confirm"
        
        # Build Summary
        name = session_data.get("name") or "N/A"
        phone = session_data.get("phone") or "N/A"
        qty = session_data.get("quantity") or 1
        price = session_data.get("unit_price") or 0
        total = int(qty) * float(price)
        address = msg_clean
        product = session_data.get("product") or "Selected Item"
        
        reply = (
            f"Please verify your details:\n\n"
            f"Name: {name}\n"
            f"Phone: {phone}\n"
            f"Address: {address}\n"
            f"Product: {product}\n"
            f"Qty: {qty}\n"
            f"Total: ₹{int(total) if total == int(total) else total}\n\n"
            "Confirm your order? Type YES to confirm or NO to cancel."
        )
    
    elif step == "confirm":
        if msg_upper == "YES":
            reply = "CONFIRMED"
            # Do NOT reset here, let backend do it after saving order
        elif msg_upper == "NO":
            reply = "CANCELLED"
            # Do NOT reset here, let backend do it
        else:
            reply = "Please type YES to confirm or NO to cancel."

    session["session_data"] = session_data
    return {
        "reply": reply,
        "session": session
    }

# ══════════════════════════════════════════════════════════════════════════════
# DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

from .. import models
from sqlalchemy.orm import Session as DBSession
from datetime import datetime

def get_or_create_customer_session(db: DBSession, shop_id: int, customer_phone: str) -> models.CustomerSession:
    session = db.query(models.CustomerSession).filter(
        models.CustomerSession.shop_id == shop_id,
        models.CustomerSession.customer_phone == customer_phone
    ).first()
    
    if not session:
        session = models.CustomerSession(
            shop_id=shop_id,
            customer_phone=customer_phone,
            is_ordering=False,
            session_data=json.dumps({"name": None, "phone": None, "address": None, "product": None, "quantity": 1, "unit_price": 0})
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    
    return session

def update_customer_session(db: DBSession, session_obj: models.CustomerSession, updated_session_dict: Dict[str, Any]):
    session_obj.is_ordering = updated_session_dict.get("is_ordering", False)
    session_obj.can_order = updated_session_dict.get("can_order", False)
    session_obj.step = updated_session_dict.get("step")
    session_obj.session_data = json.dumps(updated_session_dict.get("session_data", {}))
    session_obj.booking_id = updated_session_dict.get("booking_id")
    db.commit()

# --- ID GENERATORS ---
import random
import string

def generate_order_id() -> str:
    """5 digit numeric only"""
    return ''.join(random.choices(string.digits, k=5))

def generate_booking_id(db: DBSession, shop_id: int) -> str:
    """8 digit numeric only, unique inside shop"""
    while True:
        bid = ''.join(random.choices(string.digits, k=8))
        exists = db.query(models.Order).filter(models.Order.shop_id == shop_id, models.Order.booking_id == bid).first()
        if not exists:
            return bid
