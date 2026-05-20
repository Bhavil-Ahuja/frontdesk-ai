"""
Waitlist management service — manages the patient waitlist for cancellation
fill-ins across all tenants.

When no slots are available, the AI agent offers to add the patient to the
waitlist. When a cancellation opens a slot, the system automatically notifies
the highest-priority matching patient via SMS. If they reply YES, the slot
is booked for them; otherwise, the next person on the list is offered the slot.

Multi-tenant: every operation is scoped to a tenant_id. SMS notifications
use the tenant's own Twilio credentials via TenantContext.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, and_, update

from backend.database import async_session
from backend.models.waitlist import WaitlistEntry, WaitlistStatus
from backend.services import sms_service

logger = logging.getLogger(__name__)


# ── Add to waitlist ─────────────────────────────────────────────────────────


async def add_to_waitlist(
    tenant_id: uuid.UUID,
    patient_name: str,
    patient_phone: str,
    appointment_type: str,
    preferred_date: str,
    patient_email: str | None = None,
    preferred_time_start: str | None = None,
    preferred_time_end: str | None = None,
    provider_id: uuid.UUID | None = None,
) -> dict:
    """
    Add a patient to the waitlist for a specific date and appointment type.

    The entry is created with status=WAITING and expires_at set to 23:59:59 UTC
    on the preferred_date. When a matching cancellation occurs, the patient will
    be notified via SMS.

    Args:
        tenant_id: Tenant this waitlist entry belongs to.
        patient_name: Full name of the patient.
        patient_phone: Phone number for SMS notification.
        appointment_type: Type of appointment (e.g. "consultation", "follow_up").
        preferred_date: Desired date in YYYY-MM-DD format.
        patient_email: Optional email address.
        preferred_time_start: Optional preferred window start (HH:MM).
        preferred_time_end: Optional preferred window end (HH:MM).
        provider_id: Optional preferred provider UUID.

    Returns:
        Dict with the entry id and status for the LLM tool response.
    """
    try:
        target_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.error("[Waitlist] Invalid preferred_date format: %s", preferred_date)
        return {"error": "Invalid date format. Expected YYYY-MM-DD."}

    # Expire at end of the preferred date (23:59:59 UTC)
    expires_at = datetime.combine(
        target_date, datetime.max.time(), tzinfo=timezone.utc
    )

    entry = WaitlistEntry(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        patient_email=patient_email,
        appointment_type=appointment_type,
        preferred_date=preferred_date,
        preferred_time_start=preferred_time_start,
        preferred_time_end=preferred_time_end,
        provider_id=provider_id,
        status=WaitlistStatus.WAITING,
        expires_at=expires_at,
    )

    async with async_session() as session:
        session.add(entry)
        await session.commit()

    logger.info(
        "[Waitlist] Added %s to waitlist for %s on %s (id=%s)",
        patient_name,
        appointment_type,
        preferred_date,
        entry.id,
    )

    return {
        "id": str(entry.id),
        "status": WaitlistStatus.WAITING.value,
        "preferred_date": preferred_date,
        "appointment_type": appointment_type,
        "message": f"{patient_name} has been added to the waitlist for {appointment_type} on {preferred_date}.",
    }


# ── Query waitlist entries ──────────────────────────────────────────────────


async def get_waitlist_entries(
    tenant_id: uuid.UUID,
    status: WaitlistStatus | None = None,
    date: str | None = None,
) -> list[dict]:
    """
    Retrieve waitlist entries for a tenant, optionally filtered by status
    and/or preferred date.

    Args:
        tenant_id: Tenant to scope the query to.
        status: Optional WaitlistStatus filter (e.g. WAITING, NOTIFIED).
        date: Optional preferred_date filter in YYYY-MM-DD format.

    Returns:
        List of dicts, each containing full entry details.
    """
    filters = [WaitlistEntry.tenant_id == tenant_id]

    if status is not None:
        filters.append(WaitlistEntry.status == status)

    if date is not None:
        filters.append(WaitlistEntry.preferred_date == date)

    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry)
            .where(and_(*filters))
            .order_by(WaitlistEntry.priority.asc(), WaitlistEntry.created_at.asc())
        )
        entries = result.scalars().all()

    logger.info(
        "[Waitlist] Fetched %d entries for tenant %s (status=%s, date=%s)",
        len(entries),
        tenant_id,
        status,
        date,
    )

    return [
        {
            "id": str(e.id),
            "patient_name": e.patient_name,
            "patient_phone": e.patient_phone,
            "patient_email": e.patient_email,
            "appointment_type": e.appointment_type,
            "preferred_date": e.preferred_date,
            "preferred_time_start": e.preferred_time_start,
            "preferred_time_end": e.preferred_time_end,
            "provider_id": str(e.provider_id) if e.provider_id else None,
            "priority": e.priority,
            "status": e.status.value if e.status else None,
            "notified_at": e.notified_at.isoformat() if e.notified_at else None,
            "booked_at": e.booked_at.isoformat() if e.booked_at else None,
            "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


# ── Check waitlist for cancellation fill-in ─────────────────────────────────


async def check_waitlist_for_opening(
    tenant_id: uuid.UUID,
    appointment_type: str,
    date: str,
    available_slot: str,
    tenant_ctx: Any | None = None,
) -> bool:
    """
    Called when a cancellation creates an available slot. Finds the
    highest-priority WAITING entry matching the appointment type and date,
    then sends an SMS notification offering the slot.

    Matching logic:
      - appointment_type must match exactly.
      - preferred_date must match the given date.
      - If the entry has a preferred time window (preferred_time_start /
        preferred_time_end), the available_slot time must fall within that
        window. Entries with no time preference always match.
      - Ordered by priority ASC (lower = higher priority), then created_at ASC.

    Args:
        tenant_id: Tenant that owns the cancelled slot.
        appointment_type: The type of the cancelled appointment.
        date: The date of the cancelled slot (YYYY-MM-DD).
        available_slot: The available time slot as an ISO datetime string
            or HH:MM string (used for time-window matching and SMS text).
        tenant_ctx: Optional TenantContext for multi-tenant SMS sending.

    Returns:
        True if a waitlisted patient was notified, False otherwise.
    """
    # Parse the slot time for window-matching
    try:
        if "T" in available_slot:
            slot_dt = datetime.fromisoformat(available_slot)
            slot_time_str = slot_dt.strftime("%H:%M")
        else:
            slot_time_str = available_slot
    except (ValueError, TypeError):
        logger.error("[Waitlist] Invalid available_slot format: %s", available_slot)
        return False

    # Query all WAITING entries matching type + date for this tenant
    filters = [
        WaitlistEntry.tenant_id == tenant_id,
        WaitlistEntry.status == WaitlistStatus.WAITING,
        WaitlistEntry.appointment_type == appointment_type,
        WaitlistEntry.preferred_date == date,
    ]

    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry)
            .where(and_(*filters))
            .order_by(WaitlistEntry.priority.asc(), WaitlistEntry.created_at.asc())
        )
        candidates = list(result.scalars().all())

        if not candidates:
            logger.info(
                "[Waitlist] No WAITING entries for %s on %s (tenant %s)",
                appointment_type,
                date,
                tenant_id,
            )
            return False

        # Find the first candidate whose time window matches (or has no window)
        matched_entry: WaitlistEntry | None = None
        for entry in candidates:
            if entry.preferred_time_start and entry.preferred_time_end:
                # Check if the slot falls within the preferred window
                if entry.preferred_time_start <= slot_time_str <= entry.preferred_time_end:
                    matched_entry = entry
                    break
            elif entry.preferred_time_start:
                # Only a start time — slot must be at or after it
                if slot_time_str >= entry.preferred_time_start:
                    matched_entry = entry
                    break
            elif entry.preferred_time_end:
                # Only an end time — slot must be at or before it
                if slot_time_str <= entry.preferred_time_end:
                    matched_entry = entry
                    break
            else:
                # No time preference — any slot on this date works
                matched_entry = entry
                break

        if not matched_entry:
            logger.info(
                "[Waitlist] %d candidates found but none match time window for slot %s",
                len(candidates),
                available_slot,
            )
            return False

        # Update the matched entry: NOTIFIED + timestamp
        now = datetime.now(timezone.utc)
        matched_entry.status = WaitlistStatus.NOTIFIED
        matched_entry.notified_at = now
        await session.commit()

    # Format a human-readable date and time for the SMS
    try:
        display_date = datetime.strptime(date, "%Y-%m-%d").strftime("%B %d")
    except ValueError:
        display_date = date

    # Format display time (e.g. "2:30 PM")
    try:
        h, m = map(int, slot_time_str.split(":"))
        slot_dt_for_display = datetime(2000, 1, 1, h, m)
        display_time = slot_dt_for_display.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        display_time = slot_time_str

    display_type = appointment_type.replace("_", " ").title()

    sms_body = (
        f"Hi {matched_entry.patient_name}! Great news — a {display_type} slot "
        f"just opened up on {display_date} at {display_time}. Reply YES to "
        f"book it or it will go to the next person on our waitlist."
    )

    ok = sms_service._send_sms(
        to=matched_entry.patient_phone,
        body=sms_body,
        tenant_ctx=tenant_ctx,
    )
    if ok:
        sms_service._log_outbound_sms(
            tenant_ctx,
            to_number=matched_entry.patient_phone,
            body=sms_body,
            patient_phone=matched_entry.patient_phone,
        )

    logger.info(
        "[Waitlist] Notified %s (%s) about %s slot on %s at %s (entry %s)",
        matched_entry.patient_name,
        matched_entry.patient_phone,
        appointment_type,
        date,
        display_time,
        matched_entry.id,
    )

    return True


# ── Confirm waitlist booking ────────────────────────────────────────────────


async def confirm_waitlist_booking(
    patient_phone: str,
    tenant_id: uuid.UUID,
) -> dict | None:
    """
    Confirm a waitlist booking when a patient replies YES to the SMS
    notification. Finds the most recently notified entry for this phone
    number and tenant, then marks it as BOOKED.

    Args:
        patient_phone: The phone number that replied YES.
        tenant_id: The tenant the patient belongs to.

    Returns:
        Dict with the booked entry details (so the caller can create the
        actual appointment), or None if no matching NOTIFIED entry was found.
    """
    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry)
            .where(
                and_(
                    WaitlistEntry.patient_phone == patient_phone,
                    WaitlistEntry.tenant_id == tenant_id,
                    WaitlistEntry.status == WaitlistStatus.NOTIFIED,
                )
            )
            .order_by(WaitlistEntry.notified_at.desc())
            .limit(1)
        )
        entry = result.scalars().first()

        if not entry:
            logger.info(
                "[Waitlist] No NOTIFIED entry found for phone %s (tenant %s)",
                patient_phone,
                tenant_id,
            )
            return None

        now = datetime.now(timezone.utc)
        entry.status = WaitlistStatus.BOOKED
        entry.booked_at = now
        await session.commit()

    logger.info(
        "[Waitlist] Confirmed booking for %s — %s on %s (entry %s)",
        entry.patient_name,
        entry.appointment_type,
        entry.preferred_date,
        entry.id,
    )

    return {
        "id": str(entry.id),
        "patient_name": entry.patient_name,
        "patient_phone": entry.patient_phone,
        "patient_email": entry.patient_email,
        "appointment_type": entry.appointment_type,
        "preferred_date": entry.preferred_date,
        "preferred_time_start": entry.preferred_time_start,
        "preferred_time_end": entry.preferred_time_end,
        "provider_id": str(entry.provider_id) if entry.provider_id else None,
        "status": WaitlistStatus.BOOKED.value,
        "booked_at": now.isoformat(),
    }


# ── Cancel a waitlist entry ─────────────────────────────────────────────────


async def cancel_waitlist_entry(entry_id: uuid.UUID) -> bool:
    """
    Cancel a specific waitlist entry by setting its status to CANCELLED.

    Args:
        entry_id: The UUID of the waitlist entry to cancel.

    Returns:
        True if the entry was found and cancelled, False otherwise.
    """
    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
        )
        entry = result.scalars().first()

        if not entry:
            logger.warning("[Waitlist] Cancel failed — entry %s not found", entry_id)
            return False

        if entry.status in (WaitlistStatus.BOOKED, WaitlistStatus.CANCELLED):
            logger.warning(
                "[Waitlist] Cancel skipped — entry %s already %s",
                entry_id,
                entry.status.value,
            )
            return False

        entry.status = WaitlistStatus.CANCELLED
        await session.commit()

    logger.info(
        "[Waitlist] Cancelled entry %s (%s, %s on %s)",
        entry_id,
        entry.patient_name,
        entry.appointment_type,
        entry.preferred_date,
    )

    return True


# ── Expire stale entries (background task) ──────────────────────────────────


async def expire_stale_entries() -> int:
    """
    Find all WAITING entries whose expires_at has passed and set their
    status to EXPIRED. Intended to be called periodically by a background
    task (e.g. every 30 minutes).

    Returns:
        The number of entries that were expired.
    """
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        result = await session.execute(
            update(WaitlistEntry)
            .where(
                and_(
                    WaitlistEntry.status == WaitlistStatus.WAITING,
                    WaitlistEntry.expires_at < now,
                )
            )
            .values(status=WaitlistStatus.EXPIRED)
        )
        expired_count = result.rowcount
        await session.commit()

    if expired_count > 0:
        logger.info("[Waitlist] Expired %d stale waitlist entries", expired_count)
    else:
        logger.debug("[Waitlist] No stale entries to expire")

    return expired_count
