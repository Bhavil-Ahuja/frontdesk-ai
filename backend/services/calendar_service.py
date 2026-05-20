"""
Calendar service — slot availability, booking, rescheduling, cancellation.

Dual-mode routing (checked in priority order):
  1. Google Calendar — if tenant has google_calendar_connected + refresh_token
  2. Native scheduler — Postgres-backed, uses business_hours + appointment_types
  3. Demo mode       — fake slots/bookings for testing (when demo_mode=True)

This means tenants can go live with Google Calendar (free) or
zero external dependencies (native scheduler only needs business hours).

Multi-tenant: every function accepts a TenantContext so it uses the correct
credentials, timezone, and event type mappings for the calling tenant.
"""

import logging
import time
from datetime import datetime
from typing import Any

from backend.config import settings
from backend.services import native_scheduling
from backend.services import google_calendar as gcal

logger = logging.getLogger(__name__)

# ── Slot availability cache ─────────────────────────────────────────────────
# During a single booking conversation the LLM often asks for the same date
# range 2-3 times (e.g. confirm → re-check → book). A short TTL avoids
# redundant Google Calendar API calls without risking stale data.
_SLOT_CACHE_TTL = 30  # seconds
_slot_cache: dict[str, tuple[float, list[str]]] = {}


def _slot_cache_key(
    date_from: str,
    date_to: str,
    tenant_slug: str,
    appointment_type_key: str,
    provider_id: str | None,
) -> str:
    return f"{tenant_slug}:{date_from}:{date_to}:{appointment_type_key}:{provider_id or ''}"


def invalidate_slot_cache(tenant_slug: str | None = None) -> None:
    """Clear cached slots — call after a booking/cancel/reschedule."""
    if tenant_slug:
        keys = [k for k in _slot_cache if k.startswith(f"{tenant_slug}:")]
        for k in keys:
            del _slot_cache[k]
    else:
        _slot_cache.clear()


def _is_demo(tenant_ctx: Any | None) -> bool:
    if tenant_ctx:
        return tenant_ctx.demo_mode
    return settings.DEMO_MODE


# ── Availability ──────────────────────────────────────────────────────────────


def _resolve_appointment_config(
    appointment_type_key: str,
    tenant_ctx: Any | None,
) -> tuple[int, int]:
    """
    Resolve ``duration_minutes`` and ``max_concurrent`` from the tenant's
    appointment_types config for the given appointment type key (e.g.
    "consultation", "follow_up").

    Falls back to (60, 1) if no match or no tenant context.
    """
    duration = 60
    max_conc = 1
    if not tenant_ctx or not tenant_ctx.appointment_types:
        return duration, max_conc

    # Try to match by code
    key = (appointment_type_key or "").lower().replace(" ", "_")
    for at in tenant_ctx.appointment_types:
        if at.get("code", "").lower() == key:
            duration = at.get("duration_minutes", 60)
            max_conc = at.get("max_concurrent", 1)
            return duration, max_conc

    # No key match — fall back to the first configured type
    first = tenant_ctx.appointment_types[0]
    duration = first.get("duration_minutes", 60)
    max_conc = first.get("max_concurrent", 1)
    return duration, max_conc


async def _resolve_provider_overrides(
    provider_id: str | None,
    tenant_ctx: Any | None,
) -> tuple[str | None, dict | None]:
    """
    If a provider_id is given, load the provider and return any overrides.

    Returns:
        (calendar_id or None, business_hours_override or None)
    """
    if not provider_id or not tenant_ctx:
        return None, None
    try:
        from backend.services import provider_service
        import uuid as _uuid
        provider = await provider_service.get_provider(_uuid.UUID(provider_id))
        if provider and str(provider.get("tenant_id", "")) == str(tenant_ctx.tenant_id):
            return provider.get("calendar_id"), provider.get("business_hours_override")
    except Exception as exc:
        logger.warning("[Calendar] Provider lookup failed for %s: %s", provider_id, exc)
    return None, None


