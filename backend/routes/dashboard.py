"""
Dashboard statistics API and agent configuration routes.

GET  /api/dashboard/stats  → overview numbers + chart data (scoped to current user)
GET  /api/knowledge        → read knowledge base (current tenant)
PUT  /api/knowledge        → update knowledge base (current tenant)
GET  /api/config           → read agent config (current tenant, from DB)
PUT  /api/config           → update agent config (current tenant, persists to DB)
GET  /api/voice-preview/{voice_id} → generate ElevenLabs TTS preview for a voice
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.defaults import (
    DEFAULT_AGENT_NAME,
    DEFAULT_TEST_PATIENT_NAME,
    DEFAULT_TIMEZONE,
)
from backend.database import async_session, get_db
from backend.models.call import Call, CallOutcome
from backend.models.appointment import Appointment, BookedVia
from backend.models.tenant import Tenant
from backend.services import auth_service, tenant_service, calendar_service
from backend.services.tenant_service import _generate_test_phone
from backend.services.http_client import http

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

        # Auto-persist defaults if NULL — prevents "UI shows values but they're not
        # actually saved" confusion that caused slot availability issues.
        needs_commit = False
        if t.business_hours is None:
            logger.info("Auto-persisting default business_hours for tenant %s", t.slug)
            t.business_hours = _DEFAULT_BUSINESS_HOURS
            needs_commit = True
        if not t.test_patient_names:
            t.test_patient_names = [DEFAULT_TEST_PATIENT_NAME]
            t.test_patient_name = DEFAULT_TEST_PATIENT_NAME
            needs_commit = True
        if needs_commit:
            await session.commit()
            tenant_service.invalidate_cache(str(t.id))

    voice_cfg = t.voice_config or {}
    return {
        "agent_active": t.status.value == "ACTIVE" if t.status else False,
        "agent_name": t.agent_name or DEFAULT_AGENT_NAME,
        "escalation_phone": t.escalation_phone or "",
        "escalation_transfer_number": t.escalation_transfer_number or "",
        "business_hours": t.business_hours or _DEFAULT_BUSINESS_HOURS,
        "greeting_message": t.greeting_message or "",
        "voice_id": voice_cfg.get("voiceId", "21m00Tcm4TlvDq8ikWAM"),
        "voice_provider": voice_cfg.get("provider", "11labs"),
        "business_name": t.business_name,
        "business_phone": t.business_phone or "",
        "business_address": t.business_address or "",
        "timezone": t.timezone or DEFAULT_TIMEZONE,
        "demo_mode": bool(t.demo_mode),
        "appointment_types": t.appointment_types or [],
        "emergency_guidance": t.emergency_guidance or "",
        # One-off holiday closures — admin manages [{date, name}, ...]
        "holidays": t.holidays or [],
        # Integration credentials — never return raw secrets, only:
        # (a) booleans so the UI can show "Connected", and
        # (b) non-sensitive identifiers (assistant ID, phone number, username, event slug)
        "vapi_configured": bool(t.vapi_api_key and t.vapi_assistant_id),
        "vapi_assistant_id": t.vapi_assistant_id or "",
        "vapi_phone_number_id": t.vapi_phone_number_id or "",
        "vapi_api_key_masked": _mask_secret(t.vapi_api_key),
        "twilio_configured": bool(t.twilio_account_sid and t.twilio_auth_token),
        "twilio_account_sid": t.twilio_account_sid or "",
        "twilio_phone_number": t.twilio_phone_number or "",
        "twilio_auth_token_masked": _mask_secret(t.twilio_auth_token),
        # Google Calendar
        "google_calendar_connected": bool(t.google_calendar_connected),
        "google_calendar_email": t.google_calendar_email or "",
        # Feature flags — effective state (global AND per-tenant)
        "vapi_enabled": settings.FEATURE_VAPI_ENABLED and (t.feature_vapi_enabled if t.feature_vapi_enabled is not None else True),
        "twilio_enabled": settings.FEATURE_TWILIO_ENABLED and (t.feature_twilio_enabled if t.feature_twilio_enabled is not None else True),
        # Test Agent — unified callers (phone + name pairs)
        "test_callers": tenant_service._merge_test_callers(t),
        # Legacy fields (kept for backwards compat)
        "test_caller_phone": t.test_caller_phone or "",
        "test_caller_phones": t.test_caller_phones or [],
        "test_patient_name": t.test_patient_name or DEFAULT_TEST_PATIENT_NAME,
        "test_patient_names": t.test_patient_names or [DEFAULT_TEST_PATIENT_NAME],
        # Reminder & review settings
        "reminder_settings": t.reminder_settings or {
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
      business_address, demo_mode, appointment_types, emergency_guidance,
      reminder_settings, review_settings

    NOTE: `timezone` is intentionally NOT accepted here — it's fixed at
    registration to keep appointment/slot history coherent. Trying to send
    a different timezone is silently ignored.
    """
    logger.info("Agent config update by %s", current_user.owner_email)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    update_fields: dict[str, Any] = {}

    for k in (
        "agent_name", "escalation_phone", "escalation_transfer_number",
        "business_hours", "holidays", "greeting_message", "business_name",
        "business_phone", "business_address",
        "demo_mode", "appointment_types", "emergency_guidance",
        # Integration credentials — accept as plain text from authenticated tenant
        "vapi_api_key", "vapi_assistant_id", "vapi_phone_number_id",
        "vapi_webhook_secret",
        "twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
        "reminder_settings", "review_settings",
    ):
        if k in data:
            # Skip empty strings for credential fields so users can clear by sending null,
            # but masked round-trip values (containing •) shouldn't overwrite real secrets.
            if k in {"vapi_api_key", "twilio_auth_token", "vapi_webhook_secret"}:
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

    # Also clear slot cache if business_hours or holidays changed — both
    # directly affect day-level availability. (Timezone is fixed at
    # registration, so it can never change here.)
    if (
        "business_hours" in update_fields
        or "holidays" in update_fields
    ):
        calendar_service.invalidate_slot_cache(current_user.slug)
        logger.info("Slot cache cleared for %s due to config change", current_user.slug)

    # If anything that affects the Vapi assistant changed (voice, greeting, agent
    # name), patch the live assistant so the phone agent matches what the user
    # just saved. Best-effort — failures are logged and don't break the save.
    _vapi_relevant = {"voice_config", "greeting_message", "agent_name", "business_name"}
    vapi_synced = False
    if _vapi_relevant & set(update_fields.keys()):
        try:
            tenant_ctx = await tenant_service.resolve_by_id(current_user.id)
            if tenant_ctx and tenant_ctx.vapi_api_key and tenant_ctx.vapi_assistant_id:
                from backend.services import vapi_service
                new_id = await vapi_service.register_assistant(tenant_ctx=tenant_ctx)
                vapi_synced = bool(new_id)
                logger.info(
                    "[Config] Vapi assistant sync for %s: %s",
                    current_user.slug,
                    "ok" if vapi_synced else "skipped/failed",
                )
            else:
                logger.info(
                    "[Config] Skipping Vapi sync for %s — credentials missing",
                    current_user.slug,
                )
        except Exception as exc:
            logger.warning("[Config] Vapi assistant sync error: %s", exc)

    return {
        "status": "saved",
        "updated_fields": list(update_fields.keys()),
        "vapi_synced": vapi_synced,
    }


