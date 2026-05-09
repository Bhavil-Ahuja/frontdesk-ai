"""
SMS message model — tracks all inbound and outbound SMS for two-way conversations.

Inbound: patient texts the clinic's Twilio number → AI agent responds
Outbound: reminders, confirmations, waitlist notifications, review requests

Multi-tenant: resolved by matching the Twilio To/From number to a tenant's
twilio_phone_number.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class SMSDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class SMSMessage(Base):
    __tablename__ = "sms_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    direction = Column(Enum(SMSDirection), nullable=False)
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)

    # Twilio message SID for delivery tracking
    twilio_sid = Column(String(50), nullable=True)

    # For threading: group messages by patient phone number
    patient_phone = Column(String(20), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", backref="sms_messages", lazy="selectin")

    def __repr__(self) -> str:
        return f"<SMSMessage {self.direction.value} {self.from_number} → {self.to_number}>"
