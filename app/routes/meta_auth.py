from fastapi import APIRouter, Request
import requests

router = APIRouter()

APP_ID = "26549149854679745"
APP_SECRET = "02b387474682544dff4b7144b3d5543a"
REDIRECT_URI = "https://levixapp.in/auth/meta/callback"


@router.get("/auth/meta/callback")
async def meta_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return {"error": "No code received"}

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

    return {
        "message": "Token received",
        "access_token": access_token,
        "state": state
    }