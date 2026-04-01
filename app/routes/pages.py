from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

@router.get("/", response_class=FileResponse)
async def get_login():
    return FileResponse("templates/login.html")

@router.get("/dashboard", response_class=FileResponse)
async def get_dashboard():
    return FileResponse("templates/dashboard.html")

@router.get("/forgot-password", response_class=FileResponse)
async def get_forgot_password():
    return FileResponse("templates/forgot-password.html")

@router.get("/reset-password", response_class=FileResponse)
async def get_reset_password():
    return FileResponse("templates/reset-password.html")
