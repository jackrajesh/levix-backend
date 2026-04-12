from fastapi import APIRouter, Request
import requests
import os
from dotenv import load_dotenv

# Load env variables (safe for local; Render ignores it)
load_dotenv()

router = APIRouter()

APP_ID = os.getenv("META_APP_ID")
APP_SECRET = os.getenv("META_APP_SECRET")
REDIRECT_URI = os.getenv("META_REDIRECT_URI")


@router.get("/auth/meta/callback")
async def meta_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return {"error": "No code received"}

    # =========================
    # STEP 1: Exchange code → access token
    # =========================
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"

    params = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    token_res = requests.get(token_url, params=params)
    token_data = token_res.json()

    access_token = token_data.get("access_token")

    if not access_token:
        return {"error": "Token failed", "data": token_data}

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # =========================
    # STEP 2: Get Businesses
    # =========================
    business_url = "https://graph.facebook.com/v19.0/me/businesses"

    business_res = requests.get(business_url, headers=headers)
    business_data = business_res.json()

    businesses = business_data.get("data", [])

    if not businesses:
        return {"error": "No businesses found", "business_data": business_data}

    # 🔥 Select correct business (by name)
    business_id = None
    for b in businesses:
        if b.get("name") == "Levix":
            business_id = b.get("id")
            break

    if not business_id:
        return {
            "error": "Levix business not found",
            "available_businesses": businesses
        }

    # =========================
    # STEP 3: Get WABA
    # =========================
    waba_url = f"https://graph.facebook.com/v19.0/{business_id}/owned_whatsapp_business_accounts"

    waba_res = requests.get(waba_url, headers=headers)
    waba_data = waba_res.json()

    waba_list = waba_data.get("data", [])

    if not waba_list:
        return {
            "error": "No WABA found",
            "waba_data": waba_data
        }

    waba_id = waba_list[0].get("id")

    # =========================
    # STEP 4: Get Phone Numbers
    # =========================
    phone_url = f"https://graph.facebook.com/v19.0/{waba_id}/phone_numbers"

    phone_res = requests.get(phone_url, headers=headers)
    phone_data = phone_res.json()

    phone_list = phone_data.get("data", [])

    if not phone_list:
        return {
            "error": "No phone numbers found",
            "phone_data": phone_data
        }

    phone_number_id = phone_list[0].get("id")
    display_number = phone_list[0].get("display_phone_number")

    # =========================
    # FINAL RESPONSE (DEBUG)
    # =========================
    return {
        "message": "WhatsApp integration success",
        "access_token": access_token,
        "business_id": business_id,
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "display_phone_number": display_number,
        "state": state
    }