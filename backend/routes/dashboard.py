"""
Dashboard statistics API and agent configuration routes.

GET  /api/dashboard/stats  → overview numbers + chart data (scoped to current user)
GET  /api/knowledge        → read knowledge base (current tenant)
PUT  /api/knowledge        → update knowledge base (current tenant)
GET  /api/config           → read agent config (current tenant, from DB)
PUT  /api/config           → update agent config (current tenant, persists to DB)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session, get_db
from backend.models.call import Call, CallOutcome
from backend.models.appointment import Appointment, BookedVia
from backend.models.tenant import Tenant
from backend.services import auth_service, tenant_service
from backend.services.tenant_service import _generate_test_phone

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])

# Default config used when a tenant hasn't customised yet
_DEFAULT_BUSINESS_HOURS = {
    "monday": {"open": "08:00", "close": "18:00"},
    "tuesday": {"open": "08:00", "close": "18:00"},
    "wednesday": {"open": "08:00", "close": "18:00"},
    "thursday": {"open": "08:00", "close": "18:00"},
    "friday": {"open": "08:00", "close": "18:00"},
    "saturday": {"open": "09:00", "close": "14:00"},
    "sunday": None,
}


# ── Response schemas ──────────────────────────────────────────────────────────


class DashboardStats(BaseModel):
    today_calls: int
    week_appointments_booked: int
    escalation_rate: float
    avg_call_duration: float
    outcomes_breakdown: dict[str, int]
    calls_per_day: list[dict[str, Any]]
    agent_active: bool


# ── Dashboard stats ───────────────────────────────────────────────────────────


@router.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    tenant_id: Optional[str] = Query(None, description="Admin-only override"),
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Return overview statistics. Auto-scoped to current tenant; admins can override."""
    import uuid as _uuid

    # Determine which tenant to scope to
    if current_user.is_admin and tenant_id:
        try:
            tid = _uuid.UUID(tenant_id)
        except ValueError:
            tid = None
    elif current_user.is_admin and not tenant_id:
        # Admin viewing global stats — no tenant filter (sees ALL tenants)
        tid = None
    else:
        tid = current_user.id

    logger.info("Computing dashboard stats... (user=%s, tenant_scope=%s)",
                current_user.owner_email, tid)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday

    def _tenant_filter(model_class):
        """Return a tenant_id filter clause or True (no-op)."""
        if tid:
            return model_class.tenant_id == tid
        return True

    # Today's calls
    today_count_q = select(func.count()).where(and_(Call.started_at >= today_start, _tenant_filter(Call)))
    today_calls = (await db.execute(today_count_q)).scalar() or 0

    # This week's AI-booked appointments
    week_appts_q = select(func.count()).where(
        and_(
            Appointment.created_at >= week_start,
            Appointment.booked_via == BookedVia.AI,
            _tenant_filter(Appointment),
        )
    )
    week_appointments = (await db.execute(week_appts_q)).scalar() or 0

    # Escalation rate (last 30 days)
    thirty_days_ago = now - timedelta(days=30)
    total_calls_q = select(func.count()).where(and_(Call.started_at >= thirty_days_ago, _tenant_filter(Call)))
    total_calls = (await db.execute(total_calls_q)).scalar() or 0

    escalated_q = select(func.count()).where(
        and_(
            Call.started_at >= thirty_days_ago,
            Call.outcome == CallOutcome.ESCALATED,
            _tenant_filter(Call),
        )
    )
    escalated = (await db.execute(escalated_q)).scalar() or 0
    escalation_rate = round((escalated / total_calls * 100) if total_calls > 0 else 0, 1)

    # Average call duration (last 30 days)
    avg_dur_q = select(func.avg(Call.duration_seconds)).where(
        and_(
            Call.started_at >= thirty_days_ago,
            Call.duration_seconds.isnot(None),
            _tenant_filter(Call),
        )
    )
    avg_duration = (await db.execute(avg_dur_q)).scalar() or 0

    # Outcome breakdown
    outcomes: dict[str, int] = {}
    for outcome in CallOutcome:
        cnt_q = select(func.count()).where(and_(Call.outcome == outcome, _tenant_filter(Call)))
        outcomes[outcome.value] = (await db.execute(cnt_q)).scalar() or 0

    # Calls per day this week
    calls_per_day = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_end = day + timedelta(days=1)
        cnt_q = select(func.count()).where(
            and_(Call.started_at >= day, Call.started_at < day_end, _tenant_filter(Call))
        )
        count = (await db.execute(cnt_q)).scalar() or 0
        calls_per_day.append({
            "date": day.strftime("%Y-%m-%d"),
            "day": day.strftime("%a"),
            "count": count,
        })

    # Agent status — derived from tenant.status
    from backend.models.tenant import TenantStatus as _TS
    if tid:
        ten = await tenant_service.get_tenant(tid)
        agent_active = bool(ten and ten.status == _TS.ACTIVE)
    else:
        agent_active = True  # Admin global view — assume agents are running

    logger.info("Dashboard stats: calls_today=%d, week_appts=%d, escalation=%.1f%%, avg_duration=%.0fs",
                today_calls, week_appointments, escalation_rate, avg_duration)

    return DashboardStats(
        today_calls=today_calls,
        week_appointments_booked=week_appointments,
        escalation_rate=escalation_rate,
        avg_call_duration=round(avg_duration, 1),
        outcomes_breakdown=outcomes,
        calls_per_day=calls_per_day,
        agent_active=agent_active,
    )


