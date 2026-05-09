"""
Patient database model — stores patient contact, insurance, and preference data.
Used for caller recognition (phone-based lookup) and personalised greetings.

Multi-tenant: each patient belongs to one tenant. The same phone number can
exist under different tenants (enforced via UniqueConstraint on tenant_id + phone).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_patient_tenant_phone"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)

    # ── Identity ─────────────────────────────────────────────────────────
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    date_of_birth = Column(String(20), nullable=True)

    # ── Clinical / preference ────────────────────────────────────────────
    insurance_provider = Column(String(255), nullable=True)
    preferred_appointment_type = Column(String(100), nullable=True)  # e.g. "cleaning"
    allergies = Column(Text, nullable=True)                          # free text
    notes = Column(Text, nullable=True)                              # receptionist notes

    # ── State tracking ───────────────────────────────────────────────────
    is_new_patient = Column(Boolean, default=True)
    visit_count = Column(Integer, default=0)                         # total completed visits
    no_show_count = Column(Integer, default=0)                       # missed appointments
    first_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_appointment_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", backref="patients", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Patient {self.name} ({self.phone})>"
