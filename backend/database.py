"""
Async SQLAlchemy database engine, session factory, and table initialisation.
"""

import logging
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Sanitise DATABASE_URL for asyncpg compatibility ─────────────────────────
# Cloud providers like Neon append query params (channel_binding, sslmode)
# that asyncpg doesn't understand.  Strip them so the engine can connect.

_ASYNCPG_UNSUPPORTED_PARAMS = {"channel_binding", "sslmode"}


def _sanitise_db_url(raw_url: str) -> str:
    """Remove query-string params that asyncpg cannot handle."""
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # Convert sslmode=require → ssl=require (asyncpg uses 'ssl')
    if "sslmode" in params and "ssl" not in params:
        params["ssl"] = params["sslmode"]

    cleaned = {k: v for k, v in params.items() if k not in _ASYNCPG_UNSUPPORTED_PARAMS}
    new_query = urlencode(cleaned, doseq=True)
    sanitised = urlunparse(parsed._replace(query=new_query))
    if sanitised != raw_url:
        logger.info("Sanitised DATABASE_URL: removed unsupported asyncpg params %s",
                     [k for k in params if k in _ASYNCPG_UNSUPPORTED_PARAMS])
    return sanitised


_db_url = _sanitise_db_url(settings.DATABASE_URL)

# ── Engine & session factory ──────────────────────────────────────────────────

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── Base model ────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ── Schema migrations ───────────────────────────────────────────────────────
# Since we don't use Alembic, new columns on *existing* tables must be added
# via ALTER TABLE.  create_all() only creates new tables — it won't touch
# existing ones.  Each statement uses IF NOT EXISTS so it's safe to re-run.

