"""
Patient CRM API routes — list patients, get full patient profile with
appointment history, call logs, and SMS threads.

GET  /api/patients              -> list all patients for the tenant
GET  /api/patients/{patient_id} -> full patient profile with history
PUT  /api/patients/{patient_id} -> update patient notes/allergies/etc.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.tenant import Tenant
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus
from backend.models.call import Call
from backend.models.sms_message import SMSMessage, SMSDirection
from backend.services import auth_service

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


# -- Routes --------------------------------------------------------------------


@router.get("")
async def list_patients(
    search: Optional[str] = Query(None, description="Search by name or phone"),
    sort: str = Query("recent", description="Sort: recent, name, visits"),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    List all patients for the authenticated tenant with summary stats.
    Returns: id, name, phone, email, visit_count, is_new_patient,
    last_appointment_at, upcoming_count.
    """
    logger.info("[Patients] Listing patients for tenant=%s search=%s", current_user.slug, search)
    async with async_session() as session:
        # Base query
        filters = [Patient.tenant_id == current_user.id]

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
            # Count upcoming confirmed appointments
            upcoming_count_stmt = select(func.count()).where(
                and_(
                    Appointment.tenant_id == current_user.id,
                    Appointment.patient_phone == p.phone,
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
        appts_result = await session.execute(
            select(Appointment)
            .where(
                and_(
                    Appointment.tenant_id == current_user.id,
                    Appointment.patient_phone == patient.phone,
                )
            )
            .order_by(desc(Appointment.scheduled_at))
            .limit(50)
        )
        appointments = appts_result.scalars().all()

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
                "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
                "duration_minutes": a.duration_minutes,
                "status": a.status.value if a.status else None,
                "booked_via": a.booked_via.value if a.booked_via else None,
                "provider_id": str(a.provider_id) if a.provider_id else None,
                "confirmed_by_patient": a.confirmed_by_patient,
                "reminder_sent_at": a.reminder_sent_at.isoformat() if a.reminder_sent_at else None,
                "notes": a.notes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
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
