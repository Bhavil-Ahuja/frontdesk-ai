"""
Appointment database model — tracks every booking made via AI or manually.

Multi-tenant: every appointment belongs to one tenant via tenant_id FK.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class AppointmentStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"      # Attended — visit completed
    NO_SHOW = "NO_SHOW"          # Patient didn't show up


class BookedVia(str, enum.Enum):
    AI = "AI"
    MANUAL = "MANUAL"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    cal_booking_id = Column(String(255), nullable=True)
    cal_booking_uid = Column(String(255), nullable=True, index=True)
    patient_name = Column(String(255), nullable=False)
    patient_phone = Column(String(20), nullable=False)
    patient_email = Column(String(255), nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    appointment_type = Column(String(100), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=60)
    status = Column(Enum(AppointmentStatus), nullable=False, default=AppointmentStatus.CONFIRMED)
    booked_via = Column(Enum(BookedVia), nullable=False, default=BookedVia.AI)
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # ── Reminder / follow-up tracking ────────────────────────────────────
    reminder_sent_at = Column(DateTime(timezone=True), nullable=True)      # legacy (was 24h-before SMS) — column kept, no longer used
    reminder_2h_sent_at = Column(DateTime(timezone=True), nullable=True)   # 2h-before SMS
    followup_sent_at = Column(DateTime(timezone=True), nullable=True)      # post-visit SMS
    review_requested_at = Column(DateTime(timezone=True), nullable=True)   # Google review request

    # ── Patient confirmation via SMS reply ───────────────────────────────
    confirmed_by_patient = Column(
        Boolean,
        # None = not yet replied, True = confirmed, False = declined
        nullable=True,
    )

    # Relationships
    tenant = relationship("Tenant", backref="appointments", lazy="selectin")
    call = relationship("Call", back_populates="appointments")
    provider = relationship("Provider", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Appointment {self.patient_name} @ {self.scheduled_at}>"