_MIGRATIONS: list[str] = [
    # ── tenants table — reminder & review settings ────────────────────────
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS reminder_settings JSONB DEFAULT '{\"2h_enabled\": true, \"confirmation_reply_enabled\": true}'::jsonb",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS review_settings JSONB DEFAULT '{\"enabled\": false, \"google_review_link\": \"\", \"delay_hours\": 24, \"appointment_types\": []}'::jsonb",

    # ── tenants table — test caller phone for Test Agent chat
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS test_caller_phone VARCHAR(20)",
    # Backfill existing tenants with a random +155501XXX test phone
    "UPDATE tenants SET test_caller_phone = '+155501' || (100 + floor(random() * 100))::int::text WHERE test_caller_phone IS NULL",

    # ── tenants table — multiple test caller phones (JSONB array)
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS test_caller_phones JSONB DEFAULT '[]'::jsonb",
    # Backfill: seed array from existing single test_caller_phone if not yet populated
    """UPDATE tenants
       SET test_caller_phones = jsonb_build_array(test_caller_phone)
       WHERE test_caller_phone IS NOT NULL
         AND (test_caller_phones IS NULL OR test_caller_phones = '[]'::jsonb)""",

    # ── tenants table — unified test_callers [{phone, name}] (replaces parallel arrays)
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS test_callers JSONB DEFAULT '[]'::jsonb",

    # ── tenants table — Google Maps share-link for the clinic location
    #    Used at signup for admin approval review (iframe preview) and inside
    #    SMS / email templates as a clickable map link.
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS google_maps_url TEXT",

    # ── tenants table — list of one-off holiday closures
    #    Each entry: {"date": "YYYY-MM-DD", "name": "Christmas Day"}
    #    Used by the slot generator (refuses bookings on these dates) and by
    #    the AI agent (proactively tells callers when a day is a holiday).
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS holidays JSONB NOT NULL DEFAULT '[]'::jsonb",

    # ── appointments table — provider, extra reminders, patient confirmation
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS provider_id UUID REFERENCES providers(id)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_2h_sent_at TIMESTAMPTZ",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS review_requested_at TIMESTAMPTZ",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS confirmed_by_patient BOOLEAN",

    # ── tenants table — drop orphaned calcom_event_types column
    #    This column was added manually during a Cal.com integration experiment
    #    but never added to the SQLAlchemy model.  Its NOT NULL constraint causes
    #    INSERT failures on tenant registration.  Safe to drop — no code reads it.
    "ALTER TABLE tenants DROP COLUMN IF EXISTS calcom_event_types",

    # ── appointmentstatus enum — add NO_SHOW value (safe if already exists)
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'NO_SHOW' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'appointmentstatus')) THEN
            ALTER TYPE appointmentstatus ADD VALUE 'NO_SHOW';
        END IF;
    END $$;""",

    # ── appointments — prevent double-booking the same provider at the same
    #    instant. Partial unique index excludes cancelled/completed/no-show
    #    rows so reusing a slot after cancellation is still possible.
    #    NOTE: COALESCE handles NULL provider_id by treating "no provider" as
    #    a single virtual provider — useful for tenants who don't yet use
    #    providers. If you need to allow multiple "no provider" bookings at
    #    the same time, drop this index.
    """CREATE UNIQUE INDEX IF NOT EXISTS uniq_appt_provider_time
       ON appointments (
           tenant_id,
           COALESCE(provider_id, '00000000-0000-0000-0000-000000000000'::uuid),
           scheduled_at
       )
       WHERE status IN ('CONFIRMED', 'RESCHEDULED')""",

    # ── tenants table — usage metering columns (Option A billing) ────────
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS call_minutes_used DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sms_sent INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ",

    # ── tenants table — per-tenant feature flags for Vapi & Twilio ──────
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS feature_vapi_enabled BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS feature_twilio_enabled BOOLEAN NOT NULL DEFAULT true",

    # ── support_tickets table — generic help / ticket system ────────────
    """CREATE TABLE IF NOT EXISTS support_tickets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        subject VARCHAR(200) NOT NULL,
        body TEXT NOT NULL,
        category VARCHAR(20) NOT NULL DEFAULT 'GENERAL',
        status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
        priority VARCHAR(10) NOT NULL DEFAULT 'MEDIUM',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        resolved_at TIMESTAMPTZ,
        admin_notes TEXT,
        resolved_by VARCHAR(255)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_support_tickets_tenant_status ON support_tickets (tenant_id, status)",

    # ── support_ticket_messages table — conversation thread per ticket ───
    """CREATE TABLE IF NOT EXISTS support_ticket_messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id UUID NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
        sender_type VARCHAR(10) NOT NULL,
        sender_name VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ticket_messages_ticket_created ON support_ticket_messages (ticket_id, created_at)",

    # ── appointments table — make provider_id NOT NULL for new rows ──────
    # Backfill existing NULL provider_ids with tenant's first active provider
    """DO $$ BEGIN
        UPDATE appointments a
        SET provider_id = (
            SELECT p.id FROM providers p
            WHERE p.tenant_id = a.tenant_id AND p.is_active = true
            ORDER BY p.created_at ASC LIMIT 1
        )
        WHERE a.provider_id IS NULL
          AND EXISTS (
            SELECT 1 FROM providers p
            WHERE p.tenant_id = a.tenant_id AND p.is_active = true
          );
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Provider backfill skipped: %', SQLERRM;
    END $$;""",

    # ── is_test flag — separate test/demo data from real patient data ──
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",

    # ── phone normalisation — strip dashes, spaces, parentheses ────────
    #    Historic data may contain "635-241-8405" or "(512) 555-1234" which
    #    breaks suffix-match queries.  Strip all non-digit / non-plus chars
    #    so stored phones look like "+16352418405" or "6352418405".
    "UPDATE appointments SET patient_phone = regexp_replace(patient_phone, '[^0-9+]', '', 'g') WHERE patient_phone ~ '[^0-9+]'",
    "UPDATE patients SET phone = regexp_replace(phone, '[^0-9+]', '', 'g') WHERE phone ~ '[^0-9+]'",
    "UPDATE waitlist_entries SET patient_phone = regexp_replace(patient_phone, '[^0-9+]', '', 'g') WHERE patient_phone IS NOT NULL AND patient_phone ~ '[^0-9+]'",
    "UPDATE sms_messages SET to_number = regexp_replace(to_number, '[^0-9+]', '', 'g') WHERE to_number IS NOT NULL AND to_number ~ '[^0-9+]'",

    # ── tenants table — owner-toggleable agent on/off (separate from status)
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS agent_active BOOLEAN NOT NULL DEFAULT true",

    # ── appointment_status_history — audit trail for status changes ──
    """CREATE TABLE IF NOT EXISTS appointment_status_history (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        appointment_id UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
        old_status VARCHAR(20),
        new_status VARCHAR(20) NOT NULL,
        changed_by VARCHAR(100) NOT NULL DEFAULT 'system',
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_status_history_appt ON appointment_status_history (appointment_id, created_at)",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables that don't yet exist, then apply column migrations."""
    logger.info("Connecting to database: %s", settings.DATABASE_URL.split("@")[-1])  # Log host only, not creds
    async with engine.begin() as conn:
        # Import models so they register with Base.metadata
        from backend.models import tenant, call, appointment, patient, provider, waitlist, sms_message, profile_change_log, support_ticket, status_history  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    # Apply column-level migrations (idempotent — safe to re-run)
    async with engine.begin() as conn:
        applied = 0
        for stmt in _MIGRATIONS:
            try:
                await conn.execute(text(stmt))
                applied += 1
            except Exception as exc:
                # Log but don't crash — column might already exist (non-PG DBs
                # may not support IF NOT EXISTS for ADD COLUMN).
                logger.warning("Migration skipped (%s): %s", exc.__class__.__name__, str(exc)[:120])
        if applied:
            logger.info("Applied %d column migrations on existing tables.", applied)

    logger.info("Database tables created / verified: tenants, calls, appointments, patients, providers, waitlist_entries, sms_messages")


async def get_db() -> AsyncSession:
    """Dependency — yields an async session then closes it."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            logger.error("Database session error — rolling back: %s", exc)
            await session.rollback()
            raise
        finally:
            await session.close()
