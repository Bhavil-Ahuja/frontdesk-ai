import logging
from typing import Optional
from backend.config import settings
from backend.services.http_client import http

logger = logging.getLogger(__name__)

async def send_escalation_email(
    to_email: str,
    caller_phone: str,
    reason: str,
    tenant_name: str,
) -> bool:
    """
    Send an email notification to the coaching institute's owner email
    notifying them about a call escalation.
    """
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.warning("[EmailService] RESEND_API_KEY is not configured in .env. Skipping email.")
        return False

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    subject = f"🚨 Immediate Action Required: Call Escalated for {tenant_name}"
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; color: #1a202c;">
        <h2 style="color: #e53e3e; margin-top: 0;">🚨 Live Call Escalated</h2>
        <p>Hello,</p>
        <p>A customer call has just been escalated and requires your immediate attention.</p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr style="border-bottom: 1px solid #edf2f7;">
                <td style="padding: 8px 0; font-weight: bold; color: #4a5568; width: 120px;">Caller Phone:</td>
                <td style="padding: 8px 0; color: #2d3748;">{caller_phone}</td>
            </tr>
            <tr style="border-bottom: 1px solid #edf2f7;">
                <td style="padding: 8px 0; font-weight: bold; color: #4a5568;">Reason:</td>
                <td style="padding: 8px 0; color: #2d3748;">{reason}</td>
            </tr>
        </table>
        
        <p>Please log in to your dashboard to call back the student or manage contact details.</p>
        <hr style="border: 0; border-top: 1px solid #edf2f7; margin: 24px 0;" />
        <p style="font-size: 12px; color: #a0aec0; margin-bottom: 0;">This is an automated alert from FrontDesk AI.</p>
    </div>
    """

    payload = {
        "from": "onboarding@resend.dev",
        "to": to_email,
        "subject": subject,
        "html": html_content,
    }

    try:
        resp = await http.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            logger.error("[EmailService] Resend API failed: status=%d response=%s", resp.status_code, resp.text)
            return False
        logger.info("[EmailService] Escalation email successfully sent to %s via Resend.", to_email)
        return True
    except Exception as exc:
        logger.error("[EmailService] HTTP request to Resend failed: %s", exc)
        return False
