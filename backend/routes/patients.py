"""
Patient CRM API routes — list patients, get full patient profile with
appointment history, call logs, and SMS threads.

GET    /api/patients              -> list all patients for the tenant
GET    /api/patients/{patient_id} -> full patient profile with history
PUT    /api/patients/{patient_id} -> update patient notes/allergies/etc.
DELETE /api/patients/{patient_id} -> delete patient + related data
POST   /api/patients/bulk-delete  -> delete multiple patients + related data
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.tenant import Tenant
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus
from backend.models.call import Call
from backend.models.sms_message import SMSMessage, SMSDirection
from backend.models.provider import Provider
from backend.models.waitlist import WaitlistEntry
from backend.models.status_history import AppointmentStatusHistory
from backend.services import auth_service
from backend.services.patient_service import _phone_digits_tail, _phone_col_clean
from backend.defaults import slugify_appointment_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["Patients"])


# -- Schemas -------------------------------------------------------------------


class PatientUpdateRequest(BaseModel):
    """Partial update for editable patient fields."""
    name: Optional[str] = None
    email: Optional[str] = None
    date_of_birth: Optional[str] = None
    allergies: Optional[str] = None
    notes: Optional[str] = None
    preferred_appointment_type: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    """Request body for bulk patient deletion."""
    patient_ids: List[str]


# -- Routes --------------------------------------------------------------------


@router.get("")
async def list_patients(
    search: Optional[str] = Query(None, description="Search by name or phone"),
    sort: str = Query("recent", description="Sort: recent, name, visits"),
    include_test: bool = Query(False, description="Include test/demo patient data"),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    List all patients for the authenticated tenant with summary stats.
    Returns: id, name, phone, email, visit_count, is_new_patient,
    last_appointment_at, upcoming_count.
    """
    logger.info("[Patients] Listing patients for tenant=%s search=%s include_test=%s", current_user.slug, search, include_test)
    async with async_session() as session:
        # Base query
        filters = [Patient.tenant_id == current_user.id]

        # Exclude test data by default
        if not include_test:
            filters.append(Patient.is_test == False)  # noqa: E712

        if search:
            search_term = f"%{search.strip()}%"
            filters.append(
                (Patient.name.ilike(search_term)) | (Patient.phone.ilike(search_term))
            )

        stmt = select(Patient).where(and_(*filters))

        # Sorting
        if sort == "name":
            stmt = stmt.order_by(Patient.name.asc())
        elif sort == "visits":
            stmt = stmt.order_by(desc(Patient.visit_count))
        else:  # "recent" — most recently seen first
            stmt = stmt.order_by(desc(Patient.last_appointment_at))

        result = await session.execute(stmt)
        patients = result.scalars().all()

        # For each patient, count upcoming appointments
        patient_list = []
        for p in patients:
            # Count upcoming confirmed appointments (suffix match handles
            # phone format differences like +6352418405 vs +16352418405)
            phone_tail = _phone_digits_tail(p.phone)
            upcoming_count_stmt = select(func.count()).where(
                and_(
                    Appointment.tenant_id == current_user.id,
                    _phone_col_clean(Appointment.patient_phone).endswith(phone_tail),
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    Appointment.scheduled_at > func.now(),
                )
            )
            upcoming_result = await session.execute(upcoming_count_stmt)
            upcoming_count = upcoming_result.scalar() or 0

            patient_list.append({
                "id": str(p.id),
                "name": p.name,
                "phone": p.phone,
                "email": p.email,
                "date_of_birth": p.date_of_birth,
                "is_new_patient": p.is_new_patient,
                "visit_count": p.visit_count or 0,
                "no_show_count": p.no_show_count or 0,
                "last_appointment_at": p.last_appointment_at.isoformat() if p.last_appointment_at else None,
                "first_seen_at": p.first_seen_at.isoformat() if p.first_seen_at else None,
                "upcoming_count": upcoming_count,
                "preferred_appointment_type": p.preferred_appointment_type,
                "is_test": p.is_test or False,
            })

        return patient_list


