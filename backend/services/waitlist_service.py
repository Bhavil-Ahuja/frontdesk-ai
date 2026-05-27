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
    tenant_ctx: Any | None = None,
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

    # ── Past-date guard ────────────────────────────────────────────────
    # Adding a patient to the waitlist for a date that has already passed
    # is never useful — we'd just create an entry that immediately expires.
    # Refuse with a clear message so the LLM tells the patient to pick a
    # future date instead of silently confirming a useless waitlist entry.
    try:
        from zoneinfo import ZoneInfo
        tz_name = (
            getattr(tenant_ctx, "timezone", None) if tenant_ctx else None
        ) or "America/Chicago"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("America/Chicago")
        today_local = datetime.now(tz).date()
    except Exception:
        today_local = datetime.utcnow().date()

    if target_date < today_local:
        friendly = target_date.strftime("%A, %B %d")
        logger.warning(
            "[Waitlist] Refused add for past date %s (today=%s, patient=%s)",
            preferred_date, today_local.isoformat(), patient_name,
        )
        return {
            "ok": False,
            "error": "past_date",
            "preferred_date": preferred_date,
            "today": today_local.isoformat(),
            "summary_for_assistant": (
                f"That date ({friendly}) has already passed — today is "
                f"{today_local.strftime('%A, %B %d, %Y')}. Tell the patient the date "
                f"is in the past and ask which upcoming day they'd prefer. Do NOT add "
                f"them to the waitlist for a past date."
            ),
        }

    # ── Holiday guard ──────────────────────────────────────────────────
    # If the preferred date is a configured tenant holiday, the office is
    # closed — adding a waitlist entry would never resolve since no slots
    # exist. Refuse with a clear message naming the holiday so the LLM can
    # explain the closure to the patient.
    holiday_match: dict | None = None
    try:
        holidays = (
            getattr(tenant_ctx, "holidays", None) if tenant_ctx else None
        ) or []
        for h in holidays:
            if isinstance(h, dict) and h.get("date") == preferred_date:
                holiday_match = {
                    "date": h["date"],
                    "name": (h.get("name") or "Holiday"),
                }
                break
    except Exception:
        holiday_match = None

    if holiday_match:
        friendly = target_date.strftime("%A, %B %d")
        holiday_name = holiday_match["name"]
        logger.info(
            "[Waitlist] Refused add for holiday %s (%s) — patient=%s",
            preferred_date, holiday_name, patient_name,
        )
        return {
            "ok": False,
            "error": "holiday",
            "preferred_date": preferred_date,
            "holiday": holiday_match,
            "summary_for_assistant": (
                f"The office is CLOSED on {friendly} for {holiday_name}. "
                f"Tell the patient we're closed that day for {holiday_name} and ask "
                f"which other day works. Do NOT add them to the waitlist for a holiday."
            ),
        }

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

    # Notify the patient by SMS that they've been added to the waitlist
    try:
        sms_service.send_waitlist_added(
            patient_name=patient_name,
            phone=patient_phone,
            appointment_type=appointment_type,
            preferred_date=preferred_date,
            preferred_time_start=preferred_time_start,
            preferred_time_end=preferred_time_end,
            tenant_ctx=tenant_ctx,
        )
    except Exception as exc:
        logger.error("[Waitlist] Failed to send 'added' SMS for entry %s: %s", entry.id, exc)

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
    provider_id: uuid.UUID | None = None,
) -> bool:
    """
    Called when a cancellation creates an available slot. Finds the
    highest-priority WAITING entry matching the appointment type and date,
    then sends an SMS notification offering the slot.

    Matching logic:
      - appointment_type must match exactly.
      - preferred_date must match the given date.
      - PROVIDER MATCH: If the cancelled slot has a provider_id, only notify
        entries that requested either that same provider OR no provider at
        all. We never push a patient onto a provider they didn't request.
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
        provider_id: Optional UUID of the provider whose slot just opened.
            When set, only entries that requested this provider (or no
            provider) are eligible.

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

    # Query all WAITING entries matching type + date for this tenant.
    # Provider filtering is enforced via OR in the WHERE so the DB only
    # returns rows that requested THIS provider or no provider at all.
    from sqlalchemy import or_  # local import to avoid widening top-level surface

    filters = [
        WaitlistEntry.tenant_id == tenant_id,
        WaitlistEntry.status == WaitlistStatus.WAITING,
        WaitlistEntry.appointment_type == appointment_type,
        WaitlistEntry.preferred_date == date,
    ]
    if provider_id is not None:
        filters.append(
            or_(
                WaitlistEntry.provider_id == provider_id,
                WaitlistEntry.provider_id.is_(None),
            )
        )

    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry)
            .where(and_(*filters))
            .order_by(WaitlistEntry.priority.asc(), WaitlistEntry.created_at.asc())
        )
        candidates = list(result.scalars().all())

        if not candidates:
            logger.info(
                "[Waitlist] No WAITING entries for %s on %s (tenant %s, provider=%s)",
                appointment_type,
                date,
                tenant_id,
                provider_id,
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


async def cancel_waitlist_entry(
    entry_id: uuid.UUID,
    tenant_ctx: Any | None = None,
) -> bool:
    """
    Cancel a specific waitlist entry by setting its status to CANCELLED.

    Args:
        entry_id: The UUID of the waitlist entry to cancel.
        tenant_ctx: Optional TenantContext for sending the patient SMS.

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

        # Snapshot fields we need for the SMS before the session closes
        patient_name = entry.patient_name
        patient_phone = entry.patient_phone
        appointment_type = entry.appointment_type
        preferred_date = entry.preferred_date

        await session.commit()

    logger.info(
        "[Waitlist] Cancelled entry %s (%s, %s on %s)",
        entry_id,
        patient_name,
        appointment_type,
        preferred_date,
    )

    # Notify the patient that their waitlist entry was cancelled
    try:
        sms_service.send_waitlist_cancelled(
            patient_name=patient_name,
            phone=patient_phone,
            appointment_type=appointment_type,
            preferred_date=preferred_date,
            tenant_ctx=tenant_ctx,
        )
    except Exception as exc:
        logger.error("[Waitlist] Failed to send 'cancelled' SMS for entry %s: %s", entry_id, exc)

    return True


