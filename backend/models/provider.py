"""
Provider model — represents an individual faculty member (teacher, counselor, etc.)
within a tenant's institute.

Each provider can have:
  - Their own Google Calendar (calendar_id) or share the tenant's primary
  - A subset of appointment types they handle (e.g. only consultations)
  - Custom business hours that override the tenant defaults
  - An active/inactive flag for vacation / leave

Multi-tenant: every provider belongs to one tenant via tenant_id FK.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class Provider(Base):
    __tablename__ = "faculty"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    # Identity
    name = Column(String(255), nullable=False)       # "Dr. Sarah Patel"
    title = Column(String(100), nullable=True)        # e.g. "DDS", "MD", "LMT", or any professional credential

    # Which appointment types this provider handles
    # e.g. ["consultation", "follow_up"]  — empty list means ALL types
    appointment_types = Column(JSONB, nullable=False, default=list)

    # Maximum concurrent appointments this provider can handle at the same time.
    # e.g., 2 means they can see 2 callers simultaneously in overlapping slots.
    # Default 1 = single-booking (classic one-at-a-time scheduling).
    max_concurrent = Column(Integer, nullable=False, default=1)

    # Optional Google Calendar ID for this specific provider.
    # If null, uses the tenant's primary calendar.
    calendar_id = Column(String(255), nullable=True)

    # Optional per-provider business hours override.
    # Same format as tenant.business_hours:
    # {"monday": {"open": "08:00", "close": "17:00"}, "friday": null, ...}
    # If null, the tenant's default business hours apply.
    business_hours_override = Column(JSONB, nullable=True)

    # Subject this provider teaches (coaching institutes only).
    # e.g. "Physics", "Chemistry", "Mathematics". One subject per provider.
    subject = Column(String(255), nullable=True)

    # Fixed time windows for demo classes (coaching institutes only).
    # Format: [{"start": "08:00", "end": "10:00"}, {"start": "12:00", "end": "14:00"}]
    # Only providers WITH this field set are offered for demo_class bookings.
    demo_time_slots = Column(JSONB, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", backref="providers", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Provider {self.name} ({self.title or 'N/A'})>"
