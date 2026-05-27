"""
Twilio SMS service — sends appointment confirmations, cancellations,
escalation notifications, and office alerts.

Multi-tenant: every public function accepts an optional TenantContext so it
uses the correct Twilio credentials, business name, phone, and timezone.
Falls back to global settings for legacy single-tenant mode.

Uses httpx to call the Twilio REST API directly (avoids the heavy twilio SDK
which requires aiohttp — not yet available for Python 3.14).
"""

import asyncio
import logging
import uuid
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
    """Return (account_sid, auth_token, from_number).

    Option A (centralised SaaS): the platform owns ONE Twilio account. All
    tenants share the global SID + auth token from .env. Only the from-number
    differs per tenant — each clinic gets its own Twilio number so patients
    see a local caller-ID.

    If a tenant has its own credentials stored (legacy Option B), they are
    used as an override so the migration path stays smooth.
    """
    # Global credentials from .env (platform account)
    global_sid = settings.TWILIO_ACCOUNT_SID
    global_token = settings.TWILIO_AUTH_TOKEN

    if tenant_ctx:
        # Use tenant-specific creds if set (legacy), else fall back to global
        sid = tenant_ctx.twilio_account_sid or global_sid
        token = tenant_ctx.twilio_auth_token or global_token
        from_number = tenant_ctx.twilio_phone_number or settings.TWILIO_PHONE_NUMBER
        return sid, token, from_number

    return global_sid, global_token, settings.TWILIO_PHONE_NUMBER


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
            # Record SMS usage for billing
            _record_sms_usage(tenant_ctx)
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


def _record_sms_usage(tenant_ctx: Any | None) -> None:
    """Fire-and-forget SMS usage recording for billing."""
    if not tenant_ctx:
        return
    tenant_id = getattr(tenant_ctx, "tenant_id", None)
    if not tenant_id:
        return
    try:
        loop = asyncio.get_running_loop()
        from backend.services.usage_service import record_sms
        loop.create_task(record_sms(tenant_id))
    except RuntimeError:
        pass  # No event loop — skip metering (rare, e.g. test harness)


# ── Outbound SMS logging ─────────────────────────────────────────────────────


async def _async_log_outbound_sms(
    tenant_id: uuid.UUID,
    to_number: str,
    body: str,
    patient_phone: str,
    from_number: str = "",
) -> None:
    """Persist an outbound SMS record for conversation threading / audit.

    This is the async implementation; callers from synchronous send_*()
    functions should use _log_outbound_sms() which schedules this onto the
    running event loop.
    """
    # Lazy import to avoid circular dependency (sms_inbound_service -> sms_service)
    from backend.database import async_session
    from backend.models.sms_message import SMSMessage, SMSDirection

    try:
        async with async_session() as session:
            msg = SMSMessage(
                tenant_id=tenant_id,
                direction=SMSDirection.OUTBOUND,
                from_number=from_number,
                to_number=to_number,
                body=body,
                patient_phone=patient_phone,
            )
            session.add(msg)
            await session.commit()
    except Exception as exc:
        logger.error(
            "[SMS Service] Failed to log OUTBOUND SMS (tenant=%s, to=%s): %s",
            tenant_id, to_number, exc,
        )


def _log_outbound_sms(
    tenant_ctx: Any | None,
    to_number: str,
    body: str,
    patient_phone: str,
) -> None:
    """Schedule an outbound SMS log entry on the running async event loop.

    All callers of the public send_*() functions are async (FastAPI routes,
    async services), so there will always be a running event loop. We use
    create_task() to fire-and-forget so the synchronous send function does
    not need to await.

    Args:
        tenant_ctx: TenantContext (must have .tenant_id).
        to_number: The recipient phone number.
        body: The message text that was sent.
        patient_phone: The patient phone used for conversation threading.
    """
    if not tenant_ctx:
        logger.debug("[SMS Service] No tenant_ctx — skipping outbound SMS log")
        return

    tenant_id = getattr(tenant_ctx, "tenant_id", None)
    if not tenant_id:
        logger.debug("[SMS Service] tenant_ctx has no tenant_id — skipping outbound SMS log")
        return

    from_number = getattr(tenant_ctx, "twilio_phone_number", "") or ""

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _async_log_outbound_sms(
                tenant_id=tenant_id,
                to_number=to_number,
                body=body,
                patient_phone=patient_phone,
                from_number=from_number,
            )
        )
    except RuntimeError:
        # No running event loop (e.g. called from a pure-sync test harness).
        # Fall back to creating a new loop — this path should be rare.
        logger.debug("[SMS Service] No running event loop — logging outbound SMS synchronously")
        asyncio.run(
            _async_log_outbound_sms(
                tenant_id=tenant_id,
                to_number=to_number,
                body=body,
                patient_phone=patient_phone,
                from_number=from_number,
            )
        )


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
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


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
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


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
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