# ── Promote a waitlist entry to a real appointment ─────────────────────────


async def find_promote_conflicts(
    entry_id: uuid.UUID,
    tenant_id: uuid.UUID,
    scheduled_at: str,
) -> dict:
    """
    Find existing appointments that would conflict with promoting a waitlist
    entry into the given slot.

    Returns appointments for the entry's preferred provider (or all providers
    if no provider preference) whose scheduled_at falls within a ±duration
    window of the proposed slot. The admin UI uses this to ask the user
    "this slot already has appointments — still promote?" before doing a
    force-bypass booking.

    Args:
        entry_id: UUID of the waitlist entry being promoted.
        tenant_id: Tenant scope (from authenticated user).
        scheduled_at: Proposed start time for the new booking (ISO string).

    Returns:
        {
          "conflicts": [<appointment dict>, ...],
          "provider_id": "<uuid or null>",
          "scheduled_at": "<iso>",
          "window_minutes": <int>,
        }
    """
    from backend.models.appointment import Appointment, AppointmentStatus
    from backend.models.provider import Provider

    # Parse the target time
    try:
        target_dt = datetime.fromisoformat(scheduled_at)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid scheduled_at: {scheduled_at!r}")
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    else:
        target_dt = target_dt.astimezone(timezone.utc)

    async with async_session() as session:
        # Load the entry to pull provider_id + appointment_type
        result = await session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
        )
        entry = result.scalars().first()
        if not entry:
            raise ValueError(f"Waitlist entry not found: {entry_id}")
        if entry.tenant_id != tenant_id:
            raise ValueError("Waitlist entry does not belong to this tenant.")

        entry_provider_id = entry.provider_id
        # Default duration window — 60 minutes covers typical appointment lengths
        window = timedelta(minutes=60)
        window_start = target_dt - window
        window_end = target_dt + window

        filters = [
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(
                [AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED]
            ),
            Appointment.scheduled_at >= window_start,
            Appointment.scheduled_at <= window_end,
        ]
        # If the entry targets a specific provider, narrow to that provider only.
        # If not, show conflicts across all providers (admin will pick a provider).
        if entry_provider_id is not None:
            filters.append(Appointment.provider_id == entry_provider_id)

        appt_rows = await session.execute(
            select(Appointment).where(and_(*filters)).order_by(Appointment.scheduled_at.asc())
        )
        appts = list(appt_rows.scalars().all())

        # Build a provider_id -> name map for friendly display
        provider_names: dict[str, str] = {}
        provider_ids = {a.provider_id for a in appts if a.provider_id}
        if provider_ids:
            prov_rows = await session.execute(
                select(Provider).where(Provider.id.in_(provider_ids))
            )
            for p in prov_rows.scalars().all():
                provider_names[str(p.id)] = p.name

    conflicts = [
        {
            "id": str(a.id),
            "patient_name": a.patient_name,
            "patient_phone": a.patient_phone,
            "appointment_type": a.appointment_type,
            "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
            "duration_minutes": a.duration_minutes,
            "status": a.status.value if a.status else None,
            "provider_id": str(a.provider_id) if a.provider_id else None,
            "provider_name": (
                provider_names.get(str(a.provider_id)) if a.provider_id else None
            ),
        }
        for a in appts
    ]

    logger.info(
        "[Waitlist] Conflict check for entry %s @ %s → %d conflicts (provider=%s)",
        entry_id, scheduled_at, len(conflicts), entry_provider_id,
    )

    return {
        "conflicts": conflicts,
        "provider_id": str(entry_provider_id) if entry_provider_id else None,
        "scheduled_at": scheduled_at,
        "window_minutes": int(window.total_seconds() // 60),
    }


async def promote_to_appointment(
    entry_id: uuid.UUID,
    scheduled_at: str,
    tenant_ctx: Any | None = None,
    force: bool = False,
) -> dict | None:
    """
    Promote a waitlist entry to a booked appointment.

    Books the appointment via calendar_service using the entry's patient info
    and the admin-supplied start time, then marks the entry as BOOKED and
    sends the patient a confirmation SMS.

    Args:
        entry_id: UUID of the waitlist entry to promote.
        scheduled_at: ISO datetime string for the booked slot.
        tenant_ctx: TenantContext for calendar routing + SMS.
        force: When True, bypass the provider/time uniqueness check by
            nudging the stored timestamp by a few seconds so the partial
            unique index doesn't fire. Use only when admin has explicitly
            confirmed the double-book in the UI.

    Returns:
        Dict with appointment + entry info on success, or None on failure.
    """
    # Lazy import to avoid circular imports (calendar_service imports a lot)
    from backend.services import calendar_service

    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
        )
        entry = result.scalars().first()

        if not entry:
            logger.warning("[Waitlist] Promote failed — entry %s not found", entry_id)
            return None

        if entry.status in (WaitlistStatus.BOOKED, WaitlistStatus.CANCELLED, WaitlistStatus.EXPIRED):
            logger.warning(
                "[Waitlist] Promote skipped — entry %s already %s",
                entry_id,
                entry.status.value,
            )
            return None

        # Snapshot the fields we need outside the session
        patient_info = {
            "name": entry.patient_name,
            "phone": entry.patient_phone,
            "email": entry.patient_email or "",
        }
        appointment_type = entry.appointment_type
        preferred_date = entry.preferred_date
        patient_name = entry.patient_name
        patient_phone = entry.patient_phone
        entry_provider_id = entry.provider_id

    # Book the appointment through the same path the AI uses
    booking_start = scheduled_at
    try:
        booking = await calendar_service.book_appointment(
            patient_info=patient_info,
            start_time=booking_start,
            tenant_ctx=tenant_ctx,
            appointment_type_key=appointment_type,
            provider_id=entry_provider_id,
        )
    except Exception as exc:
        logger.error("[Waitlist] Booking failed during promote of %s: %s", entry_id, exc)
        return None

    if not booking:
        logger.warning("[Waitlist] book_appointment returned None during promote of %s", entry_id)
        return None

    # The native path returns CONFLICT when the unique-index races. When the
    # admin has explicitly opted to force the double-book, retry with a tiny
    # offset (a few seconds) so the partial unique index on
    # (tenant_id, provider_id, scheduled_at) doesn't fire — the doctor has
    # explicitly agreed to take an overlapping appointment.
    if isinstance(booking, dict) and booking.get("status") == "CONFLICT":
        if force:
            try:
                forced_dt = datetime.fromisoformat(scheduled_at)
                if forced_dt.tzinfo is None:
                    forced_dt = forced_dt.replace(tzinfo=timezone.utc)
                # Walk forward by a few seconds at a time until the unique
                # index lets us in. Cap at 12 retries (~1 minute) — beyond
                # that something else is wrong.
                booking = None
                for offset in range(1, 13):
                    nudged = forced_dt + timedelta(seconds=offset * 5)
                    nudged_iso = nudged.isoformat()
                    try:
                        booking = await calendar_service.book_appointment(
                            patient_info=patient_info,
                            start_time=nudged_iso,
                            tenant_ctx=tenant_ctx,
                            appointment_type_key=appointment_type,
                            provider_id=entry_provider_id,
                        )
                    except Exception as exc:
                        logger.error(
                            "[Waitlist] Force-promote retry failed (offset=%ds): %s",
                            offset * 5, exc,
                        )
                        return None
                    if not booking:
                        return None
                    if isinstance(booking, dict) and booking.get("status") == "CONFLICT":
                        continue  # try next offset
                    # Success — record the actual booked time so callers + SMS
                    # show the slightly nudged timestamp.
                    booking_start = nudged_iso
                    logger.info(
                        "[Waitlist] Force-promote of %s succeeded with +%ds offset",
                        entry_id, offset * 5,
                    )
                    break
                else:
                    logger.warning(
                        "[Waitlist] Force-promote of %s exhausted offset retries",
                        entry_id,
                    )
                    return None
                # If after the loop we still hold a CONFLICT, give up.
                if isinstance(booking, dict) and booking.get("status") == "CONFLICT":
                    return None
            except (ValueError, TypeError) as exc:
                logger.error("[Waitlist] Force-promote parse failed: %s", exc)
                return None
        else:
            logger.warning(
                "[Waitlist] Promote of %s lost the unique-index race — slot %s already taken",
                entry_id, scheduled_at,
            )
            return None

    # Mark the entry BOOKED
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
        )
        entry = result.scalars().first()
        if entry:
            entry.status = WaitlistStatus.BOOKED
            entry.booked_at = now
            await session.commit()

    # SMS the patient about the promotion (use the time we actually booked,
    # which may be nudged a few seconds from `scheduled_at` for force-promote)
    try:
        sms_start = booking_start
        if isinstance(sms_start, str):
            try:
                start_dt = datetime.fromisoformat(sms_start)
            except ValueError:
                start_dt = datetime.strptime(sms_start, "%Y-%m-%dT%H:%M:%S")
        else:
            start_dt = sms_start
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        sms_service.send_waitlist_promoted(
            patient_name=patient_name,
            phone=patient_phone,
            appointment_type=appointment_type,
            scheduled_at=start_dt,
            tenant_ctx=tenant_ctx,
        )
    except Exception as exc:
        logger.error("[Waitlist] Failed to send 'promoted' SMS for entry %s: %s", entry_id, exc)

    logger.info(
        "[Waitlist] Promoted entry %s (%s, %s on %s) → booking %s",
        entry_id,
        patient_name,
        appointment_type,
        preferred_date,
        booking.get("uid") or booking.get("id"),
    )

    return {
        "id": str(entry_id),
        "status": WaitlistStatus.BOOKED.value,
        "booked_at": now.isoformat(),
        "appointment_type": appointment_type,
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "scheduled_at": booking_start,
        "forced": bool(force),
        "booking": booking,
    }


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
