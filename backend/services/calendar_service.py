"""
Calendar service — slot availability, booking, rescheduling, cancellation.

Tri-mode routing (checked in priority order):
  1. Google Calendar — if tenant has google_calendar_connected + refresh_token
  2. Cal.com         — if tenant has a calcom_api_key
  3. Native scheduler — Postgres-backed, uses business_hours + appointment_types
  4. Demo mode       — fake slots/bookings for testing (when demo_mode=True)

This means tenants can go live with Google Calendar (free), Cal.com, or
zero external dependencies (native scheduler only needs business hours).

Multi-tenant: every function accepts a TenantContext so it uses the correct
credentials, timezone, and event type mappings for the calling tenant.
"""

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from backend.config import settings
from backend.services import native_scheduling
from backend.services import google_calendar as gcal
from backend.services.http_client import http

logger = logging.getLogger(__name__)

CALCOM_BASE = "https://api.cal.com/v2"

# ── Slot availability cache ─────────────────────────────────────────────────
# During a single booking conversation the LLM often asks for the same date
# range 2-3 times (e.g. confirm → re-check → book). A short TTL avoids
# redundant Google Calendar / Cal.com API calls without risking stale data.
_SLOT_CACHE_TTL = 30  # seconds
_slot_cache: dict[str, tuple[float, list[str]]] = {}


def _slot_cache_key(
    event_type_id: str,
    date_from: str,
    date_to: str,
    tenant_slug: str,
    appointment_type_key: str,
    provider_id: str | None,
) -> str:
    return f"{tenant_slug}:{event_type_id}:{date_from}:{date_to}:{appointment_type_key}:{provider_id or ''}"


def invalidate_slot_cache(tenant_slug: str | None = None) -> None:
    """Clear cached slots — call after a booking/cancel/reschedule."""
    if tenant_slug:
        keys = [k for k in _slot_cache if k.startswith(f"{tenant_slug}:")]
        for k in keys:
            del _slot_cache[k]
    else:
        _slot_cache.clear()


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "cal-api-version": "2024-08-13",
    }


