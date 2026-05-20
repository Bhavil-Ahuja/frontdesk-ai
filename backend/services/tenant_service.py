"""
Tenant service — resolution, caching, and CRUD for multi-tenant routing.

The primary flow:
  1. Vapi sends a request with `call.assistantId`
  2. We resolve `assistantId` → Tenant row → TenantContext
  3. TenantContext is threaded through every service call
  4. Each service uses the tenant's credentials, timezone, etc.

Includes an in-memory TTL cache to avoid a DB hit on every request.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.tenant import Tenant, TenantStatus

logger = logging.getLogger(__name__)

# ── Cache ────────────────────────────────────────────────────────────────────
# Simple in-memory cache with 5-minute TTL. Tenants change rarely;
# avoids a DB round-trip on every Vapi request.

_CACHE_TTL = 300  # seconds
_cache: dict[str, tuple[float, "TenantContext"]] = {}  # key → (timestamp, context)


def _cache_get(key: str) -> "TenantContext | None":
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, ctx: "TenantContext") -> None:
    _cache[key] = (time.time(), ctx)


def invalidate_cache(tenant_id: str | None = None) -> None:
    """Clear cache for one tenant or all tenants."""
    if tenant_id:
        keys_to_remove = [k for k, (_, ctx) in _cache.items() if str(ctx.tenant_id) == str(tenant_id)]
        for k in keys_to_remove:
            del _cache[k]
    else:
        _cache.clear()


# ── TenantContext (the lightweight object threaded through services) ──────────

@dataclass(frozen=True)
class TenantContext:
    """
    Immutable snapshot of a tenant's config. Created once per request,
    threaded through all service calls. No DB connection needed after creation.
    """
    tenant_id: uuid.UUID
    slug: str

    # Business
    business_name: str
    business_type: str
    business_phone: str
    business_address: str
    timezone: str
    demo_mode: bool

    # Agent
    agent_name: str
    greeting_message: str
    system_prompt_override: str | None

    # Vapi
    vapi_api_key: str
    vapi_assistant_id: str
    vapi_phone_number_id: str
    vapi_webhook_secret: str

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # Google Calendar OAuth
    google_calendar_refresh_token: str
    google_calendar_email: str
    google_calendar_connected: bool

    # Escalation
    escalation_phone: str
    escalation_transfer_number: str

    # Appointment config
    appointment_types: list[dict[str, Any]]
    business_hours: dict[str, Any] | None

    # Knowledge
    knowledge_base: dict[str, Any]
    emergency_guidance: str

    # Reminder & review settings
    reminder_settings: dict[str, Any]
    review_settings: dict[str, Any]

    # Test Agent — unified callers with 1:1 phone→name mapping
    test_callers: list[dict[str, str]]  # [{phone: str, name: str}, ...]

    # Legacy fields (deprecated — prefer test_callers)
    test_caller_phone: str
    test_caller_phones: list[str]
    test_patient_name: str
    test_patient_names: list[str]

    @property
    def tz_abbreviation(self) -> str:
        """Human-readable timezone abbreviation for SMS templates."""
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as dt
            tz = ZoneInfo(self.timezone)
            return dt.now(tz).strftime("%Z")  # e.g. "CST", "EST", "PST"
        except Exception:
            return "local time"


def _tenant_to_context(t: Tenant) -> TenantContext:
    """Convert a Tenant ORM object to a frozen TenantContext."""
    return TenantContext(
        tenant_id=t.id,
        slug=t.slug,
        business_name=t.business_name,
        business_type=t.business_type.value if t.business_type else "custom",
        business_phone=t.business_phone or "",
        business_address=t.business_address or "",
        timezone=t.timezone or "America/Chicago",
        demo_mode=t.demo_mode if t.demo_mode is not None else True,
        agent_name=t.agent_name or "Sarah",
        greeting_message=t.greeting_message or "Thank you for calling. How can I help you today?",
        system_prompt_override=t.system_prompt_override,
        vapi_api_key=t.vapi_api_key or "",
        vapi_assistant_id=t.vapi_assistant_id or "",
        vapi_phone_number_id=t.vapi_phone_number_id or "",
        vapi_webhook_secret=t.vapi_webhook_secret or "",
        twilio_account_sid=t.twilio_account_sid or "",
        twilio_auth_token=t.twilio_auth_token or "",
        twilio_phone_number=t.twilio_phone_number or "",
        google_calendar_refresh_token=t.google_calendar_refresh_token or "",
        google_calendar_email=t.google_calendar_email or "",
        google_calendar_connected=t.google_calendar_connected if t.google_calendar_connected is not None else False,
        escalation_phone=t.escalation_phone or "",
        escalation_transfer_number=t.escalation_transfer_number or "",
        appointment_types=t.appointment_types or [],
        business_hours=t.business_hours,
        knowledge_base=t.knowledge_base or {},
        emergency_guidance=t.emergency_guidance or "",
        reminder_settings=t.reminder_settings or {"2h_enabled": True, "confirmation_reply_enabled": True},
        review_settings=t.review_settings or {"enabled": False, "google_review_link": "", "delay_hours": 24, "appointment_types": []},
        # Unified test_callers — migrate from legacy if needed
        test_callers=_merge_test_callers(t),
        # Legacy fields (kept for backwards compat)
        test_caller_phone=t.test_caller_phone or "",
        test_caller_phones=t.test_caller_phones or [],
        test_patient_name=t.test_patient_name or "Alex Johnson",
        test_patient_names=t.test_patient_names or ["Alex Johnson"],
    )


def _merge_test_callers(t: Tenant) -> list[dict[str, str]]:
    """
    Build the test_callers list. If the new unified field is populated, use it.
    Otherwise, merge the legacy parallel arrays (phones + names) into pairs.
    """
    if t.test_callers:
        return t.test_callers

    # Merge legacy parallel arrays
    phones = t.test_caller_phones or []
    names = t.test_patient_names or []

    # If no phones but we have the single legacy field, use that
    if not phones and t.test_caller_phone:
        phones = [t.test_caller_phone]
    if not names and t.test_patient_name:
        names = [t.test_patient_name]

    # Pair them up — if arrays are different lengths, use index or default name
    result = []
    for i, phone in enumerate(phones):
        name = names[i] if i < len(names) else f"Test Patient {i + 1}"
        result.append({"phone": phone, "name": name})

    return result


# ── Resolution (the hot path — called on every request) ──────────────────────

async def resolve_by_assistant_id(assistant_id: str) -> TenantContext | None:
    """
    Resolve a Vapi assistant_id to a TenantContext.
    Uses cache first; falls back to DB.
    Returns None if no active tenant matches.
    """
    if not assistant_id:
        return None

    cache_key = f"assistant:{assistant_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(
                Tenant.vapi_assistant_id == assistant_id,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )
        tenant = result.scalar_one_or_none()

    if not tenant:
        logger.warning("[TenantSvc] No active tenant for assistant_id=%s", assistant_id)
        return None

    ctx = _tenant_to_context(tenant)
    _cache_set(cache_key, ctx)
    logger.info("[TenantSvc] Resolved tenant: %s (%s) for assistant_id=%s",
                ctx.slug, ctx.business_name, assistant_id)
    return ctx


async def resolve_by_phone_number_id(phone_number_id: str) -> TenantContext | None:
    """
    Resolve a Vapi phone number ID to a TenantContext.

    In the platform-managed model we own ONE Vapi assistant and N phone numbers.
    Each tenant row stores the phone_number_id assigned to them. When Vapi calls
    the webhook it sends phoneNumberId — that's how we know which tenant the
    call belongs to.
    """
    if not phone_number_id:
        return None

    cache_key = f"phone:{phone_number_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(
                Tenant.vapi_phone_number_id == phone_number_id,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )
        tenant = result.scalar_one_or_none()

    if not tenant:
        logger.warning("[TenantSvc] No active tenant for phone_number_id=%s", phone_number_id)
        return None

    ctx = _tenant_to_context(tenant)
    _cache_set(cache_key, ctx)
    logger.info("[TenantSvc] Resolved tenant: %s (%s) for phone_number_id=%s",
                ctx.slug, ctx.business_name, phone_number_id)
    return ctx


async def resolve_by_slug(slug: str) -> TenantContext | None:
    """Resolve a tenant by URL slug."""
    if not slug:
        return None

    cache_key = f"slug:{slug}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        tenant = result.scalar_one_or_none()

    if not tenant:
        return None

    ctx = _tenant_to_context(tenant)
    _cache_set(cache_key, ctx)
    return ctx


async def resolve_by_id(tenant_id: uuid.UUID) -> TenantContext | None:
    """Resolve a tenant by UUID.

    Lazily assigns a test_caller_phone if the tenant doesn't have one yet
    (backfill for tenants created before this feature existed).
    """
    cache_key = f"id:{tenant_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

    if not tenant:
        return None

    # Backfill test_caller_phone for existing tenants
    if not tenant.test_caller_phone:
        test_phone = _generate_test_phone()
        async with async_session() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            t = result.scalar_one_or_none()
            if t:
                t.test_caller_phone = test_phone
                t.updated_at = datetime.now(timezone.utc)
                await session.commit()
                tenant.test_caller_phone = test_phone
                logger.info("[TenantSvc] Backfilled test_caller_phone=%s for tenant %s",
                            test_phone, tenant.slug)

    ctx = _tenant_to_context(tenant)
    _cache_set(cache_key, ctx)
    return ctx


# ── Fallback: resolve from .env (single-tenant backwards compatibility) ──────

async def resolve_default_tenant() -> TenantContext | None:
    """
    Fallback for when no assistant_id is present in the request
    (e.g. direct API testing, legacy single-tenant mode).
    Returns the first ACTIVE tenant, or builds a context from .env settings.
    """
    cache_key = "default"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.status == TenantStatus.ACTIVE)
            .order_by(Tenant.created_at.asc())
            .limit(1)
        )
        tenant = result.scalar_one_or_none()

    if tenant:
        ctx = _tenant_to_context(tenant)
        _cache_set(cache_key, ctx)
        return ctx

    # No tenants in DB — build from legacy .env settings
    from backend.config import settings
    logger.info("[TenantSvc] No tenants in DB — using legacy .env config")
    ctx = TenantContext(
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        slug="default",
        business_name=settings.OFFICE_NAME,
        business_type="custom",
        business_phone="",
        business_address="",
        timezone=settings.OFFICE_TIMEZONE,
        demo_mode=settings.DEMO_MODE,
        agent_name="Alex",
        greeting_message="Thank you for calling. How can I help you today?",
        system_prompt_override=None,
        vapi_api_key=settings.VAPI_API_KEY,
        vapi_assistant_id=settings.VAPI_ASSISTANT_ID,
        vapi_phone_number_id=settings.VAPI_PHONE_NUMBER_ID,
        vapi_webhook_secret=settings.VAPI_WEBHOOK_SECRET,
        twilio_account_sid=settings.TWILIO_ACCOUNT_SID,
        twilio_auth_token=settings.TWILIO_AUTH_TOKEN,
        twilio_phone_number=settings.TWILIO_PHONE_NUMBER,
        google_calendar_refresh_token="",
        google_calendar_email="",
        google_calendar_connected=False,
        escalation_phone=settings.ESCALATION_PHONE_NUMBER,
        escalation_transfer_number=settings.ESCALATION_TRANSFER_NUMBER,
        appointment_types=[
            {"code": "new_client", "name": "New Client Visit", "duration_minutes": 60, "max_concurrent": 1},
            {"code": "follow_up", "name": "Follow-up", "duration_minutes": 30, "max_concurrent": 2},
            {"code": "emergency", "name": "Emergency / Urgent", "duration_minutes": 30, "max_concurrent": 1},
            {"code": "consultation", "name": "Consultation", "duration_minutes": 45, "max_concurrent": 1},
        ],
        business_hours=None,
        knowledge_base={},
        emergency_guidance="",
        reminder_settings={"2h_enabled": True, "confirmation_reply_enabled": True},
        review_settings={"enabled": False, "google_review_link": "", "delay_hours": 24, "appointment_types": []},
        test_callers=[],
        test_caller_phone="",
        test_caller_phones=[],
        test_patient_name="Alex Johnson",
        test_patient_names=["Alex Johnson"],
    )
    _cache_set(cache_key, ctx)
    return ctx


# ── CRUD (admin operations) ──────────────────────────────────────────────────

def _generate_test_phone() -> str:
    """Generate a unique dummy phone for Test Agent chat caller recognition.

    Uses the 555-XXXX range reserved for fictional use in US numbering plans.
    The result looks like +15551000 through +15559999 — clearly a test number.
    With 9000 possible values, collisions are extremely unlikely.
    """
    import random
    suffix = random.randint(1000, 9999)
    return f"+1555{suffix}"


_DEFAULT_BUSINESS_HOURS = {
    "monday": {"open": "08:00", "close": "18:00"},
    "tuesday": {"open": "08:00", "close": "18:00"},
    "wednesday": {"open": "08:00", "close": "18:00"},
    "thursday": {"open": "08:00", "close": "18:00"},
    "friday": {"open": "08:00", "close": "18:00"},
    "saturday": None,
    "sunday": None,
}


async def create_tenant(data: dict[str, Any]) -> Tenant:
    """
    Create a new tenant in PENDING status (requires admin approval).
    Auto-assigns a test caller phone and default business hours.
    """
    async with async_session() as session:
        tenant = Tenant(
            slug=data["slug"],
            business_name=data["business_name"],
            business_type=data.get("business_type", "custom"),
            business_phone=data.get("owner_phone", ""),
            business_address=data.get("business_address", ""),
            owner_name=data["owner_name"],
            owner_email=data["owner_email"],
            owner_phone=data.get("owner_phone"),
            timezone=data.get("timezone", "America/Chicago"),
            plan=data.get("plan", "starter"),
            status=TenantStatus.PENDING,
            test_caller_phone=_generate_test_phone(),
            test_patient_names=["Alex Johnson"],
            test_patient_name="Alex Johnson",
            business_hours=_DEFAULT_BUSINESS_HOURS,
        )
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        logger.info("[TenantSvc] Created tenant %s (PENDING): %s (test_phone=%s)",
                    tenant.slug, tenant.business_name, tenant.test_caller_phone)
        return tenant


async def approve_tenant(tenant_id: uuid.UUID) -> Tenant | None:
    """Admin approves a PENDING tenant → ACTIVE."""
    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None
        if tenant.status != TenantStatus.PENDING:
            logger.warning("[TenantSvc] Cannot approve tenant %s — status is %s", tenant.slug, tenant.status)
            return tenant
        tenant.status = TenantStatus.ACTIVE
        tenant.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(tenant)
        invalidate_cache(str(tenant.id))
        logger.info("[TenantSvc] Approved tenant %s → ACTIVE", tenant.slug)
        return tenant


async def update_tenant(tenant_id: uuid.UUID, data: dict[str, Any]) -> Tenant | None:
    """Update tenant configuration fields."""
    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None

        # Only update provided fields
        allowed_fields = {
            "business_name", "business_type", "business_phone", "business_address",
            "business_website", "timezone", "agent_name", "greeting_message",
            "system_prompt_override", "voice_config", "end_call_phrases",
            "vapi_api_key", "vapi_assistant_id", "vapi_phone_number_id",
            "vapi_webhook_secret", "twilio_account_sid", "twilio_auth_token",
            "twilio_phone_number", "escalation_phone", "escalation_transfer_number",
            "appointment_types", "business_hours", "knowledge_base",
            "emergency_guidance", "demo_mode", "plan",
            "reminder_settings", "review_settings",
        }
        for field_name, value in data.items():
            if field_name in allowed_fields:
                setattr(tenant, field_name, value)

        tenant.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(tenant)
        invalidate_cache(str(tenant.id))
        logger.info("[TenantSvc] Updated tenant %s", tenant.slug)
        return tenant


async def list_tenants(status: TenantStatus | None = None) -> list[Tenant]:
    """List all tenants, optionally filtered by status."""
    async with async_session() as session:
        query = select(Tenant).order_by(Tenant.created_at.desc())
        if status:
            query = query.where(Tenant.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())


async def get_tenant(tenant_id: uuid.UUID) -> Tenant | None:
    """Get a single tenant by ID."""
    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        return result.scalar_one_or_none()
