"""
Contact form API route.
Sends emails via Resend to levixsupport@gmail.com.
Environment variables required:
  RESEND_API_KEY — Resend API key (never exposed to frontend)
"""
import os
import time
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["contact"])

# --- Simple in-memory rate limiter (per IP, max 3 per hour) ---
_rate_store: dict[str, list[float]] = {}
RATE_LIMIT_MAX = 3
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds


def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate-limited."""
    now = time.time()
    hits = _rate_store.get(ip, [])
    # Remove old hits outside window
    hits = [h for h in hits if now - h < RATE_LIMIT_WINDOW]
    if len(hits) >= RATE_LIMIT_MAX:
        _rate_store[ip] = hits
        return False
    hits.append(now)
    _rate_store[ip] = hits
    return True


class ContactFormPayload(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty.")
        if len(v) > 100:
            raise ValueError("Name is too long.")
        return v

    @field_validator("subject")
    @classmethod
    def subject_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Subject cannot be empty.")
        if len(v) > 200:
            raise ValueError("Subject is too long.")
        return v

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty.")
        if len(v) > 5000:
            raise ValueError("Message is too long (max 5000 characters).")
        return v


@router.post("/contact")
async def submit_contact_form(request: Request, payload: ContactFormPayload):
    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many messages sent. Please try again later."
        )

    # Resend API key check
    resend_api_key = os.getenv("RESEND_API_KEY")
    if not resend_api_key:
        logger.error("[Contact] RESEND_API_KEY not configured.")
        raise HTTPException(
            status_code=503,
            detail="Email service is temporarily unavailable. Please email us directly at levixsupport@gmail.com"
        )

    # Build email content
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1e293b;">
      <h2 style="color:#1a56db;margin-bottom:4px;">New Contact Form Message — Levix</h2>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin-bottom:20px;">
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:8px 0;font-weight:600;width:100px;color:#475569;">From:</td>
          <td style="padding:8px 0;">{payload.name}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;font-weight:600;color:#475569;">Email:</td>
          <td style="padding:8px 0;"><a href="mailto:{payload.email}" style="color:#1a56db;">{payload.email}</a></td>
        </tr>
        <tr>
          <td style="padding:8px 0;font-weight:600;color:#475569;">Subject:</td>
          <td style="padding:8px 0;">{payload.subject}</td>
        </tr>
      </table>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">
      <h3 style="color:#475569;font-size:14px;margin-bottom:8px;">Message:</h3>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;white-space:pre-wrap;font-size:15px;">{payload.message}</div>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin-top:24px;">
      <p style="font-size:12px;color:#94a3b8;">Sent via levixapp.in contact form | IP: {client_ip}</p>
    </div>
    """

    text_body = (
        f"New contact form submission from levixapp.in\n\n"
        f"Name: {payload.name}\n"
        f"Email: {payload.email}\n"
        f"Subject: {payload.subject}\n\n"
        f"Message:\n{payload.message}\n\n"
        f"---\nIP: {client_ip}"
    )

    try:
        import resend
        resend.api_key = resend_api_key

        params: resend.Emails.SendParams = {
            "from": "Levix Contact Form <contact@levixapp.in>",
            "to": ["levixsupport@gmail.com"],
            "reply_to": payload.email,
            "subject": f"[Levix Contact] {payload.subject}",
            "html": html_body,
            "text": text_body,
        }
        response = resend.Emails.send(params)
        logger.info(f"[Contact] Email sent successfully. ID: {response.get('id', 'N/A')}")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Your message has been sent. We will review and get back to you within 48 hours."
            }
        )

    except Exception as e:
        logger.error(f"[Contact] Resend API error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to send your message. Please email us directly at levixsupport@gmail.com"
        )
