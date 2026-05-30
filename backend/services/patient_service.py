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
from zoneinfo import ZoneInfo
from datetime import timedelta

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.defaults import slugify_appointment_type
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)


# ── Phone normalisation ─────────────────────────────────────────────────────
# Uses Google's libphonenumber (via `phonenumbers` package) when available
# for robust E.164 normalisation across all countries. Falls back to a
# regex-based heuristic when the library isn't installed.

try:
    import phonenumbers as _pn  # type: ignore[import-untyped]
    _HAS_PHONENUMBERS = True
except ImportError:
    _pn = None  # type: ignore[assignment]
    _HAS_PHONENUMBERS = False

# Map common timezone prefixes → ISO 3166 region codes for phonenumbers.
# Used as the default_region when parsing ambiguous numbers (e.g. "6352418405"
# with no country code).  Only the most common healthcare markets are listed;
# phonenumbers handles the rest once a valid E.164 is stored.
_TZ_TO_REGION: dict[str, str] = {
    "America/": "US",
    "US/": "US",
    "Canada/": "CA",
    "Asia/Kolkata": "IN",
    "Asia/Calcutta": "IN",
    "Asia/Mumbai": "IN",
    "Europe/London": "GB",
    "Europe/": "GB",
    "Australia/": "AU",
    "Asia/Singapore": "SG",
    "Asia/Shanghai": "CN",
    "Asia/Tokyo": "JP",
}


def _region_from_timezone(tz_name: str | None) -> str:
    """Derive a best-guess ISO region from a timezone string."""
    if not tz_name:
        return "US"
    for prefix, region in _TZ_TO_REGION.items():
        if tz_name.startswith(prefix):
            return region
    return "US"  # safe default — most users are US-based


def _normalise_phone(raw: str, default_region: str = "US") -> str:
    """Normalise a phone string to E.164 format.

    Uses libphonenumber when available for correct international handling.
    Falls back to a regex heuristic (strip non-digits, prepend +).

    Args:
        raw: Any phone input — "512-555-1234", "+16352418405", "6352418405" etc.
        default_region: ISO 3166 region code for parsing numbers without a
                        country code (e.g. "US", "IN", "GB"). Default "US".
    """
    if not raw:
        return ""

    # ── Try libphonenumber first ──────────────────────────────────────
    if _HAS_PHONENUMBERS:
        try:
            parsed = _pn.parse(raw.strip(), default_region)
            if _pn.is_valid_number(parsed):
                return _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
        except _pn.NumberParseException:
            pass
        # If invalid / unparseable, fall through to regex approach

    # ── Regex fallback ────────────────────────────────────────────────
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits and not digits.startswith("+") and len(digits) >= 10:
        digits = "+" + digits
    return digits


def _phone_digits_tail(phone: str) -> str:
    """Extract the **national number** portion of a phone string.

    Uses libphonenumber when available — this gives the exact national number
    (e.g. "+61412345678" → "412345678" for Australia, "+16352418405" →
    "6352418405" for the US).

    Falls back to last-10 digits when the library isn't installed, which is
    correct for US/Canada/India/UK (the most common markets).

    The national number is always a suffix of the full E.164 digit string,
    so ``Appointment.patient_phone.endswith(tail)`` works in SQL.
    """
    if not phone:
        return ""

    if _HAS_PHONENUMBERS:
        try:
            parsed = _pn.parse(phone.strip(), None)
            if _pn.is_valid_number(parsed):
                return str(parsed.national_number)
        except _pn.NumberParseException:
            pass

    # Fallback: last 10 digits (covers US / Canada / India / UK)
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _phone_col_clean(col):
    """Wrap a SQLAlchemy phone column with regexp_replace to strip non-digits.

    Returns a SQL expression equivalent to:
        regexp_replace(col, '[^0-9]', '', 'g')

    Use this instead of raw ``col.endswith(tail)`` so that legacy rows
    containing dashes / spaces / parentheses still match correctly.

    Example usage::

        _phone_col_clean(Appointment.patient_phone).endswith(phone_tail)
    """
    return func.regexp_replace(col, '[^0-9]', '', 'g')


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

        # Fallback: try matching national-number suffix (handles +1 prefix
        # differences and any residual non-digit chars in stored phones).
        tail = _phone_digits_tail(norm)
        if tail:
            fallback_filters = [_phone_col_clean(Patient.phone).endswith(tail)]
            if tenant_id:
                fallback_filters.append(Patient.tenant_id == tenant_id)
            result = await session.execute(
                select(Patient).where(and_(*fallback_filters))
            )
            patient = result.scalar_one_or_none()
            return patient

    return None