async def get_available_slots(
    date_from: str,
    date_to: str,
    tenant_ctx: Any | None = None,
    appointment_type_key: str = "",
    provider_id: str | None = None,
    *,
    event_type_id: str = "",  # deprecated, kept for call-site compat
) -> list[str]:
    """
    Fetch available time slots.

    Routes to Google Calendar, native scheduler, or demo mode
    depending on the tenant's configuration.

    Args:
        date_from: ISO date string (YYYY-MM-DD) — start of window.
        date_to: ISO date string (YYYY-MM-DD) — end of window.
        tenant_ctx: TenantContext for multi-tenant routing.
        appointment_type_key: Raw appointment type key (e.g. "consultation")
            used to resolve duration and max_concurrent from tenant config.
        provider_id: Optional provider UUID — uses their calendar_id and
            business hours override if set.

    Returns:
        List of available slot ISO datetime strings.
    """
    # ── Check slot cache first ─────────────────────────────────────────
    slug = tenant_ctx.slug if tenant_ctx else "default"
    tz = tenant_ctx.timezone if tenant_ctx else settings.OFFICE_TIMEZONE
    cache_key = _slot_cache_key(date_from, date_to, slug, appointment_type_key, provider_id)
    cached = _slot_cache.get(cache_key)
    if cached:
        ts, slots = cached
        if (time.time() - ts) < _SLOT_CACHE_TTL:
            logger.info("[Calendar][%s] Slot cache HIT (%d slots, %.0fs old)",
                        slug, len(slots), time.time() - ts)
            return slots
        del _slot_cache[cache_key]

    # Resolve provider-specific overrides (calendar_id, business hours)
    prov_calendar_id, prov_hours = await _resolve_provider_overrides(provider_id, tenant_ctx)
    effective_hours = prov_hours or (tenant_ctx.business_hours if tenant_ctx else None)

    def _cache_and_return(result: list[str]) -> list[str]:
        """Store result in short-TTL cache before returning."""
        _slot_cache[cache_key] = (time.time(), result)
        return result

    # ── Priority 1: Google Calendar (if connected) ──────────────────────
    if tenant_ctx and tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token:
        duration, max_conc = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        cal_id = prov_calendar_id or "primary"
        logger.info("[Calendar][%s] Using Google Calendar for availability (type=%s, duration=%d, max_concurrent=%d, calendar=%s)",
                    tenant_ctx.slug, appointment_type_key, duration, max_conc, cal_id)
        return _cache_and_return(await gcal.get_available_slots(
            refresh_token=tenant_ctx.google_calendar_refresh_token,
            date_from=date_from,
            date_to=date_to,
            timezone=tz,
            duration_minutes=duration,
            business_hours=effective_hours,
            max_concurrent=max_conc,
            calendar_id=cal_id,
        ))

    # ── Priority 2: Native scheduling (uses business_hours + Postgres) ──
    if tenant_ctx:
        duration, max_conc = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        logger.info("[Calendar][%s] Using native scheduler (type=%s, duration=%d, max_concurrent=%d)",
                    tenant_ctx.slug, appointment_type_key, duration, max_conc)

        # Use provider-aware slots which handles per-provider concurrency
        provider_uuid = None
        if provider_id:
            try:
                import uuid as uuid_mod
                provider_uuid = uuid_mod.UUID(provider_id)
            except (ValueError, TypeError):
                pass

        result = await native_scheduling.get_provider_aware_slots(
            date_str=date_from,
            duration_minutes=duration,
            tenant_id=tenant_ctx.tenant_id,
            business_hours=effective_hours,
            tz_name=tz,
            provider_id=provider_uuid,
        )
        # Extract just the time strings for backwards compatibility
        slot_times = [s["time"] for s in result.get("slots", [])]
        return _cache_and_return(slot_times)

    # ── Priority 3: Demo mode fallback (no real calendar configured) ────
    if _is_demo(tenant_ctx):
        demo_slots = _demo_slots(date_from)
        logger.info("[Calendar DEMO] Returning %d fake slots for %s", len(demo_slots), date_from)
        return _cache_and_return(demo_slots)

    logger.warning("[Calendar] No calendar configured and not in demo mode — returning empty slots")
    return []


# ── Booking ───────────────────────────────────────────────────────────────────


async def book_appointment(
    patient_info: dict[str, Any],
    start_time: str,
    tenant_ctx: Any | None = None,
    appointment_type_key: str = "",
    *,
    event_type_id: str = "",  # deprecated, kept for call-site compat
) -> dict[str, Any] | None:
    """
    Create a booking.

    Routes to Google Calendar, native scheduler, or demo mode.

    Args:
        patient_info: Dict with name, email, phone, dob.
        start_time: ISO datetime string for the slot.
        tenant_ctx: TenantContext for multi-tenant routing.
        appointment_type_key: Raw appointment type key (e.g. "consultation")
            used to resolve duration from tenant config.

    Returns:
        Dict with id, uid, status on success; None on failure.
    """
    slug = tenant_ctx.slug if tenant_ctx else "default"
    tz = tenant_ctx.timezone if tenant_ctx else settings.OFFICE_TIMEZONE

    # Invalidate slot cache — the booking changes availability
    invalidate_slot_cache(slug)

    # ── Priority 1: Google Calendar (if connected) ──────────────────────
    if tenant_ctx and tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token:
        duration, _ = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        logger.info("[Calendar][%s] Using Google Calendar for booking (type=%s, duration=%d)", slug, appointment_type_key, duration)
        return await gcal.book_appointment(
            refresh_token=tenant_ctx.google_calendar_refresh_token,
            patient_info=patient_info,
            start_time=start_time,
            duration_minutes=duration,
            timezone=tz,
        )

    # ── Priority 2: Native scheduling (uses business_hours + Postgres) ──
    if tenant_ctx:
        duration, _ = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        appt_type_key = appointment_type_key or "consultation"
        logger.info("[Calendar][%s] Using native booking (type=%s, duration=%d)", slug, appt_type_key, duration)

        return await native_scheduling.create_native_booking(
            tenant_id=tenant_ctx.tenant_id,
            patient_info=patient_info,
            appointment_type=appt_type_key,
            start_time=start_time,
            duration_minutes=duration,
        )

    # ── Priority 3: Demo mode fallback (no real calendar configured) ────
    if _is_demo(tenant_ctx):
        result = _demo_booking(patient_info, start_time)
        logger.info("[Calendar DEMO] Booking created: %s", result)
        return result

    logger.warning("[Calendar] No calendar configured and not in demo mode — booking failed")
    return None