# ── Voice preview (ElevenLabs TTS) ──────────────────────────────────────────

# Allowed voice IDs — prevents abuse by restricting to known ElevenLabs voices.
_ALLOWED_VOICE_IDS = {
    "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "AZnzlk1XvdvUeBnXmlld",  # Domi
    "EXAVITQu4vr4xnSDxMaL",  # Bella
    "MF3mGyEYCl7XYWbV9V6O",  # Emily
    "TxGEqnHWrfWFTfGW9XjX",  # Josh
}

_PREVIEW_TEXT = "Hi there! Thank you for calling. How can I help you today?"


@router.get("/api/voice-preview/{voice_id}")
async def voice_preview(
    voice_id: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Generate a short ElevenLabs TTS preview for the given voice.

    Returns audio/mpeg on success.
    Returns 404 if no ElevenLabs API key is configured.
    Returns 400 if the voice_id is not in the allowed list.
    """
    if voice_id not in _ALLOWED_VOICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid voice ID.")

    api_key = settings.ELEVENLABS_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=404,
            detail="ElevenLabs API key not configured. Set ELEVENLABS_API_KEY in your environment to enable voice previews.",
        )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": _PREVIEW_TEXT,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    try:
        resp = await http.post(url, headers=headers, json=payload, timeout=15)
    except Exception as exc:
        logger.error("ElevenLabs TTS request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Voice preview service unavailable.")

    if resp.status_code != 200:
        logger.warning(
            "ElevenLabs TTS returned %d: %s",
            resp.status_code,
            resp.text[:200] if resp.text else "(empty)",
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to generate voice preview from ElevenLabs.",
        )

    return Response(
        content=resp.content,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=86400",  # cache for 24h
            "Content-Disposition": f'inline; filename="voice-preview-{voice_id}.mp3"',
        },
    )


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


# ── Test patient name management ─────────────────────────────────────────────


@router.post("/api/config/test-patient-names")
async def add_test_patient_name(
    body: dict,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Add a new test patient name to the tenant's list."""
    name = (body.get("name") or "").strip()
    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="Name must be 50 characters or less.")

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        names = list(t.test_patient_names or [DEFAULT_TEST_PATIENT_NAME])
        if len(names) >= 10:
            raise HTTPException(status_code=400, detail="Maximum 10 test patient names allowed.")
        if name in names:
            raise HTTPException(status_code=400, detail="This name already exists.")

        names.append(name)
        t.test_patient_names = names

        # If no default yet, set this as default
        if not t.test_patient_name:
            t.test_patient_name = name

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Added test patient name '%s' for tenant %s (total: %d)",
                name, current_user.owner_email, len(names))
    return {"name": name, "test_patient_names": names}


