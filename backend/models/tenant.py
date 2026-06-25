"""
Tenant model — each row represents one onboarded client (institute, office,
salon, studio, etc.) with all their integration credentials and config.

This is the foundation of multi-tenancy: every call, caller record, and session
is scoped to a tenant via tenant_id foreign keys.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, String, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.database import Base


class TenantStatus(str, enum.Enum):
    """Lifecycle states for tenant onboarding."""
    PENDING = "PENDING"          # submitted, awaiting admin approval
    APPROVED = "APPROVED"        # approved, integrations being configured
    ACTIVE = "ACTIVE"            # live, accepting calls
    SUSPENDED = "SUSPENDED"      # temporarily disabled (billing, abuse, etc.)
    DEACTIVATED = "DEACTIVATED"  # permanently off


class BusinessType(str, enum.Enum):
    """Supported business verticals."""
    COACHING_INSTITUTE = "coaching_institute"
    CUSTOM = "custom"


class PlanTier(str, enum.Enum):
    """Pricing tiers — controls feature access."""
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(100), unique=True, nullable=False, index=True)

    # ── Business identity ────────────────────────────────────────────────
    business_name = Column(String(255), nullable=False)
    business_type = Column(
        Enum(BusinessType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=BusinessType.COACHING_INSTITUTE,
    )
    business_phone = Column(String(20), nullable=True)
    business_address = Column(Text, nullable=True)
    business_website = Column(String(255), nullable=True)
    # Google Maps share-link or embed URL for the institute's location.
    # Collected during registration so admins can iframe-preview the address
    # before approving, and so we have a definitive map source for templates.
    google_maps_url = Column(Text, nullable=True)
    timezone = Column(String(50), nullable=False, default="America/Chicago")

    # ── Owner / admin contact ────────────────────────────────────────────
    owner_name = Column(String(255), nullable=False)
    owner_email = Column(String(255), nullable=False, unique=True, index=True)
    owner_phone = Column(String(20), nullable=True)

    # ── Auth ─────────────────────────────────────────────────────────────
    password_hash = Column(String(255), nullable=True)  # bcrypt hash
    is_admin = Column(Boolean, nullable=False, default=False, index=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ── Plan & status ────────────────────────────────────────────────────
    plan = Column(Enum(PlanTier), nullable=False, default=PlanTier.STARTER)
    status = Column(Enum(TenantStatus), nullable=False, default=TenantStatus.PENDING)
    agent_active = Column(Boolean, nullable=False, default=True)  # owner can toggle; separate from status
    demo_mode = Column(Boolean, nullable=False, default=True)

    # ── Agent personality ────────────────────────────────────────────────
    agent_name = Column(String(100), nullable=False, default="Sarah")
    greeting_message = Column(
        Text, nullable=True,
        default="Thank you for calling. How can I help you today?",
    )
    system_prompt_override = Column(Text, nullable=True)  # full custom prompt (rare)
    voice_config = Column(
        JSONB, nullable=False,
        default=lambda: {"provider": "11labs", "voiceId": "21m00Tcm4TlvDq8ikWAM"},
    )
    end_call_phrases = Column(
        JSONB, nullable=False,
        default=lambda: ["goodbye", "thank you bye", "bye bye"],
    )

    # ── Twilio integration ───────────────────────────────────────────────
    # Under Option A, twilio_account_sid and twilio_auth_token are unused —
    # all tenants share the platform's global Twilio account. Only the
    # per-tenant phone number matters (each tenant gets a unique number).
    twilio_account_sid = Column(String(255), nullable=True)
    twilio_auth_token = Column(String(255), nullable=True)
    twilio_phone_number = Column(String(20), nullable=True)

    # ── Feature flags (per-tenant — effective only when global flag is also True)
    feature_twilio_enabled = Column(Boolean, nullable=False, default=True)

    # ── Usage metering (Option A — platform manages billing) ─────────────
    # Tracks consumption in the current billing period. Reset by a monthly
    # cron or when current_period_start rolls over.
    call_minutes_used = Column(Float, nullable=False, default=0.0)
    sms_sent = Column(Integer, nullable=False, default=0)
    current_period_start = Column(DateTime(timezone=True), nullable=True)

    # ── Google Calendar OAuth ───────────────────────────────────────────
    google_calendar_refresh_token = Column(String(512), nullable=True)
    google_calendar_email = Column(String(255), nullable=True)
    google_calendar_connected = Column(Boolean, nullable=False, default=False)

    # ── Test Agent (chat) ──────────────────────────────────────────────
    # Unified test callers — each entry is {phone, name} to ensure 1:1 mapping.
    # The first entry is the default caller used when the chat starts.
    # Example: [{"phone": "+155501177", "name": "Alex Johnson"}, ...]
    test_callers = Column(JSONB, nullable=False, default=lambda: [])

    # DEPRECATED: Legacy separate arrays — kept for migration, prefer test_callers
    test_caller_phone = Column(String(20), nullable=True)
    test_caller_phones = Column(JSONB, nullable=False, default=lambda: [])
    test_student_name = Column(String(100), nullable=True, default="Alex Johnson")
    test_student_names = Column(JSONB, nullable=False, default=lambda: ["Alex Johnson"])

    # ── Escalation ───────────────────────────────────────────────────────
    escalation_phone = Column(String(20), nullable=True)
    escalation_transfer_number = Column(String(20), nullable=True)

    # ── Appointment configuration ────────────────────────────────────────
    appointment_types = Column(
        JSONB, nullable=False,
        default=lambda: [
            {"code": "consultation", "name": "Consultation", "duration_minutes": 45, "slot_capacity": 1},
        ],
    )
    business_hours = Column(
        JSONB, nullable=True,
        # e.g. {"monday": {"open": "08:00", "close": "18:00"}, "sunday": null}
    )

    # ── Holidays / one-off closures ──────────────────────────────────────
    # Each entry: {"date": "YYYY-MM-DD", "name": "Christmas Day"}
    # Admin manages these via /api/tenants/{id}. When the AI is asked to
    # book or check slots on one of these dates, the system refuses and
    # the agent explains the office is closed for the holiday by name.
    holidays = Column(JSONB, nullable=False, default=lambda: [])

    # ── Reminder settings ──────────────────────────────────────────────
    reminder_settings = Column(
        JSONB, nullable=False,
        default=lambda: {
            "2h_enabled": True,
            "confirmation_reply_enabled": True,
        },
    )

    # ── Google Review solicitation ──────────────────────────────────────
    review_settings = Column(
        JSONB, nullable=False,
        default=lambda: {
            "enabled": False,
            "google_review_link": "",
            "delay_hours": 24,
            "appointment_types": [],  # empty = all types trigger review request
        },
    )

    # ── Knowledge base (replaces per-file default_kb.json) ──────────────
    knowledge_base = Column(JSONB, nullable=False, default=lambda: {})
    emergency_guidance = Column(Text, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<Tenant {self.slug} ({self.business_name})>"

