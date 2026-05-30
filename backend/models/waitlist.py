"""
Waitlist model — tracks patients waiting for a slot to open up.

When the AI agent finds no available slots for a requested date/type, it offers
to add the patient to the waitlist. When a cancellation creates an opening, the
system auto-notifies the top waitlisted patient via SMS. First to confirm gets
the slot.

Multi-tenant: every waitlist entry belongs to one tenant via tenant_id FK.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class WaitlistStatus(str, enum.Enum):
    WAITING = "WAITING"       # Actively waiting for a slot
    NOTIFIED = "NOTIFIED"     # SMS sent — waiting for patient reply
    BOOKED = "BOOKED"         # Patient confirmed and got the slot
    EXPIRED = "EXPIRED"       # Preferred date passed without a match
    CANCELLED = "CANCELLED"   # Patient or system removed from waitlist


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    # Patient info
    patient_name = Column(String(255), nullable=False)
    patient_phone = Column(String(20), nullable=False, index=True)
    patient_email = Column(String(255), nullable=True)

    # What they're waiting for
    appointment_type = Column(String(100), nullable=False)
    preferred_date = Column(String(10), nullable=False)             # YYYY-MM-DD
    preferred_time_start = Column(String(5), nullable=True)         # HH:MM (optional window)
    preferred_time_end = Column(String(5), nullable=True)           # HH:MM (optional window)

    # Optional provider preference
    provider_id = Column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True)

    # Priority: lower = higher priority (1 = highest). Default uses insertion order.
    priority = Column(Integer, nullable=False, default=100)

    # Test data flag
    is_test = Column(Boolean, nullable=False, default=False)  # True = created via Test Agent chat

    # Lifecycle
    status = Column(Enum(WaitlistStatus), nullable=False, default=WaitlistStatus.WAITING)
    notified_at = Column(DateTime(timezone=True), nullable=True)    # When we texted them
    booked_at = Column(DateTime(timezone=True), nullable=True)      # When they confirmed
    expires_at = Column(DateTime(timezone=True), nullable=True)     # Auto-expire after preferred date

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", backref="waitlist_entries", lazy="selectin")
    provider = relationship("Provider", lazy="selectin")

    def __repr__(self) -> str:
        return f"<WaitlistEntry {self.patient_name} waiting for {self.appointment_type} on {self.preferred_date}>"
