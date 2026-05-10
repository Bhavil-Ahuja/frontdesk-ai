"""
Native scheduling engine — computes availability and creates bookings
using the tenant's business_hours, appointment_types, and existing
Appointment records in Postgres. No external Cal.com dependency.

This is the platform-managed alternative: tenants just set their hours
and appointment types in Agent Config, and the system handles the rest.

If a tenant HAS configured a Cal.com API key, the caller (calendar_service)
should prefer Cal.com. This module is the fallback for tenants without it.

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
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia

logger = logging.getLogger(__name__)

# ── Day-of-week mapping (Python weekday → business_hours key) ────────────────

_DOW_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Default slot interval in minutes (granularity of the scheduling grid)
_SLOT_INTERVAL = 30


# ── Availability ─────────────────────────────────────────────────────────────


async def get_native_slots(
    date_str: str,
    duration_minutes: int = 60,
    tenant_id: uuid.UUID | None = None,
    business_hours: dict[str, Any] | None = None,
    tz_name: str = "America/Chicago",
    max_concurrent: int = 1,
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
        local_tz = ZoneInfo("America/Chicago")

    dow_key = _DOW_KEYS[target_date.weekday()]

    # ── Get business hours for this day ──────────────────────────────────
    if not business_hours:
        # Default: Mon-Fri 8am-5pm, Sat-Sun closed
        business_hours = {
            "monday": {"open": "08:00", "close": "17:00"},
            "tuesday": {"open": "08:00", "close": "17:00"},
            "wednesday": {"open": "08:00", "close": "17:00"},
            "thursday": {"open": "08:00", "close": "17:00"},
            "friday": {"open": "08:00", "close": "17:00"},
        }

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
    candidate_slots_local: list[datetime] = []
    candidate_slots_utc: list[datetime] = []

    current_local = datetime.combine(target_date, open_time, tzinfo=local_tz)
    latest_start_local = datetime.combine(target_date, close_time, tzinfo=local_tz) - timedelta(minutes=duration_minutes)

    while current_local <= latest_start_local:
        candidate_slots_local.append(current_local)
        candidate_slots_utc.append(current_local.astimezone(timezone.utc))
        current_local += timedelta(minutes=_SLOT_INTERVAL)

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

        result = await session.execute(query)
        existing_appointments = list(result.scalars().all())

    logger.info("[NativeSched] %s: %d candidates, %d existing appts (max_concurrent=%d)",
                date_str, len(candidate_slots_utc), len(existing_appointments), max_concurrent)

    # ── Count overlaps per slot (all in UTC) ─────────────────────────────
    # Build list of (start_utc, end_utc) for existing appointments
    booked_ranges: list[tuple[datetime, datetime]] = []
    for appt in existing_appointments:
        appt_start = appt.scheduled_at
        # Ensure UTC-aware for comparison
        if appt_start.tzinfo is None:
            appt_start = appt_start.replace(tzinfo=timezone.utc)
        appt_end = appt_start + timedelta(minutes=appt.duration_minutes or 60)
        booked_ranges.append((appt_start, appt_end))

    available: list[str] = []
    for slot_utc, slot_local in zip(candidate_slots_utc, candidate_slots_local):
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


# ── Booking ──────────────────────────────────────────────────────────────────


async def create_native_booking(
    tenant_id: uuid.UUID | None,
    patient_info: dict[str, str],
    appointment_type: str,
    start_time: str,
    duration_minutes: int = 60,
) -> dict[str, Any] | None:
    """
    Create a booking directly in the Appointment table.

    Returns dict with id, uid, status on success; None on failure.
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

    async with async_session() as session:
        appt = Appointment(
            tenant_id=tenant_id,
            cal_booking_uid=booking_uid,
            patient_name=patient_info.get("name", ""),
            patient_phone=patient_info.get("phone", ""),
            patient_email=patient_info.get("email", ""),
            date_of_birth=patient_info.get("dob", ""),
            insurance_provider=patient_info.get("insurance", ""),
            appointment_type=appointment_type,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            status=AppointmentStatus.CONFIRMED,
            booked_via=BookedVia.AI,
        )
        session.add(appt)
        await session.commit()
        await session.refresh(appt)

    result = {
        "id": str(appt.id),
        "uid": booking_uid,
        "status": "ACCEPTED",
    }
    logger.info("[NativeSched] ✓ Booking created: %s for %s @ %s (%d min)",
                booking_uid, patient_info.get("name"), start_time, duration_minutes)
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
