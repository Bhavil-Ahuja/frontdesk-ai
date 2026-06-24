"""
Appointment database model — tracks every booking made via AI or manually.

Tenant scope is derived via caller_id → callers.tenant_id (no stored tenant_id
column). All SQL filtering by tenant uses an explicit JOIN to callers.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, case, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from backend.database import Base


class AppointmentStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"      # Attended — visit completed
    NO_SHOW = "NO_SHOW"          # Caller didn't show up


class BookedVia(str, enum.Enum):
    AI = "AI"
    MANUAL = "MANUAL"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    caller_id = Column(UUID(as_uuid=True), ForeignKey("callers.id"), nullable=False, index=True)
    cal_booking_id = Column(String(255), nullable=True)
    cal_booking_uid = Column(String(255), nullable=True, index=True)
    student_name = Column(String(255), nullable=False)
    student_phone = Column(String(20), nullable=False)
    student_email = Column(String(255), nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    appointment_type = Column(String(100), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=60)
    status = Column(Enum(AppointmentStatus), nullable=False, default=AppointmentStatus.CONFIRMED)
    booked_via = Column(Enum(BookedVia), nullable=False, default=BookedVia.AI)
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("faculty.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @hybrid_property
    def is_test(self) -> bool:
        return self.caller.is_test if self.caller else False

    @is_test.inplace.expression
    @classmethod
    def _is_test_expr(cls):
        from backend.models.caller import Caller
        return case(
            (cls.caller_id.is_(None), False),
            else_=(
                select(Caller.is_test)
                .where(Caller.id == cls.caller_id)
                .correlate(cls)
                .scalar_subquery()
            ),
        )

    # Derived from caller — no stored column (use explicit JOIN for SQL filtering)
    @property
    def tenant_id(self):
        return self.caller.tenant_id if self.caller else None

    # ── Reminder / follow-up tracking ────────────────────────────────────
    reminder_sent_at = Column(DateTime(timezone=True), nullable=True)      # legacy (was 24h-before SMS) — column kept, no longer used
    reminder_2h_sent_at = Column(DateTime(timezone=True), nullable=True)   # 2h-before SMS
    followup_sent_at = Column(DateTime(timezone=True), nullable=True)      # post-visit SMS
    review_requested_at = Column(DateTime(timezone=True), nullable=True)   # Google review request

    # ── Caller confirmation via SMS reply ───────────────────────────────
    confirmed_by_student = Column(
        Boolean,
        # None = not yet replied, True = confirmed, False = declined
        nullable=True,
    )

    # Relationships
    caller = relationship("Caller", lazy="selectin", foreign_keys=[caller_id])
    call = relationship("Call", back_populates="appointments")
    provider = relationship("Provider", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Appointment {self.student_name} @ {self.scheduled_at}>"
