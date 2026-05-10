"""
Twilio SMS service — sends appointment confirmations, cancellations,
escalation notifications, and office alerts.

Multi-tenant: every public function accepts an optional TenantContext so it
uses the correct Twilio credentials, business name, phone, and timezone.
Falls back to global settings for legacy single-tenant mode.

Uses httpx to call the Twilio REST API directly (avoids the heavy twilio SDK
which requires aiohttp — not yet available for Python 3.14).
"""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Twilio REST API endpoint
TWILIO_API_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


# ── Internal helpers ─────────────────────────────────────────────────────────


def _resolve_twilio(tenant_ctx: Any | None) -> tuple[str, str, str]:
    """Return (account_sid, auth_token, from_number) from tenant or global settings.

    IMPORTANT: when called from a tenant-authenticated path (tenant_ctx is not
    None) we ONLY use the tenant's own credentials. If the tenant hasn't
    configured Twilio we return empty strings — which causes _send_sms to log a
    "credentials not configured" warning and skip the send. We NEVER fall back
    to the global .env credentials from a tenant-scoped request, because that
    would leak one tenant's Twilio to another (or to a test account that
    shouldn't be sending real SMS).
    """
    if tenant_ctx:
        return (
            tenant_ctx.twilio_account_sid,
            tenant_ctx.twilio_auth_token,
            tenant_ctx.twilio_phone_number,
        )
    # Legacy single-tenant / no-tenant path — use global .env
    return settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_PHONE_NUMBER


def _business_name(tenant_ctx: Any | None) -> str:
    if tenant_ctx:
        return tenant_ctx.business_name
    return settings.OFFICE_NAME


def _business_phone_display(tenant_ctx: Any | None) -> str:
    """Human-readable phone for templates. Prefer tenant's business_phone, else from-number."""
    if tenant_ctx:
        return tenant_ctx.business_phone or tenant_ctx.twilio_phone_number or ""
    return settings.TWILIO_PHONE_NUMBER


def _tz_abbrev(tenant_ctx: Any | None) -> str:
    """Timezone abbreviation for SMS (e.g. 'CST', 'EST')."""
    if tenant_ctx:
        return tenant_ctx.tz_abbreviation  # property on TenantContext
    return "CST"


def _to_local_time(dt: datetime, tenant_ctx: Any | None) -> datetime:
    """Convert a UTC datetime to the tenant's local timezone for display.

    The DB stores all scheduled_at values in UTC.  Before formatting a
    human-readable date/time string (for SMS, emails, etc.) we must
    convert to the tenant's timezone so patients see the correct local
    time — e.g. "9:00 AM CST" not "3:00 PM UTC".
    """
    tz_name = tenant_ctx.timezone if tenant_ctx else "America/Chicago"
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = ZoneInfo("America/Chicago")
    # Ensure the datetime is tz-aware (DB values should be, but guard)
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(local_tz)


def _is_demo(tenant_ctx: Any | None) -> bool:
    if tenant_ctx:
        return tenant_ctx.demo_mode
    return settings.DEMO_MODE


def _escalation_phone(tenant_ctx: Any | None) -> str:
    if tenant_ctx:
        return tenant_ctx.escalation_phone  # may be empty — caller handles that
    return settings.ESCALATION_PHONE_NUMBER  # legacy .env fallback


