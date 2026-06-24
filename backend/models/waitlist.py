"""
Waitlist model — tracks callers waiting for a slot to open up.

When the AI agent finds no available slots for a requested date/type, it offers
to add the caller to the waitlist. When a cancellation creates an opening, the
system auto-notifies the top waitlisted caller via SMS. First to confirm gets
the slot.

Tenant scope is derived via caller_id → callers.tenant_id (no stored tenant_id
column). All SQL filtering by tenant uses an explicit JOIN to callers.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, case, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from backend.database import Base


class WaitlistStatus(str, enum.Enum):
    WAITING = "WAITING"       # Actively waiting for a slot
    NOTIFIED = "NOTIFIED"     # SMS sent — waiting for caller reply
    BOOKED = "BOOKED"         # Caller confirmed and got the slot
    EXPIRED = "EXPIRED"       # Preferred date passed without a match
    CANCELLED = "CANCELLED"   # Caller or system removed from waitlist


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    caller_id = Column(UUID(as_uuid=True), ForeignKey("callers.id"), nullable=False, index=True)

    # Caller info
    student_name = Column(String(255), nullable=False)
    student_phone = Column(String(20), nullable=False, index=True)
    student_email = Column(String(255), nullable=True)

    # What they're waiting for
    appointment_type = Column(String(100), nullable=False)
    preferred_date = Column(String(10), nullable=False)             # YYYY-MM-DD
    preferred_time_start = Column(String(5), nullable=True)         # HH:MM (optional window)
    preferred_time_end = Column(String(5), nullable=True)           # HH:MM (optional window)

    # Optional provider preference
    provider_id = Column(UUID(as_uuid=True), ForeignKey("faculty.id"), nullable=True)

    # Priority: lower = higher priority (1 = highest). Default uses insertion order.
    priority = Column(Integer, nullable=False, default=100)

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

    # Lifecycle
    status = Column(Enum(WaitlistStatus), nullable=False, default=WaitlistStatus.WAITING)
    notified_at = Column(DateTime(timezone=True), nullable=True)    # When we texted them
    booked_at = Column(DateTime(timezone=True), nullable=True)      # When they confirmed
    expires_at = Column(DateTime(timezone=True), nullable=True)     # Auto-expire after preferred date

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Derived from caller — no stored column (use explicit JOIN for SQL filtering)
    @property
    def tenant_id(self):
        return self.caller.tenant_id if self.caller else None

    # Relationships
    caller = relationship("Caller", lazy="selectin", foreign_keys=[caller_id])
    provider = relationship("Provider", lazy="selectin")

    def __repr__(self) -> str:
        return f"<WaitlistEntry {self.student_name} waiting for {self.appointment_type} on {self.preferred_date}>"
