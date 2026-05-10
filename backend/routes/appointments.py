"""
Appointment CRUD API routes.

GET  /api/appointments              → list with filters
POST /api/appointments/{id}/cancel  → manual cancellation
POST /api/appointments/sync-gcal    → bidirectional Google Calendar sync
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session, get_db
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia
from backend.models.tenant import Tenant
from backend.services import sms_service, auth_service, tenant_service, calendar_service
from backend.services import google_calendar as gcal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])


# ── Response schemas ──────────────────────────────────────────────────────────


class AppointmentOut(BaseModel):
    id: str
    cal_booking_uid: Optional[str]
    patient_name: str
    patient_phone: str
    patient_email: Optional[str]
    date_of_birth: Optional[str]
    appointment_type: str
    scheduled_at: datetime
    duration_minutes: int
    status: str
    booked_via: str
    notes: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    appointment_type: Optional[str] = None,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant UUID (admin-only)"),
    sync: int = Query(0, description="If 1, pull latest bookings from Cal.com before returning"),
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """List all appointments with optional filters. Auto-scoped to current tenant."""
    logger.info("Listing appointments for user=%s admin=%s status=%s type=%s sync=%d",
                current_user.owner_email, current_user.is_admin, status, appointment_type, sync)

    # Optional live sync from Cal.com → upsert into local Appointment table
    if sync and not current_user.is_admin:
        try:
            await _sync_calcom_bookings(current_user)
        except Exception as exc:
            logger.warning("Cal.com sync failed (non-fatal): %s", exc)

    query = select(Appointment)

    # Tenant scoping: non-admins only see their own
    if not current_user.is_admin:
        query = query.where(Appointment.tenant_id == current_user.id)
    elif tenant_id:
        try:
            tid = uuid.UUID(tenant_id)
            query = query.where(Appointment.tenant_id == tid)
        except ValueError:
            pass

    if status:
        try:
            query = query.where(Appointment.status == AppointmentStatus(status.upper()))
        except ValueError:
            pass
    if date_from:
        try:
            query = query.where(Appointment.scheduled_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.where(Appointment.scheduled_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    if appointment_type:
        query = query.where(Appointment.appointment_type.ilike(f"%{appointment_type}%"))

    query = query.order_by(desc(Appointment.scheduled_at))
    result = await db.execute(query)
    appointments = result.scalars().all()

    return [
        AppointmentOut(
            id=str(a.id),
            cal_booking_uid=a.cal_booking_uid,
            patient_name=a.patient_name,
            patient_phone=a.patient_phone,
            patient_email=a.patient_email,
            date_of_birth=a.date_of_birth,
            appointment_type=a.appointment_type,
            scheduled_at=a.scheduled_at,
            duration_minutes=a.duration_minutes,
            status=a.status.value,
            booked_via=a.booked_via.value,
            notes=a.notes,
            created_at=a.created_at,
        )
        for a in appointments
    ]


@router.post("/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Manually cancel an appointment from the dashboard."""
    try:
        uid = uuid.UUID(appointment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment ID format.")

    result = await db.execute(select(Appointment).where(Appointment.id == uid))
    apt = result.scalar_one_or_none()
    if apt is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if not current_user.is_admin and apt.tenant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied.")

    if apt.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Appointment is already cancelled.")

    apt.status = AppointmentStatus.CANCELLED
    await db.flush()

    # Send cancellation SMS with tenant context for correct Twilio credentials
    tenant_ctx = None
    if apt.tenant_id:
        tenant_ctx = await tenant_service.resolve_by_id(apt.tenant_id)
    sms_service.send_cancellation(
        patient_name=apt.patient_name,
        phone=apt.patient_phone,
        scheduled_at=apt.scheduled_at,
        tenant_ctx=tenant_ctx,
    )

    # Auto-cancel in Google Calendar if the appointment has a gcal- uid
    gcal_cancelled = False
    if (
        apt.cal_booking_uid
        and apt.cal_booking_uid.startswith("gcal-")
        and current_user.google_calendar_connected
        and current_user.google_calendar_refresh_token
    ):
        try:
            gcal_cancelled = await gcal.cancel_appointment(
                refresh_token=current_user.google_calendar_refresh_token,
                event_id=apt.cal_booking_uid,
            )
            if gcal_cancelled:
                logger.info("Appointment %s also cancelled in Google Calendar.", appointment_id)
            else:
                logger.warning("Appointment %s — GCal cancel returned False.", appointment_id)
        except Exception as exc:
            logger.warning("Appointment %s — GCal cancel failed (non-fatal): %s", appointment_id, exc)

    logger.info("Appointment %s manually cancelled.", appointment_id)
    return {"status": "cancelled", "id": appointment_id, "gcal_cancelled": gcal_cancelled}


# ── Google Calendar bidirectional sync ────────────────────────────────────────


@router.post("/sync-gcal")
async def sync_google_calendar(
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Bidirectional sync between the local Appointment table and Google Calendar.

    1. Pull: Fetch future events from Google Calendar → upsert into DB
    2. Push: Find DB appointments missing from Google Calendar → create GCal events

    Returns sync stats: { pulled, pushed, errors, total }.
    """
    if not current_user.google_calendar_connected or not current_user.google_calendar_refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected. Please connect it in Settings first.",
        )

    refresh_token = current_user.google_calendar_refresh_token
    tenant_tz = current_user.timezone or "America/Chicago"
    now = datetime.now(timezone.utc)
    # Sync window: from now to 90 days in the future
    time_min = now.isoformat()
    time_max = (now + timedelta(days=90)).isoformat()

    pulled = 0
    pushed = 0
    errors = 0

    # ── PULL: Google Calendar → DB ────────────────────────────────────────
    # show_deleted=True so we can detect events cancelled directly in GCal
    try:
        gcal_events = await gcal.list_events(
            refresh_token=refresh_token,
            time_min=time_min,
            time_max=time_max,
            show_deleted=True,
        )
    except Exception as exc:
        logger.error("[GCalSync] Failed to list GCal events: %s", exc)
        gcal_events = []
        errors += 1

    for event in gcal_events:
        try:
            event_id = event.get("id", "")
            if not event_id:
                continue

            gcal_uid = f"gcal-{event_id}"
            gcal_status = event.get("status", "confirmed")

            # Cancelled events from GCal may lack start/end — handle them specially
            if gcal_status == "cancelled":
                existing = (
                    await db.execute(
                        select(Appointment).where(
                            Appointment.cal_booking_uid == gcal_uid,
                            Appointment.tenant_id == current_user.id,
                        )
                    )
                ).scalar_one_or_none()
                if existing and existing.status != AppointmentStatus.CANCELLED:
                    existing.status = AppointmentStatus.CANCELLED
                    pulled += 1
                    logger.info("[GCalSync] Cancelled from GCal: %s (%s)", gcal_uid, existing.patient_name)
                continue

            # Skip all-day events (no dateTime means all-day)
            start_obj = event.get("start", {})
            end_obj = event.get("end", {})
            start_str = start_obj.get("dateTime")
            end_str = end_obj.get("dateTime")
            if not start_str:
                continue

            scheduled_at = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            duration = 60
            if end_str:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                duration = max(int((end_dt - scheduled_at).total_seconds() / 60), 5)

            summary = event.get("summary", "Appointment")
            description = event.get("description", "")
            local_status = AppointmentStatus.CONFIRMED

            # Parse patient info from event summary/description
            patient_name = summary
            # If summary follows our format "Appointment: Name", extract the name
            if summary.startswith("Appointment:"):
                patient_name = summary.replace("Appointment:", "").strip()

            patient_phone = ""
            patient_email = ""
            if description:
                # Try to extract phone/email from the description we write
                phone_match = re.search(r"Phone:\s*(\+?[\d\-\s()]+)", description)
                if phone_match:
                    patient_phone = phone_match.group(1).strip()
                email_match = re.search(r"Email:\s*(\S+@\S+)", description)
                if email_match:
                    patient_email = email_match.group(1).strip()

            # Also check attendees for email
            attendees = event.get("attendees", [])
            if attendees and not patient_email:
                patient_email = attendees[0].get("email", "")

            # Upsert by gcal uid
            existing = (
                await db.execute(
                    select(Appointment).where(
                        Appointment.cal_booking_uid == gcal_uid,
                        Appointment.tenant_id == current_user.id,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                existing.scheduled_at = scheduled_at
                existing.duration_minutes = duration
                existing.status = local_status
                if patient_name and patient_name != "Appointment":
                    existing.patient_name = patient_name
                if patient_email:
                    existing.patient_email = patient_email
                if patient_phone:
                    existing.patient_phone = patient_phone
            else:
                new_apt = Appointment(
                    tenant_id=current_user.id,
                    cal_booking_uid=gcal_uid,
                    patient_name=patient_name or "Unknown",
                    patient_phone=patient_phone,
                    patient_email=patient_email,
                    appointment_type=summary,
                    scheduled_at=scheduled_at,
                    duration_minutes=duration,
                    status=local_status,
                    booked_via=BookedVia.MANUAL,
                )
                db.add(new_apt)
            pulled += 1

        except Exception as exc:
            logger.warning("[GCalSync] Pull error for event %s: %s", event.get("id"), exc)
            errors += 1

    await db.flush()

    # ── DETECT DELETIONS: GCal events that disappeared ───────────────────
    # When an event is fully deleted in Google Calendar (not just "cancelled"),
    # it vanishes from the events list. Find DB appointments with gcal- UIDs
    # that are NOT in the returned events → mark them CANCELLED.
    gcal_uids_in_calendar = {f"gcal-{e.get('id', '')}" for e in gcal_events if e.get("id")}

    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == current_user.id,
            Appointment.scheduled_at >= now,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.cal_booking_uid.ilike("gcal-%"),
        )
    )
    gcal_db_appointments = result.scalars().all()

    for apt in gcal_db_appointments:
        if apt.cal_booking_uid not in gcal_uids_in_calendar:
            apt.status = AppointmentStatus.CANCELLED
            pulled += 1
            logger.info("[GCalSync] Detected deletion from GCal: %s (%s)",
                        apt.cal_booking_uid, apt.patient_name)

    await db.flush()

    # ── PUSH: DB → Google Calendar ────────────────────────────────────────
    # Find future CONFIRMED appointments that don't have a gcal- uid
    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == current_user.id,
            Appointment.scheduled_at >= now,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )
    all_future = result.scalars().all()

    for apt in all_future:
        # Skip if already synced to GCal (has gcal- prefix)
        if apt.cal_booking_uid and apt.cal_booking_uid.startswith("gcal-"):
            continue
        # Skip demo bookings
        if apt.cal_booking_uid and apt.cal_booking_uid.startswith("demo-"):
            pass  # Still push these — they were created in demo mode but GCal is now connected

        try:
            patient_info = {
                "name": apt.patient_name,
                "email": apt.patient_email or "",
                "phone": apt.patient_phone or "",
                "dob": apt.date_of_birth or "",
            }
            booking = await gcal.book_appointment(
                refresh_token=refresh_token,
                patient_info=patient_info,
                start_time=apt.scheduled_at.isoformat(),
                duration_minutes=apt.duration_minutes,
                timezone=tenant_tz,
            )
            if booking:
                apt.cal_booking_uid = booking.get("uid", apt.cal_booking_uid)
                pushed += 1
                logger.info("[GCalSync] Pushed appointment %s → GCal %s",
                            apt.id, booking.get("uid"))
        except Exception as exc:
            logger.warning("[GCalSync] Push error for appointment %s: %s", apt.id, exc)
            errors += 1

    await db.flush()

    # ── PUSH CANCELLATIONS: DB (CANCELLED) → Google Calendar ─────────────
    # Find appointments cancelled in DB that still have a gcal- uid (not yet deleted from GCal)
    cancelled_count = 0
    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == current_user.id,
            Appointment.status == AppointmentStatus.CANCELLED,
            Appointment.cal_booking_uid.ilike("gcal-%"),
        )
    )
    cancelled_apts = result.scalars().all()

    # Build a set of GCal event IDs we know are already cancelled in GCal
    gcal_cancelled_ids = set()
    for event in gcal_events:
        if event.get("status") == "cancelled":
            gcal_cancelled_ids.add(f"gcal-{event.get('id', '')}")

    for apt in cancelled_apts:
        if apt.cal_booking_uid in gcal_cancelled_ids:
            continue  # Already cancelled in GCal
        try:
            ok = await gcal.cancel_appointment(
                refresh_token=refresh_token,
                event_id=apt.cal_booking_uid,
            )
            if ok:
                cancelled_count += 1
                logger.info("[GCalSync] Pushed cancellation → GCal: %s (%s)",
                            apt.cal_booking_uid, apt.patient_name)
        except Exception as exc:
            logger.warning("[GCalSync] Cancel push error for %s: %s", apt.cal_booking_uid, exc)
            errors += 1

    await db.flush()

    total = pulled + pushed + cancelled_count
    logger.info("[GCalSync] Sync complete for tenant %s: pulled=%d pushed=%d cancelled=%d errors=%d",
                current_user.slug, pulled, pushed, cancelled_count, errors)

    return {
        "status": "ok",
        "pulled": pulled,
        "pushed": pushed,
        "cancelled": cancelled_count,
        "errors": errors,
        "total": total,
        "message": f"Synced {total} appointments ({pulled} from Google Calendar, {pushed} pushed, {cancelled_count} cancellations synced)"
        + (f", {errors} errors" if errors else ""),
    }


# ── Cal.com live sync ─────────────────────────────────────────────────────────


async def _sync_calcom_bookings(tenant: Tenant) -> int:
    """
    Pull bookings from Cal.com for this tenant and upsert into the local
    Appointment table (matched by cal_booking_uid).

    Returns the number of bookings synced.
    """
    if not tenant.calcom_api_key:
        logger.debug("[CalSync] Skipped — tenant %s has no calcom_api_key", tenant.slug)
        return 0

    # Build a TenantContext to satisfy calendar_service signatures
    ctx = tenant_service._tenant_to_context(tenant)
    bookings = await calendar_service.list_bookings(tenant_ctx=ctx, take=100)

    if not bookings:
        return 0

    synced = 0
    async with async_session() as session:
        for b in bookings:
            try:
                uid = b.get("uid") or b.get("id")
                if not uid:
                    continue
                uid = str(uid)

                # Pull fields from Cal.com booking shape
                start = b.get("start") or b.get("startTime")
                end = b.get("end") or b.get("endTime")
                event_title = (b.get("eventType") or {}).get("title") or b.get("title") or "Appointment"
                status_str = (b.get("status") or "ACCEPTED").upper()

                # Attendee details
                attendees = b.get("attendees") or []
                first_attendee = attendees[0] if attendees else {}
                patient_name = first_attendee.get("name") or b.get("responses", {}).get("name") or "Unknown"
                patient_email = first_attendee.get("email") or b.get("responses", {}).get("email")
                patient_phone = (
                    first_attendee.get("phoneNumber")
                    or b.get("responses", {}).get("smsReminderNumber")
                    or b.get("responses", {}).get("phone")
                    or ""
                )

                if not start:
                    continue
                scheduled_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
                duration = 30
                if end:
                    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    duration = max(int((end_dt - scheduled_at).total_seconds() / 60), 5)

                # Map Cal.com status → local AppointmentStatus
                if status_str in ("CANCELLED", "REJECTED"):
                    local_status = AppointmentStatus.CANCELLED
                elif status_str in ("PENDING", "AWAITING_HOST"):
                    local_status = AppointmentStatus.CONFIRMED
                else:
                    local_status = AppointmentStatus.CONFIRMED

                # Upsert by cal_booking_uid
                existing = (
                    await session.execute(
                        select(Appointment).where(
                            Appointment.cal_booking_uid == uid,
                            Appointment.tenant_id == tenant.id,
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.scheduled_at = scheduled_at
                    existing.duration_minutes = duration
                    existing.status = local_status
                    existing.appointment_type = event_title
                    existing.patient_name = patient_name
                    existing.patient_email = patient_email
                    if patient_phone:
                        existing.patient_phone = patient_phone
                else:
                    new = Appointment(
                        tenant_id=tenant.id,
                        cal_booking_uid=uid,
                        patient_name=patient_name,
                        patient_phone=patient_phone or "",
                        patient_email=patient_email,
                        appointment_type=event_title,
                        scheduled_at=scheduled_at,
                        duration_minutes=duration,
                        status=local_status,
                        booked_via=BookedVia.AI,  # Booked via Cal.com (treated as agent-booked)
                    )
                    session.add(new)
                synced += 1
            except Exception as exc:
                logger.warning("[CalSync] Failed to upsert booking %s: %s", b.get("uid"), exc)

        await session.commit()

    logger.info("[CalSync] Synced %d bookings for tenant %s", synced, tenant.slug)
    return synced