# ── Reschedule ────────────────────────────────────────────────────────────────


async def reschedule_appointment(
    booking_uid: str,
    new_start_time: str,
    reason: str = "",
    tenant_ctx: Any | None = None,
) -> dict[str, Any] | None:
    """Reschedule an existing booking."""
    slug = tenant_ctx.slug if tenant_ctx else "default"
    tz = tenant_ctx.timezone if tenant_ctx else settings.OFFICE_TIMEZONE

    # Invalidate slot cache — reschedule changes availability
    invalidate_slot_cache(slug)

    # ── Priority 1: Google Calendar (if the booking is a gcal event) ────
    if tenant_ctx and tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token:
        if booking_uid.startswith("gcal-"):
            duration, _ = _resolve_appointment_config("", tenant_ctx)
            logger.info("[Calendar][%s] Using Google Calendar for reschedule (duration=%d)", slug, duration)
            return await gcal.reschedule_appointment(
                refresh_token=tenant_ctx.google_calendar_refresh_token,
                event_id=booking_uid,
                new_start_time=new_start_time,
                duration_minutes=duration,
                timezone=tz,
            )

    # ── Native scheduling fallback ───────────────────────────────────────
    if tenant_ctx:
        logger.info("[Calendar][%s] Using native reschedule", slug)
        return await native_scheduling.reschedule_native_booking(booking_uid, new_start_time)

    # ── Demo mode fallback ──────────────────────────────────────────────
    if _is_demo(tenant_ctx):
        result = {"uid": booking_uid, "new_start": new_start_time, "status": "RESCHEDULED"}
        logger.info("[Calendar DEMO] Rescheduled booking %s → %s", booking_uid, new_start_time)
        return result

    logger.warning("[Calendar] No calendar configured and not in demo mode — reschedule failed")
    return None


# ── Cancellation ──────────────────────────────────────────────────────────────


async def cancel_appointment(
    booking_uid: str,
    reason: str = "",
    tenant_ctx: Any | None = None,
) -> bool:
    """Cancel a booking. Returns True on success."""
    slug = tenant_ctx.slug if tenant_ctx else "default"

    # Invalidate slot cache — cancellation frees up availability
    invalidate_slot_cache(slug)

    # ── Priority 1: Google Calendar (if the booking is a gcal event) ────
    if tenant_ctx and tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token:
        if booking_uid.startswith("gcal-"):
            logger.info("[Calendar][%s] Using Google Calendar for cancel", slug)
            return await gcal.cancel_appointment(
                refresh_token=tenant_ctx.google_calendar_refresh_token,
                event_id=booking_uid,
            )

    # ── Native scheduling fallback ───────────────────────────────────────
    if tenant_ctx:
        logger.info("[Calendar][%s] Using native cancel", slug)
        return await native_scheduling.cancel_native_booking(booking_uid, reason)

    # ── Demo mode fallback ──────────────────────────────────────────────
    if _is_demo(tenant_ctx):
        logger.info("[Calendar DEMO] Cancelled booking %s — reason: %s", booking_uid, reason)
        return True

    logger.warning("[Calendar] No calendar configured and not in demo mode — cancel failed")
    return False


# ── Demo helpers (used when demo_mode=True) ───────────────────────────────────


def _demo_slots(date_from: str) -> list[str]:
    """Return fake slots for demo purposes."""
    from datetime import timedelta

    base = datetime.fromisoformat(date_from)
    slots = []
    for hour in [9, 10, 11, 13, 14, 15, 16]:
        slot_dt = base.replace(hour=hour, minute=0, second=0)
        slots.append(slot_dt.isoformat())
    return slots


def _demo_booking(patient_info: dict, start_time: str) -> dict[str, Any]:
    """Return a fake booking response for demo purposes."""
    import uuid

    return {
        "id": str(uuid.uuid4()),
        "uid": f"demo-{uuid.uuid4().hex[:12]}",
        "status": "ACCEPTED",
    }