def _resolve_calcom_config(tenant_ctx: Any | None) -> tuple[str, str]:
    """
    Return (calcom_api_key, timezone) from TenantContext or fall back to global settings.
    """
    if tenant_ctx:
        return tenant_ctx.calcom_api_key, tenant_ctx.timezone
    return settings.CALCOM_API_KEY, settings.OFFICE_TIMEZONE


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

    # Try to match by key
    key = (appointment_type_key or "").lower().replace(" ", "_")
    for at in tenant_ctx.appointment_types:
        if at.get("key", "").lower() == key:
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
    event_type_id: str,
    date_from: str,
    date_to: str,
    tenant_ctx: Any | None = None,
    appointment_type_key: str = "",
    provider_id: str | None = None,
) -> list[str]:
    """
    Fetch available time slots.

    Routes to Google Calendar, native scheduler, Cal.com, or demo mode
    depending on the tenant's configuration.

    Args:
        event_type_id: Cal.com event type ID (used only for Cal.com path).
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
    cache_key = _slot_cache_key(event_type_id, date_from, date_to, slug, appointment_type_key, provider_id)
    cached = _slot_cache.get(cache_key)
    if cached:
        ts, slots = cached
        if (time.time() - ts) < _SLOT_CACHE_TTL:
            logger.info("[Calendar][%s] Slot cache HIT (%d slots, %.0fs old)",
                        slug, len(slots), time.time() - ts)
            return slots
        del _slot_cache[cache_key]

    api_key, tz = _resolve_calcom_config(tenant_ctx)

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

    # ── Priority 2: Cal.com (if API key is set) ─────────────────────────
    # (falls through to Cal.com HTTP calls below)

    # ── Priority 3: Native scheduling fallback (no Cal.com key) ─────────
    if not api_key and tenant_ctx:
        duration, max_conc = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        logger.info("[Calendar] No Cal.com key for %s — using native scheduler (type=%s, duration=%d, max_concurrent=%d)",
                    tenant_ctx.slug, appointment_type_key, duration, max_conc)

        return _cache_and_return(await native_scheduling.get_native_slots(
            date_str=date_from,
            duration_minutes=duration,
            tenant_id=tenant_ctx.tenant_id,
            business_hours=effective_hours,
            tz_name=tz,
            max_concurrent=max_conc,
        ))

    # ── Priority 4: Demo mode fallback (no real calendar configured) ────
    if _is_demo(tenant_ctx):
        demo_slots = _demo_slots(date_from)
        logger.info("[Cal.com DEMO] Returning %d fake slots for %s", len(demo_slots), date_from)
        return _cache_and_return(demo_slots)

    params = {
        "eventTypeId": event_type_id,
        "startTime": f"{date_from}T00:00:00Z",
        "endTime": f"{date_to}T23:59:59Z",
        "timeZone": tz,
    }
    logger.info("=" * 60)
    logger.info("[Cal.com][%s] GET /slots/available", slug)
    logger.info("[Cal.com][%s]   event_type_id: %s", slug, event_type_id)
    logger.info("[Cal.com][%s]   date_from:     %s", slug, date_from)
    logger.info("[Cal.com][%s]   date_to:       %s", slug, date_to)
    logger.info("[Cal.com][%s]   timezone:      %s", slug, tz)
    logger.info("[Cal.com][%s]   full params:   %s", slug, params)

    try:
        resp = await http.get(
            f"{CALCOM_BASE}/slots/available",
            headers=_headers(api_key),
            params=params,
        )
        logger.info("[Cal.com][%s]   HTTP status:   %d", slug, resp.status_code)
        resp.raise_for_status()
        data = resp.json()

        # Log the raw API response
        import json as _json
        raw_response = _json.dumps(data, indent=2, default=str)
        logger.info("[Cal.com][%s] RAW RESPONSE (truncated to 2000 chars):", slug)
        logger.info("[Cal.com][%s]   %s", slug, raw_response[:2000])

        # Cal.com returns slots grouped by date
        slots: list[str] = []
        slots_by_date = data.get("data", {}).get("slots", {})
        logger.info("[Cal.com][%s] Slots grouped by %d date(s):", slug, len(slots_by_date))

        for date_key, day_slots in slots_by_date.items():
            slot_times = []
            for slot in day_slots:
                slot_time = slot.get("time", slot) if isinstance(slot, dict) else slot
                slot_times.append(slot_time)
                slots.append(slot_time)
            logger.info("[Cal.com][%s]   %s → %d slots: %s", slug, date_key, len(slot_times), slot_times[:10])
            if len(slot_times) > 10:
                logger.info("[Cal.com][%s]     ... and %d more", slug, len(slot_times) - 10)

        logger.info("[Cal.com][%s] TOTAL: %d available slots for event type %s", slug, len(slots), event_type_id)
        logger.info("=" * 60)
        return _cache_and_return(slots)

    except httpx.HTTPStatusError as exc:
        logger.error("=" * 60)
        logger.error("[Cal.com][%s] SLOTS ERROR (HTTP %s)", slug, exc.response.status_code)
        logger.error("[Cal.com][%s]   URL:      %s/slots/available", slug, CALCOM_BASE)
        logger.error("[Cal.com][%s]   Params:   %s", slug, params)
        logger.error("[Cal.com][%s]   Response: %s", slug, exc.response.text[:1000])
        logger.error("=" * 60)
        return []
    except Exception as exc:
        logger.error("=" * 60)
        logger.error("[Cal.com][%s] SLOTS REQUEST FAILED: %s", slug, exc, exc_info=True)
        logger.error("[Cal.com][%s]   URL:    %s/slots/available", slug, CALCOM_BASE)
        logger.error("[Cal.com][%s]   Params: %s", slug, params)
        logger.error("=" * 60)
        return []


# ── Booking ───────────────────────────────────────────────────────────────────


async def book_appointment(
    event_type_id: str,
    patient_info: dict[str, Any],
    start_time: str,
    tenant_ctx: Any | None = None,
    appointment_type_key: str = "",
) -> dict[str, Any] | None:
    """
    Create a booking.

    Routes to Google Calendar, native scheduler, Cal.com, or demo mode.

    Args:
        event_type_id: Cal.com event type ID (used only for Cal.com path).
        patient_info: Dict with name, email, phone, insurance, dob.
        start_time: ISO datetime string for the slot.
        tenant_ctx: TenantContext for multi-tenant routing.
        appointment_type_key: Raw appointment type key (e.g. "consultation")
            used to resolve duration from tenant config.

    Returns:
        Dict with id, uid, status on success; None on failure.
    """
    api_key, tz = _resolve_calcom_config(tenant_ctx)
    slug = tenant_ctx.slug if tenant_ctx else "default"

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

    # ── Priority 2: Cal.com (falls through to HTTP calls below) ─────────

    # ── Priority 3: Native scheduling fallback (no Cal.com key) ─────────
    if not api_key and tenant_ctx:
        duration, _ = _resolve_appointment_config(appointment_type_key, tenant_ctx)
        appt_type_key = appointment_type_key or "consultation"
        logger.info("[Calendar][%s] No Cal.com key — using native booking (type=%s, duration=%d)", slug, appt_type_key, duration)

        return await native_scheduling.create_native_booking(
            tenant_id=tenant_ctx.tenant_id,
            patient_info=patient_info,
            appointment_type=appt_type_key,
            start_time=start_time,
            duration_minutes=duration,
        )

    # ── Priority 4: Demo mode fallback (no real calendar configured) ────
    if _is_demo(tenant_ctx):
        result = _demo_booking(patient_info, start_time)
        logger.info("[Cal.com DEMO] Booking created: %s", result)
        return result

    body = {
        "eventTypeId": int(event_type_id),
        "start": start_time,
        "attendee": {
            "name": patient_info.get("name", ""),
            "email": patient_info.get("email", "patient@example.com"),
            "timeZone": tz,
            "phoneNumber": patient_info.get("phone", ""),
        },
        "metadata": {
            "insurance": patient_info.get("insurance", ""),
            "dob": patient_info.get("dob", ""),
        },
    }

    import json as _json
    logger.info("=" * 60)
    logger.info("[Cal.com][%s] POST /bookings", slug)
    logger.info("[Cal.com][%s]   event_type_id: %s", slug, event_type_id)
    logger.info("[Cal.com][%s]   start_time:    %s", slug, start_time)
    logger.info("[Cal.com][%s]   patient:       %s (%s)", slug, patient_info.get("name"), patient_info.get("phone"))
    logger.info("[Cal.com][%s]   REQUEST BODY:  %s", slug, _json.dumps(body, indent=2)[:1000])

    try:
        resp = await http.post(
            f"{CALCOM_BASE}/bookings",
            headers=_headers(api_key),
            json=body,
        )
        logger.info("[Cal.com][%s]   HTTP status:   %d", slug, resp.status_code)

        # Log raw response even before raise_for_status
        raw_text = resp.text[:2000]
        logger.info("[Cal.com][%s]   RAW RESPONSE:  %s", slug, raw_text)

        resp.raise_for_status()
        data = resp.json().get("data", {})

        booking_result = {
            "id": str(data.get("id", "")),
            "uid": data.get("uid", ""),
            "status": data.get("status", "ACCEPTED"),
        }
        logger.info("[Cal.com][%s] ✓ BOOKING CREATED:", slug)
        logger.info("[Cal.com][%s]   id:     %s", slug, booking_result["id"])
        logger.info("[Cal.com][%s]   uid:    %s", slug, booking_result["uid"])
        logger.info("[Cal.com][%s]   status: %s", slug, booking_result["status"])
        logger.info("=" * 60)
        return booking_result

    except httpx.HTTPStatusError as exc:
        logger.error("=" * 60)
        logger.error("[Cal.com][%s] BOOKING ERROR (HTTP %s)", slug, exc.response.status_code)
        logger.error("[Cal.com][%s]   Request body: %s", slug, _json.dumps(body, indent=2)[:1000])
        logger.error("[Cal.com][%s]   Response:     %s", slug, exc.response.text[:1000])
        logger.error("=" * 60)
        return None
    except Exception as exc:
        logger.error("=" * 60)
        logger.error("[Cal.com][%s] BOOKING REQUEST FAILED: %s", slug, exc, exc_info=True)
        logger.error("[Cal.com][%s]   Request body: %s", slug, _json.dumps(body, indent=2)[:1000])
        logger.error("=" * 60)
        return None


# ── Reschedule ────────────────────────────────────────────────────────────────


async def reschedule_appointment(
    booking_uid: str,
    new_start_time: str,
    reason: str = "",
    tenant_ctx: Any | None = None,
) -> dict[str, Any] | None:
    """Reschedule an existing Cal.com booking."""
    api_key, tz = _resolve_calcom_config(tenant_ctx)
    slug = tenant_ctx.slug if tenant_ctx else "default"

    # Invalidate slot cache — reschedule changes availability
    invalidate_slot_cache(slug)

    # ── Priority 1: Google Calendar (if the booking is a gcal event) ────
    if tenant_ctx and tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token:
        if booking_uid.startswith("gcal-"):
            # For reschedule we don't know the exact appointment type from the
            # uid alone, so we fall back to first type's duration. This is
            # acceptable because reschedule just moves the event.
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
    if not api_key and tenant_ctx:
        logger.info("[Calendar][%s] No Cal.com key — using native reschedule", slug)
        return await native_scheduling.reschedule_native_booking(booking_uid, new_start_time)

    # ── Demo mode fallback ──────────────────────────────────────────────
    if _is_demo(tenant_ctx):
        result = {"uid": booking_uid, "new_start": new_start_time, "status": "RESCHEDULED"}
        logger.info("[Cal.com DEMO] Rescheduled booking %s → %s", booking_uid, new_start_time)
        return result

    logger.info("=" * 60)
    logger.info("[Cal.com][%s] POST /bookings/%s/reschedule", slug, booking_uid)
    logger.info("[Cal.com][%s]   new_start: %s", slug, new_start_time)
    logger.info("[Cal.com][%s]   reason:    %s", slug, reason or "(none)")

    try:
        resp = await http.post(
            f"{CALCOM_BASE}/bookings/{booking_uid}/reschedule",
            headers=_headers(api_key),
            json={"rescheduledReason": reason, "start": new_start_time},
        )
        logger.info("[Cal.com][%s]   HTTP status: %d", slug, resp.status_code)
        logger.info("[Cal.com][%s]   RAW RESPONSE: %s", slug, resp.text[:1000])
        resp.raise_for_status()
        data = resp.json().get("data", {})

        result = {"uid": data.get("uid", booking_uid), "new_start": new_start_time, "status": "RESCHEDULED"}
        logger.info("[Cal.com][%s] ✓ RESCHEDULED: %s → %s", slug, booking_uid, new_start_time)
        logger.info("=" * 60)
        return result

    except httpx.HTTPStatusError as exc:
        logger.error("[Cal.com][%s] RESCHEDULE ERROR (HTTP %s): %s", slug, exc.response.status_code, exc.response.text[:1000])
        logger.error("=" * 60)
        return None
    except Exception as exc:
        logger.error("[Cal.com][%s] RESCHEDULE FAILED: %s", slug, exc, exc_info=True)
        logger.error("=" * 60)
        return None


# ── Cancellation ──────────────────────────────────────────────────────────────


async def cancel_appointment(
    booking_uid: str,
    reason: str = "",
    tenant_ctx: Any | None = None,
) -> bool:
    """Cancel a Cal.com booking. Returns True on success."""
    api_key, _ = _resolve_calcom_config(tenant_ctx)
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
    if not api_key and tenant_ctx:
        logger.info("[Calendar][%s] No Cal.com key — using native cancel", slug)
        return await native_scheduling.cancel_native_booking(booking_uid, reason)

    # ── Demo mode fallback ──────────────────────────────────────────────
    if _is_demo(tenant_ctx):
        logger.info("[Cal.com DEMO] Cancelled booking %s — reason: %s", booking_uid, reason)
        return True

    logger.info("=" * 60)
    logger.info("[Cal.com][%s] POST /bookings/%s/cancel", slug, booking_uid)
    logger.info("[Cal.com][%s]   reason: %s", slug, reason or "(none)")

    try:
        resp = await http.post(
            f"{CALCOM_BASE}/bookings/{booking_uid}/cancel",
            headers=_headers(api_key),
            json={"cancellationReason": reason},
        )
        logger.info("[Cal.com][%s]   HTTP status: %d", slug, resp.status_code)
        logger.info("[Cal.com][%s]   RAW RESPONSE: %s", slug, resp.text[:1000])
        resp.raise_for_status()

        logger.info("[Cal.com][%s] ✓ CANCELLED booking %s", slug, booking_uid)
        logger.info("=" * 60)
        return True

    except httpx.HTTPStatusError as exc:
        logger.error("[Cal.com][%s] CANCEL ERROR (HTTP %s): %s", slug, exc.response.status_code, exc.response.text[:1000])
        logger.error("=" * 60)
        return False
    except Exception as exc:
        logger.error("[Cal.com][%s] CANCEL FAILED: %s", slug, exc, exc_info=True)
        logger.error("=" * 60)
        return False


# ── List bookings (live sync from Cal.com) ────────────────────────────────────


async def list_bookings(
    tenant_ctx: Any | None = None,
    after: str | None = None,
    take: int = 100,
) -> list[dict[str, Any]]:
    """
    Pull the tenant's recent bookings directly from Cal.com.

    Returns raw booking dicts as-returned by Cal.com v2. Caller is responsible
    for mapping these into the local Appointment table.

    Args:
        tenant_ctx: TenantContext with calcom_api_key
        after:  ISO date string — only return bookings starting at/after this date
        take:   max bookings to fetch (Cal.com paginates; this caps a single page)
    """
    api_key, _ = _resolve_calcom_config(tenant_ctx)
    if not api_key:
        if _is_demo(tenant_ctx):
            logger.info("[Cal.com DEMO] list_bookings → returning empty list (demo mode)")
            return []
        logger.warning("[Cal.com] list_bookings skipped — no API key configured")
        return []

    slug = tenant_ctx.slug if tenant_ctx else "default"
    params: dict[str, Any] = {"take": take}
    if after:
        params["afterStart"] = after

    logger.info("[Cal.com][%s] GET /bookings (params=%s)", slug, params)
    try:
        resp = await http.get(
            f"{CALCOM_BASE}/bookings",
            headers=_headers(api_key),
            params=params,
        )
        logger.info("[Cal.com][%s]   HTTP status: %d", slug, resp.status_code)
        resp.raise_for_status()
        data = resp.json()

        # Cal.com v2 returns { status, data: [...] }
        bookings = data.get("data") if isinstance(data, dict) else data
        bookings = bookings or []
        logger.info("[Cal.com][%s] ✓ list_bookings → %d bookings", slug, len(bookings))
        return bookings
    except httpx.HTTPStatusError as exc:
        logger.error(
            "[Cal.com][%s] list_bookings ERROR (HTTP %s): %s",
            slug, exc.response.status_code, exc.response.text[:500],
        )
        return []
    except Exception as exc:
        logger.error("[Cal.com][%s] list_bookings FAILED: %s", slug, exc, exc_info=True)
        return []


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
