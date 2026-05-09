"""
Patient service — caller recognition, history lookup, and upsert.

Multi-tenant: every function accepts a TenantContext (or tenant_id) so that
patient lookups and writes are scoped to the calling tenant. A patient with
the same phone can exist under different tenants.

The core of Tier 1: when a patient calls, we match their phone number against
the patients table (within the tenant), pull their history, and inject it into
the LLM system prompt so the agent can greet them by name and reference past visits.
"""

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)


# ── Phone normalisation ─────────────────────────────────────────────────────
# Vapi sends E.164 (+15125551234), patients might give "512-555-1234".
# We strip to digits-only for comparison, keeping leading country code.

def _normalise_phone(raw: str) -> str:
    """Strip everything except digits and leading +."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw.strip())
    # Ensure we always store with + prefix if it looks like E.164
    if digits and not digits.startswith("+") and len(digits) >= 10:
        digits = "+" + digits
    return digits


# ── Lookup ──────────────────────────────────────────────────────────────────

async def get_patient_by_phone(
    phone: str,
    tenant_id: _uuid.UUID | None = None,
) -> Patient | None:
    """Look up a patient by phone (normalised match), scoped to a tenant."""
    norm = _normalise_phone(phone)
    if not norm:
        return None

    async with async_session() as session:
        # Build base filter
        filters = [Patient.phone == norm]
        if tenant_id:
            filters.append(Patient.tenant_id == tenant_id)

        result = await session.execute(
            select(Patient).where(and_(*filters))
        )
        patient = result.scalar_one_or_none()

        if patient:
            return patient

        # Fallback: try matching last 10 digits (handles +1 prefix differences)
        digits_only = re.sub(r"\D", "", norm)
        if len(digits_only) >= 10:
            tail = digits_only[-10:]
            fallback_filters = [Patient.phone.endswith(tail)]
            if tenant_id:
                fallback_filters.append(Patient.tenant_id == tenant_id)
            result = await session.execute(
                select(Patient).where(and_(*fallback_filters))
            )
            patient = result.scalar_one_or_none()
            return patient

    return None


async def get_patient_history(
    phone: str,
    tenant_id: _uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """
    Full patient context for system prompt injection, scoped to a tenant.
    Returns None if patient not found.

    Shape:
    {
        "patient": {name, phone, dob, insurance, is_new, visit_count, ...},
        "upcoming_appointments": [{type, date, time, booking_uid}, ...],
        "past_appointments": [{type, date, status}, ...],
        "last_visit": {type, date} or None,
        "months_since_last_visit": int or None,
    }
    """
    patient = await get_patient_by_phone(phone, tenant_id=tenant_id)
    if not patient:
        return None

    now = datetime.now(timezone.utc)
    async with async_session() as session:
        # Upcoming appointments (CONFIRMED, in the future) — tenant-scoped
        upcoming_filters = [
            Appointment.patient_phone == patient.phone,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.scheduled_at > now,
        ]
        if tenant_id:
            upcoming_filters.append(Appointment.tenant_id == tenant_id)

        upcoming_result = await session.execute(
            select(Appointment)
            .where(and_(*upcoming_filters))
            .order_by(Appointment.scheduled_at.asc())
            .limit(5)
        )
        upcoming = upcoming_result.scalars().all()

        # Past appointments (any status, in the past) — most recent first
        past_filters = [
            Appointment.patient_phone == patient.phone,
            Appointment.scheduled_at <= now,
        ]
        if tenant_id:
            past_filters.append(Appointment.tenant_id == tenant_id)

        past_result = await session.execute(
            select(Appointment)
            .where(and_(*past_filters))
            .order_by(Appointment.scheduled_at.desc())
            .limit(10)
        )
        past = past_result.scalars().all()

    # Calculate months since last visit
    months_since = None
    last_visit_info = None
    if past:
        last = past[0]
        last_visit_info = {
            "type": last.appointment_type.replace("_", " ").title(),
            "date": last.scheduled_at.strftime("%B %d, %Y"),
        }
        delta = now - last.scheduled_at.replace(tzinfo=timezone.utc) if last.scheduled_at.tzinfo is None else now - last.scheduled_at
        months_since = max(0, int(delta.days / 30))

    return {
        "patient": {
            "name": patient.name,
            "phone": patient.phone,
            "dob": patient.date_of_birth,
            "insurance": patient.insurance_provider,
            "is_new_patient": patient.is_new_patient,
            "visit_count": patient.visit_count or 0,
            "preferred_type": patient.preferred_appointment_type,
            "allergies": patient.allergies,
            "notes": patient.notes,
        },
        "upcoming_appointments": [
            {
                "type": a.appointment_type.replace("_", " ").title(),
                "date": a.scheduled_at.strftime("%A, %B %d, %Y"),
                "time": a.scheduled_at.strftime("%I:%M %p").lstrip("0"),
                "booking_uid": a.cal_booking_uid or "",
            }
            for a in upcoming
        ],
        "past_appointments": [
            {
                "type": a.appointment_type.replace("_", " ").title(),
                "date": a.scheduled_at.strftime("%B %d, %Y"),
                "status": a.status.value if a.status else "UNKNOWN",
            }
            for a in past[:5]  # limit context size
        ],
        "last_visit": last_visit_info,
        "months_since_last_visit": months_since,
    }


# ── Upsert ──────────────────────────────────────────────────────────────────

async def upsert_patient(
    name: str,
    phone: str,
    dob: str = "",
    email: str = "",
    insurance: str = "",
    appointment_type: str = "",
    tenant_id: _uuid.UUID | None = None,
) -> Patient:
    """
    Create a new patient or update an existing one, scoped to a tenant.
    Called after a successful booking so we accumulate patient data over time.
    """
    norm_phone = _normalise_phone(phone)
    if not norm_phone:
        raise ValueError("Cannot upsert patient without a phone number")

    async with async_session() as session:
        filters = [Patient.phone == norm_phone]
        if tenant_id:
            filters.append(Patient.tenant_id == tenant_id)

        result = await session.execute(
            select(Patient).where(and_(*filters))
        )
        patient = result.scalar_one_or_none()

        if patient:
            # Update existing — only overwrite non-empty fields
            if name and name.strip():
                patient.name = name.strip()
            if dob and dob.strip():
                patient.date_of_birth = dob.strip()
            if email and email.strip():
                patient.email = email.strip()
            if insurance and insurance.strip():
                patient.insurance_provider = insurance.strip()
            if appointment_type:
                patient.preferred_appointment_type = appointment_type
            patient.is_new_patient = False
            patient.visit_count = (patient.visit_count or 0) + 1
            patient.last_appointment_at = datetime.now(timezone.utc)
            logger.info("[PatientSvc] Updated returning patient: %s (%s), visit #%d",
                        patient.name, patient.phone, patient.visit_count)
        else:
            # Create new
            patient = Patient(
                tenant_id=tenant_id,
                name=name.strip() or "Unknown",
                phone=norm_phone,
                date_of_birth=dob.strip() if dob else None,
                email=email.strip() if email else None,
                insurance_provider=insurance.strip() if insurance else None,
                preferred_appointment_type=appointment_type or None,
                is_new_patient=True,
                visit_count=1,
                last_appointment_at=datetime.now(timezone.utc),
            )
            session.add(patient)
            logger.info("[PatientSvc] Created new patient: %s (%s) tenant=%s",
                        patient.name, patient.phone, tenant_id)

        await session.commit()
        await session.refresh(patient)
        return patient


async def record_appointment(
    patient_phone: str,
    appointment_type: str,
    scheduled_at: datetime,
    cal_booking_uid: str = "",
    cal_booking_id: str = "",
    patient_name: str = "",
    patient_email: str = "",
    dob: str = "",
    insurance: str = "",
    tenant_id: _uuid.UUID | None = None,
) -> None:
    """
    Record an appointment in the DB after a successful Cal.com booking.
    Also upserts the patient record. Scoped to a tenant.
    """
    norm_phone = _normalise_phone(patient_phone)

    # Upsert patient first
    await upsert_patient(
        name=patient_name,
        phone=norm_phone,
        dob=dob,
        email=patient_email,
        insurance=insurance,
        appointment_type=appointment_type,
        tenant_id=tenant_id,
    )

    # Create appointment record
    async with async_session() as session:
        appointment = Appointment(
            tenant_id=tenant_id,
            cal_booking_uid=cal_booking_uid,
            cal_booking_id=cal_booking_id,
            patient_name=patient_name,
            patient_phone=norm_phone,
            patient_email=patient_email or None,
            date_of_birth=dob,
            insurance_provider=insurance,
            appointment_type=appointment_type,
            scheduled_at=scheduled_at,
            status=AppointmentStatus.CONFIRMED,
        )
        session.add(appointment)
        await session.commit()
        logger.info("[PatientSvc] Recorded appointment: %s @ %s (uid=%s, tenant=%s)",
                    patient_name, scheduled_at, cal_booking_uid, tenant_id)