@router.get("/{patient_id}")
async def get_patient_profile(
    patient_id: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Full patient profile: demographics, all appointments, call logs, SMS threads.
    This is the data backing the CRM patient detail view.
    """
    logger.info("[Patients] Profile request for %s by tenant=%s", patient_id, current_user.slug)
    async with async_session() as session:
        # Get patient
        result = await session.execute(
            select(Patient).where(
                and_(Patient.id == patient_id, Patient.tenant_id == current_user.id)
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        # ── Appointments (all, most recent first) ────────────────────────
        # Use suffix matching to handle phone format differences
        phone_tail = _phone_digits_tail(patient.phone)
        appts_result = await session.execute(
            select(Appointment)
            .where(
                and_(
                    Appointment.tenant_id == current_user.id,
                    _phone_col_clean(Appointment.patient_phone).endswith(phone_tail),
                )
            )
            .order_by(desc(Appointment.scheduled_at))
            .limit(50)
        )
        appointments = appts_result.scalars().all()

        # ── Provider name map ───────────────────────────────────────────
        provider_ids = {a.provider_id for a in appointments if a.provider_id}
        provider_map: dict = {}
        if provider_ids:
            prov_result = await session.execute(
                select(Provider).where(Provider.id.in_(provider_ids))
            )
            for prov in prov_result.scalars().all():
                provider_map[prov.id] = prov.name

        # ── Call logs (matched by caller_number) ─────────────────────────
        # Match on last 10 digits to handle +1 prefix differences
        phone_digits = patient.phone.replace("+", "").replace("-", "").replace(" ", "")
        phone_tail = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        calls_result = await session.execute(
            select(Call)
            .where(
                and_(
                    Call.tenant_id == current_user.id,
                    Call.caller_number.ilike(f"%{phone_tail}"),
                )
            )
            .order_by(desc(Call.started_at))
            .limit(30)
        )
        calls = calls_result.scalars().all()

        # ── SMS messages ─────────────────────────────────────────────────
        sms_result = await session.execute(
            select(SMSMessage)
            .where(
                and_(
                    SMSMessage.tenant_id == current_user.id,
                    SMSMessage.patient_phone.ilike(f"%{phone_tail}"),
                )
            )
            .order_by(desc(SMSMessage.created_at))
            .limit(100)
        )
        sms_messages = sms_result.scalars().all()

        # ── Status history for all appointments ─────────────────────────
        appt_ids = [a.id for a in appointments]
        history_map: dict[str, list] = {str(aid): [] for aid in appt_ids}
        if appt_ids:
            history_result = await session.execute(
                select(AppointmentStatusHistory)
                .where(AppointmentStatusHistory.appointment_id.in_(appt_ids))
                .order_by(AppointmentStatusHistory.created_at.asc())
            )
            for h in history_result.scalars().all():
                history_map.setdefault(str(h.appointment_id), []).append(h)

    # Build slug → display name map from tenant config
    type_display_map: dict[str, str] = {}
    tenant_types = current_user.appointment_types or []
    for at in tenant_types:
        code = slugify_appointment_type(at.get("code", ""))
        name = at.get("name", "")
        if code and name:
            type_display_map[code] = name

    # ── Assemble response ────────────────────────────────────────────────
    return {
        "patient": {
            "id": str(patient.id),
            "name": patient.name,
            "phone": patient.phone,
            "email": patient.email,
            "date_of_birth": patient.date_of_birth,
            "preferred_appointment_type": patient.preferred_appointment_type,
            "allergies": patient.allergies,
            "notes": patient.notes,
            "is_new_patient": patient.is_new_patient,
            "visit_count": patient.visit_count or 0,
            "no_show_count": patient.no_show_count or 0,
            "first_seen_at": patient.first_seen_at.isoformat() if patient.first_seen_at else None,
            "last_appointment_at": patient.last_appointment_at.isoformat() if patient.last_appointment_at else None,
        },
        "appointments": [
            {
                "id": str(a.id),
                "appointment_type": a.appointment_type,
                "appointment_type_display": type_display_map.get(
                    slugify_appointment_type(a.appointment_type or ""),
                    a.appointment_type,
                ),
                "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
                "duration_minutes": a.duration_minutes,
                "status": a.status.value if a.status else None,
                "booked_via": a.booked_via.value if a.booked_via else None,
                "provider_id": str(a.provider_id) if a.provider_id else None,
                "provider_name": provider_map.get(a.provider_id) if a.provider_id else None,
                "confirmed_by_patient": a.confirmed_by_patient,
                "reminder_sent_at": a.reminder_sent_at.isoformat() if a.reminder_sent_at else None,
                "notes": a.notes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "status_history": [
                    {
                        "old_status": h.old_status,
                        "new_status": h.new_status,
                        "changed_by": h.changed_by,
                        "note": h.note,
                        "created_at": h.created_at.isoformat() if h.created_at else None,
                    }
                    for h in history_map.get(str(a.id), [])
                ],
            }
            for a in appointments
        ],
        "calls": [
            {
                "id": str(c.id),
                "vapi_call_id": c.vapi_call_id,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "duration_seconds": c.duration_seconds,
                "outcome": c.outcome.value if c.outcome else None,
                "summary": c.summary,
                "transcript": c.transcript or [],
            }
            for c in calls
        ],
        "sms_messages": [
            {
                "id": str(m.id),
                "direction": m.direction.value,
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in sms_messages
        ],
    }


@router.put("/{patient_id}")
async def update_patient(
    patient_id: str,
    req: PatientUpdateRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Update editable patient fields (notes, allergies, etc.)."""
    logger.info("[Patients] Updating patient %s for tenant=%s", patient_id, current_user.slug)
    async with async_session() as session:
        result = await session.execute(
            select(Patient).where(
                and_(Patient.id == patient_id, Patient.tenant_id == current_user.id)
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        update_data = {k: v for k, v in req.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update.")

        for key, value in update_data.items():
            setattr(patient, key, value)

        await session.commit()
        return {"status": "updated", "patient_id": patient_id, "updated_fields": list(update_data.keys())}


@router.post("/bulk-delete")
async def bulk_delete_patients(
    req: BulkDeleteRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Delete multiple patients and all their related data (appointments,
    waitlist entries, SMS messages). Matches related data by phone number.
    Requires explicit patient_ids list from the doctor.
    """
    if not req.patient_ids:
        raise HTTPException(status_code=400, detail="No patient IDs provided.")
    if len(req.patient_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 patients per bulk delete.")

    logger.warning(
        "[Patients] Bulk delete requested for %d patients by tenant=%s",
        len(req.patient_ids), current_user.slug,
    )

    async with async_session() as session:
        # Look up all requested patients (scoped to tenant)
        result = await session.execute(
            select(Patient).where(
                and_(
                    Patient.tenant_id == current_user.id,
                    Patient.id.in_(req.patient_ids),
                )
            )
        )
        patients = result.scalars().all()

        if not patients:
            raise HTTPException(status_code=404, detail="No matching patients found.")

        # Cascade delete related data by phone number
        totals = {"patients": 0, "appointments": 0, "waitlist_entries": 0, "sms_messages": 0}
        deleted_names = []

        for patient in patients:
            counts = await _cascade_delete_patient(session, patient, current_user.id)
            totals["patients"] += 1
            totals["appointments"] += counts["appointments"]
            totals["waitlist_entries"] += counts["waitlist_entries"]
            totals["sms_messages"] += counts["sms_messages"]
            deleted_names.append(patient.name or patient.phone)

        await session.commit()

    total = sum(totals.values())
    logger.warning(
        "[Patients] Bulk deleted %d patients (%s) + %d appts + %d waitlist + %d sms for tenant=%s",
        totals["patients"], ", ".join(deleted_names),
        totals["appointments"], totals["waitlist_entries"], totals["sms_messages"],
        current_user.slug,
    )
    return {
        "status": "deleted",
        "deleted": totals,
        "total": total,
        "deleted_names": deleted_names,
    }


@router.delete("/test-data")
async def clear_test_data(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Delete all test/demo data (patients, appointments, waitlist entries, SMS)
    for the authenticated tenant. Only removes records where is_test=True.
    """
    logger.info("[Patients] Clearing test data for tenant=%s", current_user.slug)
    async with async_session() as session:
        # Delete in order to respect FK constraints
        sms_count = (await session.execute(
            delete(SMSMessage).where(
                and_(SMSMessage.tenant_id == current_user.id, SMSMessage.is_test == True)  # noqa: E712
            )
        )).rowcount

        waitlist_count = (await session.execute(
            delete(WaitlistEntry).where(
                and_(WaitlistEntry.tenant_id == current_user.id, WaitlistEntry.is_test == True)  # noqa: E712
            )
        )).rowcount

        appt_count = (await session.execute(
            delete(Appointment).where(
                and_(Appointment.tenant_id == current_user.id, Appointment.is_test == True)  # noqa: E712
            )
        )).rowcount

        patient_count = (await session.execute(
            delete(Patient).where(
                and_(Patient.tenant_id == current_user.id, Patient.is_test == True)  # noqa: E712
            )
        )).rowcount

        await session.commit()

    total = patient_count + appt_count + waitlist_count + sms_count
    logger.info(
        "[Patients] Cleared test data: %d patients, %d appointments, %d waitlist, %d sms",
        patient_count, appt_count, waitlist_count, sms_count,
    )
    return {
        "status": "cleared",
        "deleted": {
            "patients": patient_count,
            "appointments": appt_count,
            "waitlist_entries": waitlist_count,
            "sms_messages": sms_count,
        },
        "total": total,
    }


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Delete a single patient and all related data (appointments, waitlist
    entries, SMS messages). Matches related data by phone number.
    """
    logger.warning("[Patients] Delete requested for patient %s by tenant=%s", patient_id, current_user.slug)

    async with async_session() as session:
        result = await session.execute(
            select(Patient).where(
                and_(Patient.id == patient_id, Patient.tenant_id == current_user.id)
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        counts = await _cascade_delete_patient(session, patient, current_user.id)
        patient_name = patient.name or patient.phone
        await session.commit()

    logger.warning(
        "[Patients] Deleted patient '%s' + %d appts + %d waitlist + %d sms for tenant=%s",
        patient_name, counts["appointments"], counts["waitlist_entries"],
        counts["sms_messages"], current_user.slug,
    )
    return {
        "status": "deleted",
        "patient_name": patient_name,
        "deleted": {
            "patients": 1,
            **counts,
        },
        "total": 1 + sum(counts.values()),
    }


# -- Helpers -------------------------------------------------------------------


async def _cascade_delete_patient(
    session: AsyncSession, patient: Patient, tenant_id
) -> dict:
    """
    Delete a patient and all related records (SMS, waitlist, appointments)
    matched by phone number suffix. Returns counts of deleted related records.
    Must be called within an active session — caller is responsible for commit.
    """
    phone_tail = _phone_digits_tail(patient.phone)

    # Delete related SMS messages
    sms_count = (await session.execute(
        delete(SMSMessage).where(
            and_(
                SMSMessage.tenant_id == tenant_id,
                _phone_col_clean(SMSMessage.patient_phone).endswith(phone_tail),
            )
        )
    )).rowcount

    # Delete related waitlist entries
    waitlist_count = (await session.execute(
        delete(WaitlistEntry).where(
            and_(
                WaitlistEntry.tenant_id == tenant_id,
                _phone_col_clean(WaitlistEntry.patient_phone).endswith(phone_tail),
            )
        )
    )).rowcount

    # Delete related appointments
    appt_count = (await session.execute(
        delete(Appointment).where(
            and_(
                Appointment.tenant_id == tenant_id,
                _phone_col_clean(Appointment.patient_phone).endswith(phone_tail),
            )
        )
    )).rowcount

    # Delete the patient record itself
    await session.execute(
        delete(Patient).where(Patient.id == patient.id)
    )

    return {
        "appointments": appt_count,
        "waitlist_entries": waitlist_count,
        "sms_messages": sms_count,
    }