def send_waitlist_added(
    patient_name: str,
    phone: str,
    appointment_type: str,
    preferred_date: str,
    preferred_time_start: str | None = None,
    preferred_time_end: str | None = None,
    tenant_ctx: Any | None = None,
) -> bool:
    """Confirm to the patient that they were added to the waitlist."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)

    # Format the preferred date as a friendly string when possible
    try:
        date_str = datetime.strptime(preferred_date, "%Y-%m-%d").strftime("%A, %B %d")
    except (ValueError, TypeError):
        date_str = preferred_date

    window = ""
    if preferred_time_start and preferred_time_end:
        window = f" between {preferred_time_start}–{preferred_time_end}"
    elif preferred_time_start:
        window = f" after {preferred_time_start}"
    elif preferred_time_end:
        window = f" before {preferred_time_end}"

    body = (
        f"Hi {patient_name}! You're on the {biz} waitlist for a "
        f"{appointment_type} on {date_str}{window}. We'll text you the moment "
        f"a matching slot opens up. Questions? Call {biz_phone}."
    )
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


def send_waitlist_promoted(
    patient_name: str,
    phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Notify the patient that their waitlist entry was promoted to a booked appointment."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    tz = _tz_abbrev(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d, %Y")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}! Great news — a {appointment_type} slot opened at "
        f"{biz} and we've booked it for you on {date_str} at {time_str} {tz}. "
        f"Need to change it? Call {biz_phone}. See you then!"
    )
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


def send_waitlist_cancelled(
    patient_name: str,
    phone: str,
    appointment_type: str,
    preferred_date: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """Notify the patient that their waitlist entry was cancelled."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)

    try:
        date_str = datetime.strptime(preferred_date, "%Y-%m-%d").strftime("%A, %B %d")
    except (ValueError, TypeError):
        date_str = preferred_date

    body = (
        f"Hi {patient_name}, your {biz} waitlist request for a "
        f"{appointment_type} on {date_str} has been cancelled. "
        f"Want back on the list? Call {biz_phone}."
    )
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


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
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


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
    ok = _send_sms(esc_phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=esc_phone, body=body, patient_phone=caller_number)
    return ok


# ── Appointment reminders & follow-ups ──────────────────────────────────────


def send_reminder(
    patient_name: str,
    phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send a 2-hour-before appointment reminder SMS."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    tz = _tz_abbrev(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}! Friendly reminder: your {appointment_type} at "
        f"{biz} is coming up today at {time_str} {tz}. "
        f"Need to reschedule? Call {biz_phone}. See you soon!"
    )
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


def send_no_show(
    patient_name: str,
    phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    tenant_ctx: Any | None = None,
) -> bool:
    """Send a gentle no-show follow-up SMS inviting the patient to reschedule."""
    biz = _business_name(tenant_ctx)
    biz_phone = _business_phone_display(tenant_ctx)
    local_dt = _to_local_time(scheduled_at, tenant_ctx)
    date_str = local_dt.strftime("%A, %B %d")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    body = (
        f"Hi {patient_name}, we missed you at your {appointment_type} on "
        f"{date_str} at {time_str}. We hope everything is okay. "
        f"Call {biz} at {biz_phone} to reschedule whenever you're ready."
    )
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok


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
    ok = _send_sms(phone, body, tenant_ctx)
    if ok:
        _log_outbound_sms(tenant_ctx, to_number=phone, body=body, patient_phone=phone)
    return ok