@router.delete("/api/config/test-patient-names/{name}")
async def delete_test_patient_name(
    name: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Remove a test patient name from the tenant's list."""
    from urllib.parse import unquote
    name = unquote(name)

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        names = list(t.test_patient_names or [])
        if name not in names:
            raise HTTPException(status_code=404, detail="Name not found in your test patient names list.")
        if len(names) <= 1:
            raise HTTPException(status_code=400, detail="Must keep at least one test patient name.")

        names.remove(name)
        t.test_patient_names = names

        # If we deleted the default, switch to the first remaining
        if t.test_patient_name == name:
            t.test_patient_name = names[0]

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Deleted test patient name '%s' for tenant %s (remaining: %d)",
                name, current_user.owner_email, len(names))
    return {"status": "deleted", "test_patient_names": names}


# ── Unified test callers management (phone + name pairs) ────────────────────


@router.post("/api/config/test-callers")
async def add_test_caller(
    body: dict,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Add a new test caller with a unique phone + name pair.
    If no phone provided, generates a random +155501XXX number.
    """
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()

    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="Name must be 50 characters or less.")

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        callers = list(t.test_callers or [])
        if len(callers) >= 10:
            raise HTTPException(status_code=400, detail="Maximum 10 test callers allowed.")

        # Generate phone if not provided
        if not phone:
            phone = _generate_test_phone()
            existing_phones = {c.get("phone") for c in callers}
            while phone in existing_phones:
                phone = _generate_test_phone()

        # Check for duplicate phone
        if any(c.get("phone") == phone for c in callers):
            raise HTTPException(status_code=400, detail="A test caller with this phone already exists.")

        callers.append({"phone": phone, "name": name})
        t.test_callers = callers

        # Also update legacy fields for backwards compat
        t.test_caller_phones = [c["phone"] for c in callers]
        t.test_patient_names = [c["name"] for c in callers]
        if not t.test_caller_phone:
            t.test_caller_phone = phone
            t.test_patient_name = name

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Added test caller %s (%s) for tenant %s (total: %d)",
                name, phone, current_user.owner_email, len(callers))
    return {"caller": {"phone": phone, "name": name}, "test_callers": callers}


@router.put("/api/config/test-callers/{phone}")
async def update_test_caller(
    phone: str,
    body: dict,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Update a test caller's name."""
    from urllib.parse import unquote
    phone = unquote(phone)
    new_name = (body.get("name") or "").strip()

    if not new_name or len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        callers = list(t.test_callers or [])
        found = False
        for c in callers:
            if c.get("phone") == phone:
                c["name"] = new_name
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail="Test caller not found.")

        t.test_callers = callers
        # Update legacy
        t.test_patient_names = [c["name"] for c in callers]

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Updated test caller %s → %s for tenant %s", phone, new_name, current_user.owner_email)
    return {"caller": {"phone": phone, "name": new_name}, "test_callers": callers}


@router.delete("/api/config/test-callers/{phone}")
async def delete_test_caller(
    phone: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Remove a test caller by phone."""
    from urllib.parse import unquote
    phone = unquote(phone)

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == current_user.id))
        t = result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        callers = list(t.test_callers or [])
        original_len = len(callers)
        callers = [c for c in callers if c.get("phone") != phone]

        if len(callers) == original_len:
            raise HTTPException(status_code=404, detail="Test caller not found.")
        if len(callers) == 0:
            raise HTTPException(status_code=400, detail="Must keep at least one test caller.")

        t.test_callers = callers
        # Update legacy
        t.test_caller_phones = [c["phone"] for c in callers]
        t.test_patient_names = [c["name"] for c in callers]

        # If we deleted the default, switch to the first remaining
        if t.test_caller_phone == phone:
            t.test_caller_phone = callers[0]["phone"]
            t.test_patient_name = callers[0]["name"]

        await session.commit()
        tenant_service.invalidate_cache(str(t.id))

    logger.info("Deleted test caller %s for tenant %s (remaining: %d)",
                phone, current_user.owner_email, len(callers))
    return {"status": "deleted", "test_callers": callers}
