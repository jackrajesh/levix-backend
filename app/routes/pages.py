from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

@router.get("/", response_class=FileResponse)
async def get_root():
    return FileResponse("templates/index.html")

@router.get("/about-levix", response_class=FileResponse)
async def get_about():
    return FileResponse("templates/about-levix.html")

@router.get("/levix-brand", response_class=FileResponse)
async def get_brand_typo():
    return FileResponse("templates/levix-brand.html")

@router.get("/login", response_class=FileResponse)
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

@router.get("/robots.txt", include_in_schema=False)
async def get_robots():
    return FileResponse("static/robots.txt")

@router.get("/sitemap.xml", include_in_schema=False)
async def get_sitemap():
    return FileResponse("static/sitemap.xml")

@router.get("/blog", response_class=FileResponse)
async def get_blog_home():
    return FileResponse("templates/blog/index.html")

@router.get("/blog/whatsapp-ordering-for-restaurants", response_class=FileResponse)
async def get_blog_1():
    return FileResponse("templates/blog/post.html")

@router.get("/blog/how-small-shops-use-ai", response_class=FileResponse)
async def get_blog_2():
    return FileResponse("templates/blog/post.html")

@router.get("/blog/best-whatsapp-order-bot-india", response_class=FileResponse)
async def get_blog_3():
    return FileResponse("templates/blog/post.html")

@router.get("/blog/how-to-grow-local-business-online", response_class=FileResponse)
async def get_blog_4():
    return FileResponse("templates/blog/post.html")

@router.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    return FileResponse("static/favicon.png")
