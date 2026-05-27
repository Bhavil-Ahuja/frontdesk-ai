"""
Async SQLAlchemy database engine, session factory, and table initialisation.
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Engine & session factory ──────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
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
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables that don't yet exist, then apply column migrations."""
    logger.info("Connecting to database: %s", settings.DATABASE_URL.split("@")[-1])  # Log host only, not creds
    async with engine.begin() as conn:
        # Import models so they register with Base.metadata
        from backend.models import tenant, call, appointment, patient, provider, waitlist, sms_message, profile_change_log  # noqa: F401
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
