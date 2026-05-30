"""
Appointment CRUD API routes.

GET   /api/appointments              → list with filters
PATCH /api/appointments/{id}         → update status / notes (post-visit management)
POST  /api/appointments/{id}/cancel  → manual cancellation
POST  /api/appointments/sync-gcal    → bidirectional Google Calendar sync
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
from backend.defaults import DEFAULT_APPOINTMENT_DURATION_MINUTES, DEFAULT_TIMEZONE, slugify_appointment_type
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia
from backend.models.provider import Provider
from backend.models.status_history import AppointmentStatusHistory
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
    appointment_type_display: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int
    status: str
    booked_via: str
    notes: Optional[str]
    created_at: Optional[datetime]
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    is_test: bool = False

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    appointment_type: Optional[str] = None,
    provider_id: Optional[str] = Query(None, description="Filter by provider UUID"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant UUID (admin-only)"),
    include_test: bool = Query(False, description="Include test/demo appointment data"),
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """List all appointments with optional filters. Auto-scoped to current tenant."""
    logger.info("Listing appointments for user=%s admin=%s status=%s type=%s include_test=%s",
                current_user.owner_email, current_user.is_admin, status, appointment_type, include_test)

    query = select(Appointment)

    # Exclude test data by default
    if not include_test:
        query = query.where(Appointment.is_test == False)  # noqa: E712

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
    if provider_id:
        try:
            query = query.where(Appointment.provider_id == uuid.UUID(provider_id))
        except ValueError:
            pass

    query = query.order_by(desc(Appointment.scheduled_at))
    result = await db.execute(query)
    appointments = result.scalars().all()

    # Batch-fetch provider names for appointments that have provider_id
    provider_ids = {a.provider_id for a in appointments if a.provider_id}
    provider_map = {}
    if provider_ids:
        prov_result = await db.execute(
            select(Provider).where(Provider.id.in_(provider_ids))
        )
        for p in prov_result.scalars().all():
            provider_map[p.id] = p.name

    # Build slug → display name map from tenant's appointment_types config
    type_display_map: dict[str, str] = {}
    tenant_types = current_user.appointment_types or []
    for at in tenant_types:
        code = slugify_appointment_type(at.get("code", ""))
        name = at.get("name", "")
        if code and name:
            type_display_map[code] = name

    return [
        AppointmentOut(
            id=str(a.id),
            cal_booking_uid=a.cal_booking_uid,
            patient_name=a.patient_name,
            patient_phone=a.patient_phone,
            patient_email=a.patient_email,
            date_of_birth=a.date_of_birth,
            appointment_type=a.appointment_type,
            appointment_type_display=type_display_map.get(
                slugify_appointment_type(a.appointment_type or ""),
                a.appointment_type,
            ),
            scheduled_at=a.scheduled_at,
            duration_minutes=a.duration_minutes,
            status=a.status.value,
            booked_via=a.booked_via.value,
            notes=a.notes,
            created_at=a.created_at,
            provider_id=str(a.provider_id) if a.provider_id else None,
            provider_name=provider_map.get(a.provider_id) if a.provider_id else None,
            is_test=a.is_test or False,
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

    old_status = apt.status
    apt.status = AppointmentStatus.CANCELLED

    # Record in audit trail
    history_entry = AppointmentStatusHistory(
        appointment_id=apt.id,
        old_status=old_status.value,
        new_status=AppointmentStatus.CANCELLED.value,
        changed_by=current_user.owner_email or "dashboard",
        note="Manually cancelled from dashboard",
    )
    db.add(history_entry)
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


# ── Update appointment status / notes (post-visit management) ────────────────


class AppointmentUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


_ALLOWED_STATUS_TRANSITIONS = {
    # From CONFIRMED: can mark attended (COMPLETED), no-show, cancel, reschedule
    "CONFIRMED": {"COMPLETED", "NO_SHOW", "CANCELLED", "RESCHEDULED"},
    # From NO_SHOW: can correct to attended
    "NO_SHOW": {"COMPLETED"},
    # From COMPLETED: can correct to no-show
    "COMPLETED": {"NO_SHOW"},
    # CANCELLED is terminal
    "CANCELLED": set(),
    # RESCHEDULED transitions back to CONFIRMED (handled by AI agent), or can be cancelled
    "RESCHEDULED": {"CONFIRMED", "CANCELLED"},
}


@router.patch("/{appointment_id}")
async def update_appointment(
    appointment_id: str,
    body: AppointmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Update an appointment's status and/or notes.
    Used by clinic owners to mark past appointments as attended / no-show
    and to add visit notes that the AI will reference on future calls.
    """
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

    updated = []

    # ── Status transition ────────────────────────────────────────────────
    if body.status is not None:
        new_status_str = body.status.upper().strip()
        try:
            new_status = AppointmentStatus(new_status_str)
        except ValueError:
            valid = ", ".join(s.value for s in AppointmentStatus)
            raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {valid}")

        current_status = apt.status.value if apt.status else "CONFIRMED"
        allowed = _ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
        if new_status_str not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from {current_status} to {new_status_str}. Allowed: {allowed or 'none'}",
            )

        old_status = apt.status
        apt.status = new_status
        updated.append(f"status: {old_status.value} → {new_status.value}")

        # ── Record in audit trail ────────────────────────────────────
        history_entry = AppointmentStatusHistory(
            appointment_id=apt.id,
            old_status=old_status.value,
            new_status=new_status.value,
            changed_by=current_user.owner_email or "dashboard",
        )
        db.add(history_entry)

        # Side effects: update patient record based on outcome
        try:
            from backend.models.patient import Patient
            patient_result = await db.execute(
                select(Patient).where(
                    Patient.phone == apt.patient_phone,
                    Patient.tenant_id == apt.tenant_id,
                )
            )
            patient = patient_result.scalar_one_or_none()
            if patient:
                if new_status == AppointmentStatus.NO_SHOW:
                    patient.no_show_count = (patient.no_show_count or 0) + 1
                    # If correcting from COMPLETED back to NO_SHOW, undo the visit_count
                    if old_status == AppointmentStatus.COMPLETED:
                        patient.visit_count = max(0, (patient.visit_count or 1) - 1)
                    logger.info("Patient %s no-show count → %d", patient.name, patient.no_show_count)
                elif new_status == AppointmentStatus.COMPLETED:
                    patient.visit_count = (patient.visit_count or 0) + 1
                    patient.last_appointment_at = apt.scheduled_at
                    patient.is_new_patient = False
                    # If correcting from NO_SHOW back to COMPLETED, undo the no-show count
                    if old_status == AppointmentStatus.NO_SHOW:
                        patient.no_show_count = max(0, (patient.no_show_count or 1) - 1)
                    logger.info("Patient %s visit count → %d", patient.name, patient.visit_count)
        except Exception as exc:
            logger.warning("Patient record update on status change failed: %s", exc)

        # ── Outbound SMS for status change (no-show / completed) ────────
        try:
            tenant_ctx_sms = None
            if apt.tenant_id:
                tenant_ctx_sms = await tenant_service.resolve_by_id(apt.tenant_id)
            if apt.patient_phone:
                if new_status == AppointmentStatus.NO_SHOW and old_status != AppointmentStatus.NO_SHOW:
                    sms_service.send_no_show(
                        patient_name=apt.patient_name,
                        phone=apt.patient_phone,
                        appointment_type=apt.appointment_type,
                        scheduled_at=apt.scheduled_at,
                        tenant_ctx=tenant_ctx_sms,
                    )
                elif new_status == AppointmentStatus.COMPLETED and old_status != AppointmentStatus.COMPLETED:
                    sms_service.send_followup(
                        patient_name=apt.patient_name,
                        phone=apt.patient_phone,
                        tenant_ctx=tenant_ctx_sms,
                    )
        except Exception as exc:
            logger.warning("Outbound SMS on status change failed (non-fatal): %s", exc)

    # ── Notes update ─────────────────────────────────────────────────────
    if body.notes is not None:
        apt.notes = body.notes.strip() if body.notes.strip() else None
        updated.append("notes")

    if not updated:
        raise HTTPException(status_code=400, detail="Nothing to update. Provide status and/or notes.")

    await db.flush()
    logger.info("Appointment %s updated: %s", appointment_id, ", ".join(updated))
    return {
        "status": "updated",
        "id": appointment_id,
        "changes": updated,
        "current_status": apt.status.value,
        "notes": apt.notes,
    }