# ── Knowledge base (per-tenant, in DB) ───────────────────────────────────────


@router.get("/api/knowledge")
async def get_knowledge(current_user: Tenant = Depends(auth_service.get_current_user)):
    """Return the current tenant's knowledge base (JSONB column)."""
    logger.info("Knowledge base requested by %s", current_user.owner_email)
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        return (t.knowledge_base if t else {}) or {}


@router.put("/api/knowledge")
async def update_knowledge(
    request: Request,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Update the current tenant's knowledge base."""
    logger.info("Knowledge base update by %s", current_user.owner_email)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")
        t.knowledge_base = data
        await session.commit()
        tenant_service.invalidate_cache(str(t.id))
    return {"status": "saved"}


# ── Agent config (per-tenant, in DB) ──────────────────────────────────────────


@router.get("/api/config")
async def get_config(current_user: Tenant = Depends(auth_service.get_current_user)):
    """Return the current tenant's agent configuration (assembled from DB columns)."""
    logger.info("Agent config requested by %s", current_user.owner_email)
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

    voice_cfg = t.voice_config or {}
    return {
        "agent_active": t.status.value == "ACTIVE" if t.status else False,
        "agent_name": t.agent_name or "Sarah",
        "escalation_phone": t.escalation_phone or "",
        "escalation_transfer_number": t.escalation_transfer_number or "",
        "business_hours": t.business_hours or _DEFAULT_BUSINESS_HOURS,
        "greeting_message": t.greeting_message or "",
        "voice_id": voice_cfg.get("voiceId", "21m00Tcm4TlvDq8ikWAM"),
        "voice_provider": voice_cfg.get("provider", "11labs"),
        "business_name": t.business_name,
        "business_phone": t.business_phone or "",
        "business_address": t.business_address or "",
        "timezone": t.timezone or "America/Chicago",
        "demo_mode": bool(t.demo_mode),
        "appointment_types": t.appointment_types or [],
        "emergency_guidance": t.emergency_guidance or "",
        # Integration credentials — never return raw secrets, only:
        # (a) booleans so the UI can show "Connected", and
        # (b) non-sensitive identifiers (assistant ID, phone number, username, event slug)
        "vapi_configured": bool(t.vapi_api_key and t.vapi_assistant_id),
        "vapi_assistant_id": t.vapi_assistant_id or "",
        "vapi_phone_number_id": t.vapi_phone_number_id or "",
        "vapi_api_key_masked": _mask_secret(t.vapi_api_key),
        "calcom_configured": bool(t.calcom_api_key),
        "calcom_username": t.calcom_username or "",
        "calcom_event_types": t.calcom_event_types or [],
        "calcom_api_key_masked": _mask_secret(t.calcom_api_key),
        "twilio_configured": bool(t.twilio_account_sid and t.twilio_auth_token),
        "twilio_account_sid": t.twilio_account_sid or "",
        "twilio_phone_number": t.twilio_phone_number or "",
        "twilio_auth_token_masked": _mask_secret(t.twilio_auth_token),
        # Google Calendar
        "google_calendar_connected": bool(t.google_calendar_connected),
        "google_calendar_email": t.google_calendar_email or "",
        # Test Agent — dummy phones used as caller-ID for patient context
        "test_caller_phone": t.test_caller_phone or "",
        "test_caller_phones": t.test_caller_phones or [],
        # Reminder & review settings
        "reminder_settings": t.reminder_settings or {
            "24h_enabled": True,
            "2h_enabled": True,
            "confirmation_reply_enabled": True,
        },
        "review_settings": t.review_settings or {
            "enabled": False,
            "google_review_link": "",
            "delay_hours": 24,
            "appointment_types": [],
        },
    }


def _mask_secret(secret: str | None) -> str:
    """Show only the last 4 chars of a secret for confirmation display."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "•" * len(secret)
    return "•" * (len(secret) - 4) + secret[-4:]


@router.put("/api/config")
async def update_config(
    request: Request,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Update the current tenant's agent configuration.

    Accepted keys:
      agent_name, escalation_phone, escalation_transfer_number, business_hours,
      greeting_message, voice_id, voice_provider, business_name, business_phone,
      business_address, timezone, demo_mode, appointment_types, emergency_guidance,
      reminder_settings, review_settings
    """
    logger.info("Agent config update by %s", current_user.owner_email)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    update_fields: dict[str, Any] = {}

    for k in (
        "agent_name", "escalation_phone", "escalation_transfer_number",
        "business_hours", "greeting_message", "business_name",
        "business_phone", "business_address", "timezone",
        "demo_mode", "appointment_types", "emergency_guidance",
        # Integration credentials — accept as plain text from authenticated tenant
        "vapi_api_key", "vapi_assistant_id", "vapi_phone_number_id",
        "vapi_webhook_secret",
        "calcom_api_key", "calcom_username", "calcom_event_types",
        "twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
        "reminder_settings", "review_settings",
    ):
        if k in data:
            # Skip empty strings for credential fields so users can clear by sending null,
            # but masked round-trip values (containing •) shouldn't overwrite real secrets.
            if k in {"vapi_api_key", "calcom_api_key", "twilio_auth_token", "vapi_webhook_secret"}:
                v = data[k]
                if isinstance(v, str) and "•" in v:
                    continue  # Don't overwrite with masked value
            update_fields[k] = data[k]

    if "voice_id" in data or "voice_provider" in data:
        update_fields["voice_config"] = {
            "provider": data.get("voice_provider", "11labs"),
            "voiceId": data.get("voice_id", "21m00Tcm4TlvDq8ikWAM"),
        }

    if not update_fields:
        raise HTTPException(status_code=400, detail="No valid fields to update.")

    updated = await tenant_service.update_tenant(current_user.id, update_fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {"status": "saved", "updated_fields": list(update_fields.keys())}


# ── Test phone management (multi-phone for concurrent booking tests) ─────────


@router.post("/api/config/test-phones")
async def generate_test_phone_endpoint(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Generate a new random test caller phone and add it to the tenant's list."""
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        phones = list(t.test_caller_phones or [])
        if len(phones) >= 10:
            raise HTTPException(status_code=400, detail="Maximum 10 test phones allowed.")

        new_phone = _generate_test_phone()
        # Ensure uniqueness (unlikely collision but be safe)
        while new_phone in phones:
            new_phone = _generate_test_phone()

        phones.append(new_phone)
        t.test_caller_phones = phones

        # If no default test_caller_phone yet, set this as default
        if not t.test_caller_phone:
            t.test_caller_phone = new_phone

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Generated test phone %s for tenant %s (total: %d)",
                new_phone, current_user.owner_email, len(phones))
    return {"phone": new_phone, "test_caller_phones": phones}


@router.delete("/api/config/test-phones/{phone}")
async def delete_test_phone(
    phone: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Remove a test caller phone from the tenant's list."""
    # URL-decode the phone (+ gets encoded as %2B)
    from urllib.parse import unquote
    phone = unquote(phone)

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        phones = list(t.test_caller_phones or [])
        if phone not in phones:
            raise HTTPException(status_code=404, detail="Phone not found in your test phones list.")
        if len(phones) <= 1:
            raise HTTPException(status_code=400, detail="Must keep at least one test phone.")

        phones.remove(phone)
        t.test_caller_phones = phones

        # If we deleted the default, switch to the first remaining
        if t.test_caller_phone == phone:
            t.test_caller_phone = phones[0]

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Deleted test phone %s for tenant %s (remaining: %d)",
                phone, current_user.owner_email, len(phones))
    return {"status": "deleted", "test_caller_phones": phones}
