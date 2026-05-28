"""
Native scheduling engine — computes availability and creates bookings
using the tenant's business_hours, appointment_types, and existing
Appointment records in Postgres. No external calendar dependency.

This is the platform-managed alternative: tenants just set their hours
and appointment types in Agent Config, and the system handles the rest.

If a tenant has connected Google Calendar, the caller (calendar_service)
should prefer Google Calendar. This module is the fallback for tenants without it.

Usage:
    from backend.services.native_scheduling import (
        get_native_slots,
        create_native_booking,
        cancel_native_booking,
        reschedule_native_booking,
    )
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.defaults import (
    DEFAULT_APPOINTMENT_DURATION_MINUTES,
    DEFAULT_BUSINESS_HOURS,
    DEFAULT_SLOT_INTERVAL_MINUTES,
    DEFAULT_TIMEZONE,
)
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia

logger = logging.getLogger(__name__)

# ── Day-of-week mapping (Python weekday → business_hours key) ────────────────

_DOW_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Slot interval from centralized defaults
_SLOT_INTERVAL = DEFAULT_SLOT_INTERVAL_MINUTES


# ── Availability ─────────────────────────────────────────────────────────────


async def get_native_slots(
    date_str: str,
    duration_minutes: int = DEFAULT_APPOINTMENT_DURATION_MINUTES,
    tenant_id: uuid.UUID | None = None,
    business_hours: dict[str, Any] | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
    max_concurrent: int = 1,
    exclude_booking_uid: str | None = None,
) -> list[str]:
    """
    Compute available time slots on `date_str` for an appointment of
    `duration_minutes` length.

    Supports concurrent bookings: instead of treating any overlap as a
    conflict, we count how many existing confirmed appointments overlap each
    candidate slot and only mark it unavailable when the count reaches
    ``max_concurrent``.

    All arithmetic is done in UTC so that overlap detection against DB
    appointments (stored in UTC) is correct.  The returned ISO strings
    include the tenant's timezone offset so downstream consumers (the LLM,
    ``create_native_booking``) can interpret them unambiguously.

    Algorithm:
      1. Look up business hours for that day of week
      2. Generate a grid of start times (every _SLOT_INTERVAL minutes) in
         the tenant's local timezone, then convert to UTC
      3. Fetch existing CONFIRMED appointments for that UTC range + tenant
      4. Count overlaps per slot — block only when count ≥ max_concurrent
      5. Return remaining slots as timezone-aware ISO datetime strings in
         the tenant's local timezone (e.g. "2026-05-06T09:00:00-05:00")

    Args:
        date_str: YYYY-MM-DD
        duration_minutes: how long the appointment is
        tenant_id: scope to this tenant's appointments
        business_hours: tenant's business_hours JSON (from Agent Config)
        tz_name: tenant's timezone string
        max_concurrent: how many overlapping bookings are allowed per slot
            before it's considered full. Default 1 (classic single-booking).
        exclude_booking_uid: if provided, excludes this booking from the
            overlap check. Used during rescheduling so the patient's own
            appointment doesn't block the new time they want to move to.

    Returns:
        List of ISO datetime strings with timezone offset
        (e.g. ["2026-05-06T09:00:00-05:00", ...])
    """
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning("[NativeSched] Invalid date: %s", date_str)
        return []

    # Resolve the tenant's timezone
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = ZoneInfo(DEFAULT_TIMEZONE)

    dow_key = _DOW_KEYS[target_date.weekday()]

    # ── Get business hours for this day ──────────────────────────────────
    if not business_hours:
        business_hours = DEFAULT_BUSINESS_HOURS

    day_hours = business_hours.get(dow_key)
    if not day_hours:
        logger.info("[NativeSched] %s (%s) is closed", date_str, dow_key)
        return []

    try:
        open_h, open_m = map(int, day_hours["open"].split(":"))
        close_h, close_m = map(int, day_hours["close"].split(":"))
    except (KeyError, ValueError) as exc:
        logger.warning("[NativeSched] Bad business hours for %s: %s", dow_key, exc)
        return []

    open_time = dtime(open_h, open_m)
    close_time = dtime(close_h, close_m)

    # ── Generate slot grid in local timezone, convert to UTC ─────────────
    # Use the smaller of the appointment duration and the default slot interval
    # so shorter appointments (e.g. 15 min) get finer-grained slots (:00, :15,
    # :30, :45) instead of only the default 30-min grid (:00, :30).
    effective_interval = min(duration_minutes, _SLOT_INTERVAL)

    candidate_slots_local: list[datetime] = []
    candidate_slots_utc: list[datetime] = []

    current_local = datetime.combine(target_date, open_time, tzinfo=local_tz)
    latest_start_local = datetime.combine(target_date, close_time, tzinfo=local_tz) - timedelta(minutes=duration_minutes)

    while current_local <= latest_start_local:
        candidate_slots_local.append(current_local)
        candidate_slots_utc.append(current_local.astimezone(timezone.utc))
        current_local += timedelta(minutes=effective_interval)

    if not candidate_slots_utc:
        return []

    # ── Fetch existing appointments for this day + tenant ────────────────
    # Query the UTC range that covers the local business day
    day_start_utc = candidate_slots_utc[0] - timedelta(hours=1)  # small buffer
    day_end_utc = candidate_slots_utc[-1] + timedelta(minutes=duration_minutes, hours=1)

    existing_appointments: list[Appointment] = []
    async with async_session() as session:
        query = select(Appointment).where(
            and_(
                Appointment.scheduled_at >= day_start_utc,
                Appointment.scheduled_at < day_end_utc,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        if tenant_id:
            query = query.where(Appointment.tenant_id == tenant_id)
        # Exclude the appointment being rescheduled so the patient's own
        # booking doesn't block the new slot they want to move to.
        if exclude_booking_uid:
            query = query.where(Appointment.cal_booking_uid != exclude_booking_uid)

        result = await session.execute(query)
        existing_appointments = list(result.scalars().all())

    logger.info("[NativeSched] %s: %d candidates, %d existing appts (max_concurrent=%d, exclude=%s)",
                date_str, len(candidate_slots_utc), len(existing_appointments), max_concurrent,
                exclude_booking_uid or "none")

    # ── Count overlaps per slot (all in UTC) ─────────────────────────────
    # Build list of (start_utc, end_utc) for existing appointments.
    # Each appointment's stored duration_minutes is the source of truth
    # (written from tenant config at booking time). The fallback to the
    # caller-supplied duration_minutes only fires for legacy rows with null.
    booked_ranges: list[tuple[datetime, datetime]] = []
    for appt in existing_appointments:
        appt_start = appt.scheduled_at
        # Ensure UTC-aware for comparison
        if appt_start.tzinfo is None:
            appt_start = appt_start.replace(tzinfo=timezone.utc)
        appt_end = appt_start + timedelta(minutes=appt.duration_minutes or duration_minutes)
        booked_ranges.append((appt_start, appt_end))

    available: list[str] = []
    now_local = datetime.now(local_tz)
    for slot_utc, slot_local in zip(candidate_slots_utc, candidate_slots_local):
        # Skip slots that are in the past (with 5-minute buffer)
        if slot_local < now_local - timedelta(minutes=5):
            continue
        slot_end_utc = slot_utc + timedelta(minutes=duration_minutes)
        overlap_count = 0
        for booked_start, booked_end in booked_ranges:
            # Two ranges overlap if one starts before the other ends AND vice versa
            if slot_utc < booked_end and slot_end_utc > booked_start:
                overlap_count += 1
                # Early exit: no need to keep counting past the limit
                if overlap_count >= max_concurrent:
                    break
        if overlap_count < max_concurrent:
            # Return in tenant's local timezone with offset for unambiguous parsing
            available.append(slot_local.isoformat())

    logger.info("[NativeSched] %s: %d available slots (after filtering, max_concurrent=%d)",
                date_str, len(available), max_concurrent)
    return available


# ── Provider-aware availability ─────────────────────────────────────────────


async def get_provider_aware_slots(
    date_str: str,
    duration_minutes: int = DEFAULT_APPOINTMENT_DURATION_MINUTES,
    tenant_id: uuid.UUID | None = None,
    business_hours: dict[str, Any] | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
    provider_id: uuid.UUID | None = None,
    holidays: list[dict[str, Any]] | None = None,
    exclude_booking_uid: str | None = None,
) -> dict[str, Any]:
    """
    Get available slots with provider-level concurrency tracking.

    Unlike get_native_slots (which checks global concurrency), this function:
    - Considers each provider's max_concurrent limit separately
    - Returns which providers are available for each slot
    - Supports filtering to a specific provider

    Returns:
        {
            "slots": [
                {
                    "time": "2026-05-20T10:00:00-05:00",
                    "available_providers": [
                        {"id": "...", "name": "Dr. Smith", "slots_remaining": 1}
                    ]
                },
                ...
            ],
            "provider_filter": provider_id or None,
        }
    """
    from backend.models.provider import Provider

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning("[NativeSched] Invalid date: %s", date_str)
        return {"slots": [], "provider_filter": None}

    # ── Holiday short-circuit ────────────────────────────────────────────
    # If the requested date is on the tenant's holidays list, the office
    # is closed — no slots regardless of business_hours. Surface the
    # holiday name so callers can tell the user why.
    holiday_match: dict[str, Any] | None = None
    if holidays:
        for h in holidays:
            if isinstance(h, dict) and h.get("date") == date_str:
                holiday_match = {
                    "date": h["date"],
                    "name": (h.get("name") or "Holiday"),
                }
                break
    if holiday_match:
        logger.info(
            "[NativeSched] %s is a holiday (%s) for tenant %s — no slots",
            date_str, holiday_match["name"], tenant_id,
        )
        return {
            "slots": [],
            "provider_filter": str(provider_id) if provider_id else None,
            "holiday": holiday_match,
        }

    # Resolve timezone
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = ZoneInfo(DEFAULT_TIMEZONE)

    dow_key = _DOW_KEYS[target_date.weekday()]

    # Default business hours
    if not business_hours:
        business_hours = DEFAULT_BUSINESS_HOURS

    day_hours = business_hours.get(dow_key)
    if not day_hours:
        logger.info("[NativeSched] %s (%s) is closed", date_str, dow_key)
        return {"slots": [], "provider_filter": str(provider_id) if provider_id else None}

    try:
        open_h, open_m = map(int, day_hours["open"].split(":"))
        close_h, close_m = map(int, day_hours["close"].split(":"))
    except (KeyError, ValueError) as exc:
        logger.warning("[NativeSched] Bad business hours for %s: %s", dow_key, exc)
        return {"slots": [], "provider_filter": str(provider_id) if provider_id else None}

    open_time = dtime(open_h, open_m)
    close_time = dtime(close_h, close_m)

    # Generate candidate slots — use finer granularity for shorter appointments
    effective_interval = min(duration_minutes, _SLOT_INTERVAL)

    candidate_slots_local: list[datetime] = []
    candidate_slots_utc: list[datetime] = []

    current_local = datetime.combine(target_date, open_time, tzinfo=local_tz)
    latest_start_local = datetime.combine(target_date, close_time, tzinfo=local_tz) - timedelta(minutes=duration_minutes)

    while current_local <= latest_start_local:
        candidate_slots_local.append(current_local)
        candidate_slots_utc.append(current_local.astimezone(timezone.utc))
        current_local += timedelta(minutes=effective_interval)

    if not candidate_slots_utc:
        return {"slots": [], "provider_filter": str(provider_id) if provider_id else None}

    # Get providers
    async with async_session() as session:
        provider_query = select(Provider).where(
            and_(
                Provider.tenant_id == tenant_id,
                Provider.is_active == True,
            )
        )
        if provider_id:
            provider_query = provider_query.where(Provider.id == provider_id)

        provider_result = await session.execute(provider_query)
        providers = list(provider_result.scalars().all())

    if not providers:
        # No providers configured — fall back to global slot availability
        logger.info("[NativeSched] No providers found, using global availability")
        simple_slots = await get_native_slots(
            date_str, duration_minutes, tenant_id, business_hours, tz_name,
            max_concurrent=1, exclude_booking_uid=exclude_booking_uid,
        )
        return {
            "slots": [{"time": s, "available_providers": []} for s in simple_slots],
            "provider_filter": None,
        }

    # Get existing appointments for this day
    day_start_utc = candidate_slots_utc[0] - timedelta(hours=1)
    day_end_utc = candidate_slots_utc[-1] + timedelta(minutes=duration_minutes, hours=1)

    async with async_session() as session:
        appt_query = select(Appointment).where(
            and_(
                Appointment.tenant_id == tenant_id,
                Appointment.scheduled_at >= day_start_utc,
                Appointment.scheduled_at < day_end_utc,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        )
        # Exclude the appointment being rescheduled so the patient's own
        # booking doesn't block the new slot they want to move to.
        if exclude_booking_uid:
            appt_query = appt_query.where(Appointment.cal_booking_uid != exclude_booking_uid)

        appt_result = await session.execute(appt_query)
        existing_appointments = list(appt_result.scalars().all())

    # Build lookup: provider_id → list of (start_utc, end_utc)
    provider_bookings: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {p.id: [] for p in providers}
    for appt in existing_appointments:
        if appt.provider_id and appt.provider_id in provider_bookings:
            appt_start = appt.scheduled_at
            if appt_start.tzinfo is None:
                appt_start = appt_start.replace(tzinfo=timezone.utc)
            appt_end = appt_start + timedelta(minutes=appt.duration_minutes or duration_minutes)
            provider_bookings[appt.provider_id].append((appt_start, appt_end))

    # For each slot, check each provider's availability
    now_local = datetime.now(local_tz)
    result_slots = []

    for slot_utc, slot_local in zip(candidate_slots_utc, candidate_slots_local):
        # Skip past slots
        if slot_local < now_local - timedelta(minutes=5):
            continue

        slot_end_utc = slot_utc + timedelta(minutes=duration_minutes)
        available_providers = []

        for provider in providers:
            bookings = provider_bookings.get(provider.id, [])
            overlap_count = 0
            for booked_start, booked_end in bookings:
                if slot_utc < booked_end and slot_end_utc > booked_start:
                    overlap_count += 1

            max_conc = provider.max_concurrent or 1
            if overlap_count < max_conc:
                available_providers.append({
                    "id": str(provider.id),
                    "name": provider.name,
                    "title": provider.title,
                    "slots_remaining": max_conc - overlap_count,
                })

        if available_providers:
            result_slots.append({
                "time": slot_local.isoformat(),
                "available_providers": available_providers,
            })

    logger.info("[NativeSched] %s: %d slots with provider availability (providers=%d, appts=%d)",
                date_str, len(result_slots), len(providers), len(existing_appointments))

    return {
        "slots": result_slots,
        "provider_filter": str(provider_id) if provider_id else None,
    }


# ── Booking ──────────────────────────────────────────────────────────────────


async def create_native_booking(
    tenant_id: uuid.UUID | None,
    patient_info: dict[str, str],
    appointment_type: str,
    start_time: str,
    duration_minutes: int = DEFAULT_APPOINTMENT_DURATION_MINUTES,
    provider_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """
    Create a booking directly in the Appointment table.

    Returns dict with id, uid, status on success; None on failure.
    Returns a dict with status="CONFLICT" if the unique index fires (someone
    booked the same provider at the same instant — race lost).
    """
    try:
        scheduled_at = datetime.fromisoformat(start_time)
        # Ensure timezone-aware — if the string has an offset (e.g. from
        # get_native_slots), fromisoformat handles it and we convert to UTC
        # for storage. If naive, assume UTC for backwards-compat.
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        else:
            scheduled_at = scheduled_at.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        logger.error("[NativeSched] Bad start_time: %s — %s", start_time, exc)
        return None

    booking_uid = f"native-{uuid.uuid4().hex[:12]}"

    # Normalise phone so it matches patient lookups (E.164 format)
    from backend.services.patient_service import _normalise_phone, upsert_patient
    norm_phone = _normalise_phone(patient_info.get("phone", ""))

    # Upsert the patient record so caller recognition works on next call
    await upsert_patient(
        name=patient_info.get("name", ""),
        phone=norm_phone,
        dob=patient_info.get("dob", ""),
        email=patient_info.get("email", ""),
        appointment_type=appointment_type,
        tenant_id=tenant_id,
    )

    # Local import to avoid a hard dependency on SQLAlchemy at import time
    from sqlalchemy.exc import IntegrityError

    try:
        async with async_session() as session:
            appt = Appointment(
                tenant_id=tenant_id,
                cal_booking_uid=booking_uid,
                patient_name=patient_info.get("name", ""),
                patient_phone=norm_phone,
                patient_email=patient_info.get("email", ""),
                date_of_birth=patient_info.get("dob", ""),
                appointment_type=appointment_type,
                scheduled_at=scheduled_at,
                duration_minutes=duration_minutes,
                status=AppointmentStatus.CONFIRMED,
                booked_via=BookedVia.AI,
                provider_id=provider_id,
            )
            session.add(appt)
            await session.commit()
            await session.refresh(appt)
    except IntegrityError as exc:
        # Unique-index violation = slot already taken by another booking
        # since we last checked availability. Surface this so the caller can
        # tell the patient "sorry, that slot was just taken — pick another."
        logger.warning(
            "[NativeSched] Booking conflict for provider=%s at %s (uid=%s): %s",
            provider_id, scheduled_at, booking_uid, str(exc.orig)[:160],
        )
        return {"status": "CONFLICT", "reason": "slot_taken"}

    result = {
        "id": str(appt.id),
        "uid": booking_uid,
        "status": "ACCEPTED",
    }
    logger.info("[NativeSched] ✓ Booking created: %s for %s @ %s (%d min, provider=%s)",
                booking_uid, patient_info.get("name"), start_time, duration_minutes, provider_id)
    return result


# ── Cancellation ─────────────────────────────────────────────────────────────


async def cancel_native_booking(
    booking_uid: str,
    reason: str = "",
) -> bool:
    """Cancel an appointment by its booking UID. Returns True on success."""
    async with async_session() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.cal_booking_uid == booking_uid)
        )
        appt = result.scalar_one_or_none()
        if not appt:
            logger.warning("[NativeSched] Cancel failed — no booking with uid=%s", booking_uid)
            return False

        appt.status = AppointmentStatus.CANCELLED
        appt.notes = (appt.notes or "") + f"\nCancelled: {reason}" if reason else appt.notes
        await session.commit()

    logger.info("[NativeSched] ✓ Cancelled booking %s (reason: %s)", booking_uid, reason or "none")
    return True


# ── Reschedule ───────────────────────────────────────────────────────────────


async def reschedule_native_booking(
    booking_uid: str,
    new_start_time: str,
) -> dict[str, Any] | None:
    """Reschedule an appointment to a new time. Returns result dict or None."""
    try:
        new_dt = datetime.fromisoformat(new_start_time)
        # Convert to UTC for storage — handles both tz-aware and naive inputs
        if new_dt.tzinfo is None:
            new_dt = new_dt.replace(tzinfo=timezone.utc)
        else:
            new_dt = new_dt.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        logger.error("[NativeSched] Bad new_start_time: %s — %s", new_start_time, exc)
        return None

    async with async_session() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.cal_booking_uid == booking_uid)
        )
        appt = result.scalar_one_or_none()
        if not appt:
            logger.warning("[NativeSched] Reschedule failed — no booking with uid=%s", booking_uid)
            return None

        old_time = appt.scheduled_at.isoformat() if appt.scheduled_at else "unknown"
        appt.scheduled_at = new_dt
        appt.status = AppointmentStatus.CONFIRMED  # reset from RESCHEDULED if needed
        await session.commit()

    logger.info("[NativeSched] ✓ Rescheduled %s: %s → %s", booking_uid, old_time, new_start_time)
    return {"uid": booking_uid, "new_start": new_start_time, "status": "RESCHEDULED"}