# ── Appointment status history ────────────────────────────────────────────────


@router.get("/{appointment_id}/history")
async def get_appointment_history(
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Return the full status change history for an appointment."""
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

    history_result = await db.execute(
        select(AppointmentStatusHistory)
        .where(AppointmentStatusHistory.appointment_id == uid)
        .order_by(AppointmentStatusHistory.created_at.asc())
    )
    entries = history_result.scalars().all()

    # Backfill: older appointments created before the status_history feature
    # won't have any entries. Create a synthetic initial entry so the timeline
    # isn't empty. This is persisted so it only happens once per appointment.
    if not entries and apt.created_at:
        booked_via_label = apt.booked_via.value.lower().replace("_", " ") if apt.booked_via else "unknown"
        backfill = AppointmentStatusHistory(
            appointment_id=apt.id,
            old_status=None,
            new_status=AppointmentStatus.CONFIRMED.value,
            changed_by=booked_via_label,
            note=f"Booked via {booked_via_label}",
            created_at=apt.created_at,
        )
        db.add(backfill)
        await db.flush()
        entries = [backfill]

    return [
        {
            "id": str(e.id),
            "old_status": e.old_status,
            "new_status": e.new_status,
            "changed_by": e.changed_by,
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


# ── Google Calendar bidirectional sync ────────────────────────────────────────


@router.post("/sync-gcal")
async def sync_google_calendar(
    db: AsyncSession = Depends(get_db),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Bidirectional sync between the local Appointment table and Google Calendar.
    The DB is the source of truth — conflicts are resolved in DB's favour.

    1. Pull: Fetch GCal events → upsert into DB (skips appointments cancelled in DB)
    2. Re-push: Confirmed DB appointments whose GCal event disappeared → clear UID for re-push
    3. Push: DB appointments without a gcal-* UID → create in Google Calendar
    4. Push cancellations: CANCELLED DB appointments with a gcal-* UID → delete from GCal

    Returns sync stats: { pulled, pushed, cancelled, errors, total }.
    """
    if not current_user.google_calendar_connected or not current_user.google_calendar_refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected. Please connect it in Settings first.",
        )

    refresh_token = current_user.google_calendar_refresh_token
    tenant_tz = current_user.timezone or DEFAULT_TIMEZONE
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

            # Cancelled events from GCal may lack start/end — handle them specially.
            # DB is authoritative: if DB says CONFIRMED but GCal says cancelled,
            # we clear the gcal UID so the PUSH step re-creates it in GCal.
            if gcal_status == "cancelled":
                existing = (
                    await db.execute(
                        select(Appointment).where(
                            Appointment.cal_booking_uid == gcal_uid,
                            Appointment.tenant_id == current_user.id,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    if existing.status == AppointmentStatus.CANCELLED:
                        # Both sides agree — nothing to do
                        logger.debug("[GCalSync] Already cancelled in both DB and GCal: %s", gcal_uid)
                    else:
                        # DB says confirmed but GCal says cancelled → DB wins.
                        # Clear the gcal UID so the PUSH step re-creates it.
                        logger.info(
                            "[GCalSync] GCal event cancelled but DB is CONFIRMED for %s (%s) — "
                            "clearing gcal UID so it will be re-pushed",
                            gcal_uid, existing.patient_name,
                        )
                        existing.cal_booking_uid = None
                continue

            # Skip all-day events (no dateTime means all-day)
            start_obj = event.get("start", {})
            end_obj = event.get("end", {})
            start_str = start_obj.get("dateTime")
            end_str = end_obj.get("dateTime")
            if not start_str:
                continue

            scheduled_at = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            # Derive default duration from tenant's appointment config (source of truth)
            _tenant_appt_types = getattr(current_user, "appointment_types", None) or []
            duration = (
                _tenant_appt_types[0].get("duration_minutes", DEFAULT_APPOINTMENT_DURATION_MINUTES)
                if _tenant_appt_types
                else DEFAULT_APPOINTMENT_DURATION_MINUTES
            )
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
                # DB is source of truth: if the appointment is cancelled in
                # DB, do NOT resurrect it just because GCal still shows it as
                # confirmed. The PUSH CANCELLATIONS step will remove it from
                # GCal instead.
                if existing.status == AppointmentStatus.CANCELLED:
                    logger.info(
                        "[GCalSync] Skipping GCal update for %s — cancelled in DB (DB is authoritative)",
                        gcal_uid,
                    )
                    continue

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

    # ── RE-PUSH: DB appointments with gcal- UIDs missing from GCal ───────
    # DB is source of truth. If a confirmed appointment has a gcal- UID but
    # the event no longer exists in Google Calendar (someone deleted it
    # directly in GCal), we re-create it in GCal rather than cancelling
    # in DB. We clear the old gcal- UID so the PUSH step below picks it up.
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
            logger.info(
                "[GCalSync] GCal event missing for confirmed DB appointment %s (%s) — "
                "clearing gcal UID so it will be re-pushed",
                apt.cal_booking_uid, apt.patient_name,
            )
            apt.cal_booking_uid = None  # PUSH step will re-create in GCal

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
