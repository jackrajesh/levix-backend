from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()

# =========================================================
# BASE PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# =========================================================
# STATIC FILES
# =========================================================

SITEMAP_PATH = STATIC_DIR / "sitemap.xml"
ROBOTS_PATH = STATIC_DIR / "robots.txt"
FAVICON_PATH = STATIC_DIR / "favicon.png"
LLMS_PATH = STATIC_DIR / "llms.txt"
SW_PATH = STATIC_DIR / "sw.js"
MANIFEST_PATH = STATIC_DIR / "manifest.json"

# =========================================================
# CACHE HEADERS
# =========================================================

COMMON_HEADERS = {
    "Cache-Control": "public, max-age=3600",
    "X-Content-Type-Options": "nosniff",
}

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

# =========================================================
# HELPERS
# =========================================================

def render_page(request: Request, template_name: str):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={}
    )


def get_sitemap_xml() -> bytes:

    if not SITEMAP_PATH.exists():
        return b'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>'''

    raw = SITEMAP_PATH.read_bytes()

    # Remove UTF-8 BOM if exists
    raw = raw.lstrip(b"\xef\xbb\xbf")

    text = raw.decode("utf-8").strip()

    # Force XML declaration
    if not text.startswith("<?xml"):
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + text
        )

    return text.encode("utf-8")


def get_robots_txt() -> str:

    if not ROBOTS_PATH.exists():
        return ""

    return ROBOTS_PATH.read_text(
        encoding="utf-8"
    ).strip()

# =========================================================
# PUBLIC PAGES
# =========================================================

@router.get("/")
async def home(request: Request):
    return render_page(request, "index.html")


@router.get("/about-levix")
async def about_legacy():
    return RedirectResponse(
        url="/about",
        status_code=301
    )


@router.get("/about")
async def about(request: Request):
    return render_page(request, "about.html")


@router.get("/founder")
async def founder(request: Request):
    return render_page(request, "founder.html")


@router.get("/what-is-levix")
async def what_is_levix(request: Request):
    return render_page(request, "what-is-levix.html")


@router.get("/why-we-built-levix")
async def why_we_built_levix(request: Request):
    return render_page(request, "why-we-built-levix.html")


@router.get("/register")
async def register(request: Request):
    return render_page(request, "register.html")


@router.get("/login")
async def login(request: Request):
    return render_page(request, "login.html")


@router.get("/dashboard")
async def dashboard(request: Request):
    return render_page(request, "dashboard.html")


@router.get("/forgot-password")
async def forgot_password(request: Request):
    return render_page(request, "forgot-password.html")


@router.get("/reset-password")
async def reset_password(request: Request):
    return render_page(request, "reset-password.html")


@router.get("/pricing")
async def pricing(request: Request):
    return render_page(request, "pricing.html")


@router.get("/privacy")
async def privacy(request: Request):
    return render_page(request, "privacy.html")


@router.get("/terms")
async def terms(request: Request):
    return render_page(request, "terms.html")


@router.get("/contact")
async def contact(request: Request):
    return render_page(request, "contact.html")

# =========================================================
# SEO FILES
# =========================================================

@router.get("/robots.txt", include_in_schema=False)
async def robots():

    robots_text = get_robots_txt()

    return Response(
        content=robots_text,
        media_type="text/plain",
        headers=COMMON_HEADERS
    )


@router.head("/sitemap.xml", include_in_schema=False)
async def sitemap_head():

    sitemap_xml = get_sitemap_xml()

    return Response(
        content=sitemap_xml,
        media_type="application/xml",
        headers=COMMON_HEADERS
    )


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap():

    sitemap_xml = get_sitemap_xml()

    return Response(
        content=sitemap_xml,
        media_type="application/xml",
        headers=COMMON_HEADERS
    )

# =========================================================
# STATIC SEO FILES
# =========================================================

@router.get("/llms.txt", include_in_schema=False)
async def llms():
    return FileResponse(
        path=LLMS_PATH,
        media_type="text/plain"
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        path=FAVICON_PATH
    )


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Root-scoped service worker required for mobile PWA install."""
    return FileResponse(
        path=SW_PATH,
        media_type="application/javascript",
        headers={
            **NO_CACHE_HEADERS,
            "Service-Worker-Allowed": "/",
        },
    )


@router.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    return FileResponse(
        path=MANIFEST_PATH,
        media_type="application/manifest+json",
        headers=NO_CACHE_HEADERS,
    )

# =========================================================
# ADMIN
# =========================================================

@router.get("/levix-admin")
async def levix_admin(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="levix-admin.html",
        context={},
        headers=NO_CACHE_HEADERS
    )