async def get_patient_by_name(
    name: str,
    tenant_id: _uuid.UUID | None = None,
) -> list[Patient]:
    """Look up patients by name (case-insensitive), scoped to a tenant.

    Returns ALL matches (up to 10) so callers can disambiguate when
    multiple patients share the same name.
    """
    if not name or not name.strip():
        return []

    async with async_session() as session:
        filters = [Patient.name.ilike(f"%{name.strip()}%")]
        if tenant_id:
            filters.append(Patient.tenant_id == tenant_id)

        result = await session.execute(
            select(Patient).where(and_(*filters)).limit(10)
        )
        return list(result.scalars().all())


async def get_patient_history(
    phone: str,
    tenant_id: _uuid.UUID | None = None,
    tz_name: str | None = None,
) -> dict[str, Any] | None:
    """
    Full patient context for system prompt injection, scoped to a tenant.
    Returns None if patient not found.

    Args:
        phone: Patient phone number
        tenant_id: Scope to this tenant's records
        tz_name: Timezone name (e.g. "Europe/London") to display times in.
                 If None, times are shown in UTC.

    Shape:
    {
        "patient": {name, phone, dob, is_new, visit_count, ...},
        "upcoming_appointments": [{type, date, time, booking_uid}, ...],
        "past_appointments": [{type, date, status}, ...],
        "last_visit": {type, date} or None,
        "months_since_last_visit": int or None,
    }
    """
    patient = await get_patient_by_phone(phone, tenant_id=tenant_id)
    if not patient:
        return None

    # Resolve display timezone (for formatting appointment times)
    display_tz: ZoneInfo | None = None
    if tz_name:
        try:
            display_tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning("[PatientSvc] Invalid timezone %s — falling back to UTC", tz_name)

    def _to_local(dt: datetime) -> datetime:
        """Convert a datetime to the display timezone (or return as-is if no tz)."""
        if display_tz is None:
            return dt
        # Ensure UTC-aware before converting
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(display_tz)

    def _relative_date_label(dt: datetime) -> str:
        """Get a relative label like 'TODAY', 'TOMORROW', 'in 3 days' for a datetime."""
        local_dt = _to_local(dt)
        now_local = datetime.now(display_tz) if display_tz else datetime.now(timezone.utc)

        # Compare dates only (ignore time)
        appt_date = local_dt.date()
        today_date = now_local.date()

        delta_days = (appt_date - today_date).days

        if delta_days == 0:
            return "TODAY"
        elif delta_days == 1:
            return "TOMORROW"
        elif delta_days == -1:
            return "YESTERDAY"
        elif delta_days > 1 and delta_days <= 7:
            return f"in {delta_days} days"
        elif delta_days < -1:
            return f"{abs(delta_days)} days ago"
        else:
            return ""

    now = datetime.now(timezone.utc)

    # Use last-10-digit suffix matching so "+6352418405" and "+16352418405"
    # both resolve to the same appointments.  This mirrors the fallback
    # logic already used in get_patient_by_phone().
    phone_tail = _phone_digits_tail(patient.phone)

    async with async_session() as session:
        # Upcoming appointments (CONFIRMED, in the future) — tenant-scoped
        # Use _phone_col_clean to strip dashes/spaces from stored phones
        # before suffix matching, so "635-241-8405" matches tail "6352418405".
        upcoming_filters = [
            _phone_col_clean(Appointment.patient_phone).endswith(phone_tail),
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
            _phone_col_clean(Appointment.patient_phone).endswith(phone_tail),
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
        last_local = _to_local(last.scheduled_at)
        last_visit_info = {
            "type": last.appointment_type.replace("_", " ").title(),
            "date": last_local.strftime("%B %d, %Y"),
        }
        delta = now - last.scheduled_at.replace(tzinfo=timezone.utc) if last.scheduled_at.tzinfo is None else now - last.scheduled_at
        months_since = max(0, int(delta.days / 30))

    return {
        "patient": {
            "name": patient.name,
            "phone": patient.phone,
            "dob": patient.date_of_birth,
            "is_new_patient": patient.is_new_patient,
            "visit_count": patient.visit_count or 0,
            "no_show_count": patient.no_show_count or 0,
            "preferred_type": patient.preferred_appointment_type,
            "allergies": patient.allergies,
            "notes": patient.notes,
        },
        "upcoming_appointments": [
            {
                "type": a.appointment_type.replace("_", " ").title(),
                "date": _to_local(a.scheduled_at).strftime("%A, %B %d, %Y"),
                "relative": _relative_date_label(a.scheduled_at),  # "TODAY", "TOMORROW", etc.
                "time": _to_local(a.scheduled_at).strftime("%I:%M %p").lstrip("0"),
                "booking_uid": a.cal_booking_uid or "",
            }
            for a in upcoming
        ],
        "past_appointments": [
            {
                "type": a.appointment_type.replace("_", " ").title(),
                "date": _to_local(a.scheduled_at).strftime("%B %d, %Y"),
                "status": a.status.value if a.status else "UNKNOWN",
                **({"notes": a.notes} if a.notes else {}),
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
    appointment_type: str = "",
    tenant_id: _uuid.UUID | None = None,
    is_test: bool = False,
) -> Patient:
    """
    Create a new patient or update an existing one, scoped to a tenant.
    Called after a successful booking so we accumulate patient data over time.
    """
    norm_phone = _normalise_phone(phone)
    if not norm_phone:
        raise ValueError("Cannot upsert patient without a phone number")
    # Canonical slug so preferred_appointment_type is always consistent
    if appointment_type:
        appointment_type = slugify_appointment_type(appointment_type)

    async with async_session() as session:
        # Exact match first
        filters = [Patient.phone == norm_phone]
        if tenant_id:
            filters.append(Patient.tenant_id == tenant_id)

        result = await session.execute(
            select(Patient).where(and_(*filters))
        )
        patient = result.scalar_one_or_none()

        # Fallback: match national-number suffix so "+6352418405" and
        # "+16352418405" resolve to the same patient. Uses _phone_col_clean
        # to handle any residual non-digit chars in stored phones.
        if not patient:
            tail = _phone_digits_tail(norm_phone)
            if tail:
                fallback_filters = [_phone_col_clean(Patient.phone).endswith(tail)]
                if tenant_id:
                    fallback_filters.append(Patient.tenant_id == tenant_id)
                result = await session.execute(
                    select(Patient).where(and_(*fallback_filters))
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
            if appointment_type:
                patient.preferred_appointment_type = appointment_type
            # If the incoming phone is longer (has country code), adopt it as
            # the canonical format so future exact matches work directly.
            if len(norm_phone) > len(patient.phone):
                logger.info("[PatientSvc] Upgrading phone %s → %s for %s",
                            patient.phone, norm_phone, patient.name)
                patient.phone = norm_phone
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
                preferred_appointment_type=appointment_type or None,
                is_new_patient=True,
                visit_count=1,
                last_appointment_at=datetime.now(timezone.utc),
                is_test=is_test,
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
    tenant_id: _uuid.UUID | None = None,
    provider_id: _uuid.UUID | None = None,
    duration_minutes: int | None = None,
) -> None:
    """
    Record an appointment in the DB after a successful calendar booking.
    Also upserts the patient record. Scoped to a tenant.

    NOTE: For tenant-scoped native bookings, create_native_booking() already
    persists the appointment with correct duration. This function is only
    needed for legacy/demo paths. Always pass duration_minutes to avoid
    falling back to the SQLAlchemy column default (60).
    """
    norm_phone = _normalise_phone(patient_phone)
    appointment_type = slugify_appointment_type(appointment_type)

    # Upsert patient first
    await upsert_patient(
        name=patient_name,
        phone=norm_phone,
        dob=dob,
        email=patient_email,
        appointment_type=appointment_type,
        tenant_id=tenant_id,
    )

    # Create appointment record
    async with async_session() as session:
        appt_kwargs = dict(
            tenant_id=tenant_id,
            cal_booking_uid=cal_booking_uid,
            cal_booking_id=cal_booking_id,
            patient_name=patient_name,
            patient_phone=norm_phone,
            patient_email=patient_email or None,
            date_of_birth=dob,
            appointment_type=appointment_type,
            scheduled_at=scheduled_at,
            status=AppointmentStatus.CONFIRMED,
            provider_id=provider_id,
        )
        if duration_minutes is not None:
            appt_kwargs["duration_minutes"] = duration_minutes
        appointment = Appointment(**appt_kwargs)
        session.add(appointment)
        await session.commit()
        logger.info("[PatientSvc] Recorded appointment: %s @ %s (uid=%s, tenant=%s, provider=%s)",
                    patient_name, scheduled_at, cal_booking_uid, tenant_id, provider_id)