def _send_sms(to: str, body: str, tenant_ctx: Any | None = None) -> bool:
    """
    Send an SMS via Twilio REST API. Returns True on success.
    In LOCAL_CHAT_MODE or demo mode, messages are logged but not actually sent.
    """
    if settings.LOCAL_CHAT_MODE:
        logger.info("[LOCAL_CHAT SMS — skipped → %s] %s", to, body)
        return True

    if _is_demo(tenant_ctx):
        logger.info("[DEMO SMS → %s] %s", to, body)
        return True

    sid, token, from_number = _resolve_twilio(tenant_ctx)

    if not sid or not token:
        logger.warning("Twilio credentials not configured — SMS will be logged only.")
        logger.info("[UNSENT SMS → %s] %s", to, body)
        return False

    url = TWILIO_API_URL.format(sid=sid)

    try:
        logger.info("Sending SMS to %s (%d chars)...", to, len(body))
        resp = httpx.post(
            url,
            auth=(sid, token),
            data={
                "To": to,
                "From": from_number,
                "Body": body,
            },
            timeout=15,
        )

        if resp.status_code in (200, 201):
            msg_sid = resp.json().get("sid", "unknown")
            logger.info("✓ SMS sent to %s (SID: %s)", to, msg_sid)
            return True
        else:
            error = resp.json().get("message", resp.text[:200])
            logger.error("✗ Twilio API error (HTTP %d) sending to %s: %s",
                         resp.status_code, to, error)
            return False

    except httpx.TimeoutException:
        logger.error("✗ Twilio request timed out sending to %s", to)
        return False
    except Exception as exc:
        logger.error("✗ Failed to send SMS to %s: %s", to, exc)
        return False


# ── Public helpers ────────────────────────────────────────────────────────────


def send_confirmation(
    patient_name: str,
    phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send appointment confirmation SMS to the patient."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    tz = _tz_abbrev(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d, %Y")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}! Your {appointment_type} at {biz} is confirmed "
        f"for {date_str} at {time_str} {tz}. "
        f"Questions? Call {biz_phone}. See you soon!"
    )
    return _send_sms(phone, body, tenant_ctx)


def send_cancellation(
    patient_name: str,
    phone: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send appointment cancellation SMS to the patient."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d, %Y")
    body = (
        f"Hi {patient_name}, your {biz} appointment on {date_str} "
        f"has been cancelled. Call us anytime to reschedule: {biz_phone}"
    )
    return _send_sms(phone, body, tenant_ctx)


def send_reschedule(
    patient_name: str,
    phone: str,
    new_scheduled_at: datetime,
    appointment_type: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send reschedule confirmation SMS to the patient."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    tz = _tz_abbrev(tenant_ctx)
    local_dt = _to_local_time(new_scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d, %Y")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}! Your {appointment_type} at {biz} has been "
        f"rescheduled to {date_str} at {time_str} {tz}. "
        f"Questions? Call {biz_phone}."
    )
    return _send_sms(phone, body, tenant_ctx)


def send_escalation_notification(
    patient_name: str,
    phone: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """Let the patient know a human will call them back."""
    biz = _business_name(tenant_ctx)
    body = (
        f"Hi {patient_name}, you recently called {biz}. "
        f"Our team will call you back within 30 minutes. Thank you!"
    )
    return _send_sms(phone, body, tenant_ctx)


def send_office_alert(
    reason: str,
    caller_number: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """Alert the office team that a caller needs human follow-up."""
    esc_phone = _escalation_phone(tenant_ctx)
    if not esc_phone:
        logger.warning("No escalation phone number configured — skipping office alert.")
        return False

    biz = _business_name(tenant_ctx)
    body = (
        f"{biz} AI Alert: Caller {caller_number} needs human assistance. "
        f"Reason: {reason}. Please call back."
    )
    return _send_sms(esc_phone, body, tenant_ctx)


# ── Appointment reminders & follow-ups ──────────────────────────────────────


def send_reminder(
    patient_name: str,
    phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send a 24-hour-before appointment reminder SMS."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    tz = _tz_abbrev(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}! Friendly reminder: your {appointment_type} at "
        f"{biz} is tomorrow ({date_str}) at {time_str} {tz}. "
        f"Need to reschedule? Call {biz_phone}. See you soon!"
    )
    return _send_sms(phone, body, tenant_ctx)


def send_followup(
    patient_name: str,
    phone: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send a post-visit satisfaction follow-up SMS."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    body = (
        f"Hi {patient_name}! Thank you for visiting {biz}. "
        f"We hope everything went well! If you have any questions or concerns, "
        f"please call us at {biz_phone}. Have a great day!"
    )
    return _send_sms(phone, body, tenant_ctx)
