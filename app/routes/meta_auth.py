from fastapi import APIRouter, Request
import requests
import os
from dotenv import load_dotenv

# Load env variables
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

    # STEP 1: Exchange code → access token
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"

    params = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    response = requests.get(token_url, params=params)
    data = response.json()

    access_token = data.get("access_token")

    if not access_token:
        return {"error": "Token failed", "data": data}

    # STEP 2: Fetch businesses (next stage)
    business_url = "https://graph.facebook.com/v19.0/me/businesses"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    business_res = requests.get(business_url, headers=headers)
    business_data = business_res.json()

    return {
        "message": "Token received",
        "access_token": access_token,
        "business_data": business_data,
        "state": state
    }