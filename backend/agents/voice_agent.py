"""
LiveKit Voice Agent Worker — FrontDesk AI

This is a long-running background process (NOT a FastAPI route).
It connects to the LiveKit server, waits for inbound SIP calls,
and runs the STT → LLM → TTS pipeline for each call.

Architecture:
  Student → Exotel (SIP trunk) → LiveKit SIP bridge → LiveKit Room
                                                            ↓
                                              This worker picks up the room
                                              Deepgram STT → Your LLM → Cartesia TTS
                                                            ↓
                                              Calls _execute_tool() for bookings

Run:
  python -m backend.agents.voice_agent dev        # local dev mode
  python -m backend.agents.voice_agent start      # production mode

Install (run OUTSIDE corporate proxy — whl files are blocked):
  pip install "livekit-agents[deepgram,silero,openai,google]>=1.0" livekit-plugins-cartesia

Targets: livekit-agents 1.x (tested with 1.6.x)
"""

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterable
from datetime import datetime, timedelta, timezone
from typing import Annotated

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, WorkerOptions, cli
from livekit.plugins import deepgram
from livekit.plugins import cartesia
from livekit.plugins import openai as lk_openai

from backend.config import settings
from backend.prompts.agent_prompt import build_system_prompt
from backend.routes.llm_proxy import _execute_tool
from backend.services.tenant_service import (
    TenantContext,
    resolve_default_tenant,
    resolve_tenant_by_sip_phone,
    resolve_tenant_by_caller_phone,
)

logger = logging.getLogger(__name__)


# ── SIP transfer phone normalisation ─────────────────────────────────────────

def _normalise_transfer_dest(raw: str) -> str:
    """
    Produce a clean E.164 phone number for use in `tel:` SIP URIs.

    Admins enter numbers in human-friendly formats like:
      +91 98765 43210   ->  +919876543210
      +1-800-555-1234   ->  +18005551234
      0091 9876543210   ->  +919876543210  (leading 00 = international prefix)
      091-9876543210    ->  +919876543210  (leading trunk 0 for India)

    Rules:
    1. Strip all non-digit characters except a leading '+'
    2. Replace leading '00' with '+' (international dialling prefix)
    3. Keep the result as-is — we trust that the admin stored a valid
       country-prefixed number, so we never guess a missing country code.
    4. Returns '' if the cleaned number has fewer than 7 digits (clearly invalid).

    This does NOT try to resolve or validate the number; it just makes it
    safe for embedding in a SIP URI.
    """
    if not raw:
        return ""
    # Try libphonenumber first — it handles every edge case correctly
    try:
        from backend.services.caller_service import _normalise_phone
        result = _normalise_phone(raw.strip(), default_region="IN")
        if result:
            return result
    except Exception:
        pass
    # Regex fallback: strip formatting, fix leading 00
    stripped = re.sub(r"[^\d+]", "", raw.strip())
    if stripped.startswith("00"):
        stripped = "+" + stripped[2:]
    digits_only = stripped.lstrip("+")
    if len(digits_only) < 7:
        return ""   # too short to be a real phone number
    return stripped


# ── Tenant resolution from SIP call metadata ─────────────────────────────────

async def _resolve_first_non_admin_tenant() -> "TenantContext | None":
    """
    For browser console testing (no SIP metadata): return the correct tenant
    for testing rather than whichever was created first.

    Resolution order:
      1. VOICE_CONSOLE_TEST_TENANT_SLUG env var — set this in .env to always
         use a specific tenant during browser console tests.
         e.g. VOICE_CONSOLE_TEST_TENANT_SLUG=bright-future-coaching
      2. First ACTIVE non-admin tenant ordered by updated_at DESC (most recently
         active tenant — likely the one being worked on).
    """
    from backend.database import async_session
    from backend.models.tenant import Tenant, TenantStatus
    from sqlalchemy import select as _select

    test_slug = os.getenv("VOICE_CONSOLE_TEST_TENANT_SLUG", "").strip()

    async with async_session() as session:
        if test_slug:
            result = await session.execute(
                _select(Tenant).where(
                    Tenant.slug == test_slug,
                    Tenant.status == TenantStatus.ACTIVE,
                )
            )
        else:
            result = await session.execute(
                _select(Tenant)
                .where(
                    Tenant.status == TenantStatus.ACTIVE,
                    Tenant.is_admin == False,  # noqa: E712
                )
                .order_by(Tenant.updated_at.desc())
                .limit(1)
            )
        tenant = result.scalar_one_or_none()

    if tenant:
        from backend.services.tenant_service import _tenant_to_context
        logger.info("[VoiceAgent] Console fallback: using tenant %s", tenant.slug)
        return _tenant_to_context(tenant)
    return None

async def _resolve_tenant(ctx: JobContext) -> tuple[TenantContext | None, str, str]:
    """
    Extract caller/called phone numbers from LiveKit SIP participant attributes
    and resolve the tenant.

    LiveKit SIP injects these attributes on the SIP participant:
      sip.callTo   — the dialled number (tenant's Exotel number)
      sip.callFrom — the caller's number

    Returns (tenant_ctx, caller_phone, called_phone).
    """
    caller_phone = ""
    called_phone = ""

    # CRITICAL: the SIP participant joins the room ~300ms AFTER the agent job
    # starts. Reading ctx.room.remote_participants immediately returns empty.
    # Wait for the participant so its sip.* attributes are populated.
    sip_participant = None
    try:
        import asyncio as _asyncio
        sip_participant = await _asyncio.wait_for(
            ctx.wait_for_participant(), timeout=10.0
        )
    except Exception as exc:
        logger.warning("[VoiceAgent] wait_for_participant failed/timed out: %s", exc)

    participants = (
        [sip_participant] if sip_participant
        else list(ctx.room.remote_participants.values())
    )
    for p in participants:
        attrs = p.attributes or {}
        if attrs:
            logger.info("[VoiceAgent] SIP participant attrs: %s", dict(attrs))
        # LiveKit SIP standard attributes:
        #   sip.trunkPhoneNumber — the DID the caller dialled (tenant's number)
        #   sip.phoneNumber      — the caller's own number
        called_phone = (
            attrs.get("sip.trunkPhoneNumber", "")
            or attrs.get("sip.callTo", "") or attrs.get("sip_call_to", "")
        )
        caller_phone = (
            attrs.get("sip.phoneNumber", "")
            or attrs.get("sip.callFrom", "") or attrs.get("sip_call_from", "")
            or attrs.get("sip.from", "")
        )
        # Fallback: LiveKit SIP participant identity is "sip_<caller-number>"
        if not caller_phone and p.identity and p.identity.startswith("sip_"):
            caller_phone = p.identity[len("sip_"):]
        if called_phone or caller_phone:
            break

    # Last resort: parse the caller number out of the room name.
    # Dispatch rule roomPrefix "call-" produces "call-_<caller>_<random>".
    if not caller_phone and ctx.room.name:
        m = re.search(r"\+?\d{10,15}", ctx.room.name)
        if m:
            caller_phone = m.group(0)
            logger.info("[VoiceAgent] Extracted caller from room name: %s", caller_phone)

    # Normalise: ensure a leading + on a bare international number
    if caller_phone and not caller_phone.startswith("+") and caller_phone.isdigit():
        caller_phone = "+" + caller_phone

    # Fallback: room metadata — set by /api/voice/token for browser console tests,
    # or by SIP dispatch rule config for real calls.
    # Format A: "{sip_phone}|{caller_phone}" — standard SIP-style metadata
    # Format B: "tenant:{uuid}|"             — direct tenant ID (no SIP number)
    if not called_phone and not caller_phone:
        meta = ctx.room.metadata or ""
        if meta.startswith("tenant:") and "|" in meta:
            # Direct tenant ID lookup — skip phone resolution
            tenant_id_str = meta.split("tenant:", 1)[1].split("|")[0].strip()
            logger.info("[VoiceAgent] Room metadata: direct tenant_id=%s", tenant_id_str)
            from backend.services.tenant_service import _tenant_to_context
            from backend.models.tenant import Tenant, TenantStatus
            from backend.database import async_session
            from sqlalchemy import select as _select
            import uuid as _uuid
            try:
                async with async_session() as _session:
                    _result = await _session.execute(
                        _select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id_str))
                    )
                    _t = _result.scalar_one_or_none()
                    if _t:
                        tenant_ctx = _tenant_to_context(_t)
                        logger.info("[VoiceAgent] Resolved from room metadata: tenant=%s", _t.slug)
                        return tenant_ctx, caller_phone, called_phone
            except Exception as exc:
                logger.warning("[VoiceAgent] Room metadata tenant lookup failed: %s", exc)
        elif "|" in meta:
            parts = meta.split("|", 1)
            called_phone, caller_phone = parts[0].strip(), parts[1].strip()

    logger.info("[VoiceAgent] SIP call: called=%s caller=%s room=%s",
                called_phone, caller_phone, ctx.room.name)

    # Tenant resolution priority:
    # 1. called_phone (the Exotel SIP number dialed) → one-to-one with a tenant ✓
    # 2. caller_phone (the student's own number) → look them up in Caller table
    #    to find which tenant they belong to. Works for real SIP calls where
    #    Exotel injects sip.callFrom even when called_phone isn't configured yet.
    # 3. Room metadata → set by /api/voice/token for browser console tests
    # 4. Env var / most-recently-updated non-admin tenant → last resort fallback
    tenant_ctx = None
    if called_phone:
        tenant_ctx = await resolve_tenant_by_sip_phone(called_phone)
    if not tenant_ctx and caller_phone:
        tenant_ctx = await resolve_tenant_by_caller_phone(caller_phone)
        if tenant_ctx:
            logger.info("[VoiceAgent] Tenant resolved from caller DB record: %s", tenant_ctx.slug)
    if not tenant_ctx:
        logger.warning("[VoiceAgent] No tenant matched — falling back to first non-admin tenant")
        tenant_ctx = await _resolve_first_non_admin_tenant()
        if not tenant_ctx:
            tenant_ctx = await resolve_default_tenant()

    return tenant_ctx, caller_phone, called_phone


# ── LLM factory — supports Ollama (local) and Gemini ─────────────────────────

def _build_llm():
    """
    Build the LLM plugin for voice calls.

    Provider resolution (most specific wins):
      1. VOICE_LLM_PROVIDER env var  — override just for voice
      2. LLM_PROVIDER from settings  — shared with text chat

    Model resolution:
      1. VOICE_LLM_MODEL env var     — override just for voice
      2. Fast default per provider   — gemini-2.0-flash / OLLAMA_MODEL

    Do NOT use thinking/reasoning models — they add 20-30s latency and stream
    chain-of-thought text to TTS.
    """
    provider = os.getenv("VOICE_LLM_PROVIDER", "") or settings.LLM_PROVIDER

    if provider == "groq":
        # Groq LPU inference: ~800 tok/s vs ~60 tok/s for hosted models.
        # Best choice for voice — fast enough that LLM latency is no longer
        # the bottleneck. llama-3.3-70b-versatile has reliable function calling.
        # Sign up at console.groq.com, set GROQ_API_KEY in .env.
        groq_key = os.getenv("GROQ_API_KEY", "")
        model = os.getenv("VOICE_LLM_MODEL", "llama-3.3-70b-versatile")
        logger.info("[VoiceAgent] Using Groq LLM: %s", model)
        return lk_openai.LLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            model=model,
        )

    if provider == "sambanova":
        # SambaNova Cloud — OpenAI-compatible API, fast inference (RDU chips).
        # Set SAMBANOVA_API_KEY in .env. Model IDs like "Meta-Llama-3.3-70B-Instruct".
        sn_key = os.getenv("SAMBANOVA_API_KEY", "")
        model = os.getenv("VOICE_LLM_MODEL", "Meta-Llama-3.3-70B-Instruct")
        logger.info("[VoiceAgent] Using SambaNova LLM: %s", model)
        return lk_openai.LLM(
            base_url="https://api.sambanova.ai/v1",
            api_key=sn_key,
            model=model,
        )

    if provider == "gemini" and settings.GEMINI_API_KEY:
        try:
            from livekit.plugins import google as lk_google
            model = os.getenv("VOICE_LLM_MODEL", "gemini-3.5-flash")
            logger.info("[VoiceAgent] Using Gemini LLM: %s (thinking disabled)", model)
            # thinking_budget=0 — gemini-3.5-flash is a thinking model; budget=0
            # disables chain-of-thought so it never leaks into the TTS stream.
            # temperature=0.3 → deterministic tool call decisions.
            return lk_google.LLM(
                model=model,
                api_key=settings.GEMINI_API_KEY,
                temperature=0.3,
                thinking_config={"thinking_budget": 0},
            )
        except ImportError:
            logger.warning("[VoiceAgent] livekit-plugins-google not installed — falling back to Ollama")

    model = os.getenv("VOICE_LLM_MODEL", settings.OLLAMA_MODEL)
    logger.info("[VoiceAgent] Using Ollama LLM: %s @ %s", model, settings.ollama_openai_base)
    return lk_openai.LLM(
        base_url=settings.ollama_openai_base,
        api_key="ollama",
        model=model,
    )


# ── Agent class with all 14 tools ────────────────────────────────────────────

class FrontDeskAgent(Agent):
    """
    AI receptionist agent for coaching institutes.
    Handles appointment booking, rescheduling, cancellations, waitlist,
    caller lookups, and office information — all via tool calls to the
    existing backend service layer.
    """

    def __init__(self, *, tenant_ctx: TenantContext | None, caller_phone: str, room: Any):
        self._tenant = tenant_ctx
        self._caller_phone = caller_phone
        self._room = room

        # Build full system prompt from existing prompt builder
        instructions = build_system_prompt(
            tenant_ctx=tenant_ctx,
            caller_phone=caller_phone,
        )
        super().__init__(instructions=instructions)
        logger.info("[VoiceAgent] Agent initialised for tenant=%s caller=%s",
                    tenant_ctx.slug if tenant_ctx else "default", caller_phone)

    async def _tool(self, name: str, **args) -> str:
        """Dispatch to the shared _execute_tool and return summary string."""
        result = await _execute_tool(
            name=name,
            args=args,
            tenant_ctx=self._tenant,
            caller_phone=self._caller_phone,
        )
        # Return the summary string — the LLM uses this to form its response
        return result.get("summary_for_assistant") or str(result)

    # ── Slot / availability tools ─────────────────────────────────────────

    @agents.function_tool
    async def get_available_slots(
        self,
        date: Annotated[str, "Date to check in YYYY-MM-DD format, or natural language like 'tomorrow'"],
        appointment_type: Annotated[str, "Appointment type code, e.g. 'demo_class', 'consultation'"],
    ) -> str:
        """Get available appointment slots for a given date and type."""
        return await self._tool("get_available_slots", date=date, appointment_type=appointment_type)

    @agents.function_tool
    async def get_week_slots(
        self,
        start_date: Annotated[str, "Start of the week in YYYY-MM-DD format"],
        appointment_type: Annotated[str, "Appointment type code"],
    ) -> str:
        """Get available slots for an entire week to help the caller choose a convenient day."""
        return await self._tool("get_week_slots", start_date=start_date, appointment_type=appointment_type)

    # ── Booking tools ─────────────────────────────────────────────────────

    @agents.function_tool
    async def book_appointment(
        self,
        caller_name: Annotated[str, "Full name of the person booking"],
        phone: Annotated[str, "Phone number of the person booking in E.164 format"],
        slot_time: Annotated[str, "Exact slot datetime from get_available_slots in ISO 8601 format"],
        appointment_type: Annotated[str, "Appointment type code"],
        provider_id: Annotated[str, "Provider ID (UUID) or '__auto__' for automatic assignment"],
        dob: Annotated[str, "Caller's date of birth in YYYY-MM-DD format (required)"],
        notes: Annotated[str, "Optional notes for the appointment"] = "",
    ) -> str:
        """Book an appointment for the caller."""
        # Prefer the real SIP caller number over whatever the LLM transcribed —
        # the model frequently hallucinates or mishears spoken digits.
        return await self._tool(
            "book_appointment",
            caller_name=caller_name,
            phone=self._caller_phone or phone,
            slot_time=slot_time,
            appointment_type=appointment_type,
            provider_id=provider_id,
            dob=dob,
            notes=notes,
        )

    @agents.function_tool
    async def reschedule_appointment(
        self,
        booking_uid: Annotated[str, "Booking UID from lookup_caller_appointments"],
        new_slot_time: Annotated[str, "New slot datetime in ISO 8601 format"],
        phone: Annotated[str, "Caller's phone number"] = "",
    ) -> str:
        """Reschedule an existing appointment to a new time slot."""
        return await self._tool(
            "reschedule_appointment",
            booking_uid=booking_uid,
            new_slot_time=new_slot_time,
            phone=phone or self._caller_phone,
        )

    @agents.function_tool
    async def cancel_appointment(
        self,
        booking_uid: Annotated[str, "Booking UID from lookup_caller_appointments"],
        phone: Annotated[str, "Caller's phone number"] = "",
        reason: Annotated[str, "Reason for cancellation"] = "",
    ) -> str:
        """Cancel an existing appointment."""
        return await self._tool(
            "cancel_appointment",
            booking_uid=booking_uid,
            phone=phone or self._caller_phone,
            reason=reason,
        )

    # ── Caller lookup tools ───────────────────────────────────────────────

    @agents.function_tool
    async def lookup_caller(
        self,
        phone: Annotated[str, "Caller's phone number in E.164 format"],
    ) -> str:
        """Look up a caller by phone number to get their name and profile."""
        # Always use the real SIP caller number — never the LLM's transcription.
        return await self._tool("lookup_caller", phone=self._caller_phone or phone)

    @agents.function_tool
    async def lookup_caller_appointments(
        self,
        phone: Annotated[str, "Caller's phone number in E.164 format"],
    ) -> str:
        """Get a caller's upcoming and past appointments."""
        return await self._tool("lookup_caller_appointments", phone=self._caller_phone or phone)

    @agents.function_tool
    async def update_caller_info(
        self,
        phone: Annotated[str, "Caller's phone number"],
        name: Annotated[str, "Updated name"] = "",
        email: Annotated[str, "Updated email address"] = "",
        notes: Annotated[str, "Notes about the caller"] = "",
    ) -> str:
        """Update a caller's name, email, or notes in the system."""
        return await self._tool("update_caller_info", phone=phone, name=name, email=email, notes=notes)

    # ── Provider / office tools ───────────────────────────────────────────

    @agents.function_tool
    async def get_providers(self) -> str:
        """Get the list of teachers, doctors, or staff who can take appointments."""
        return await self._tool("get_providers")

    @agents.function_tool
    async def get_office_info(self) -> str:
        """Get office details: address, hours, holidays, and contact information."""
        return await self._tool("get_office_info")

    # ── Waitlist tools ────────────────────────────────────────────────────

    @agents.function_tool
    async def add_to_waitlist(
        self,
        caller_name: Annotated[str, "Full name of the person"],
        phone: Annotated[str, "Phone number in E.164 format"],
        appointment_type: Annotated[str, "Appointment type requested"],
        preferred_date: Annotated[str, "Preferred date in YYYY-MM-DD format"] = "",
    ) -> str:
        """Add the caller to the waitlist when no slots are available."""
        return await self._tool(
            "add_to_waitlist",
            caller_name=caller_name,
            phone=phone or self._caller_phone,
            appointment_type=appointment_type,
            preferred_date=preferred_date,
        )

    @agents.function_tool
    async def check_waitlist_status(
        self,
        phone: Annotated[str, "Caller's phone number"],
    ) -> str:
        """Check a caller's current position on the waitlist."""
        return await self._tool("check_waitlist_status", phone=phone or self._caller_phone)

    # ── Escalation tools ──────────────────────────────────────────────────

    @agents.function_tool
    async def end_call(
        self,
        reason: Annotated[str, "Why the call is being ended, e.g. 'completed' or 'caller hung up'"],
    ) -> str:
        """Disconnect and end the phone call. Call this IMMEDIATELY after saying goodbye when the conversation is finished."""
        logger.info("[VoiceAgent] end_call called with reason: %s. Scheduling disconnect...", reason)
        
        async def _disconnect_soon():
            await asyncio.sleep(3.0)  # Wait for TTS to finish speaking the goodbye message
            try:
                logger.info("[VoiceAgent] Executing room disconnect: %s", self._room.name)
                await self._room.disconnect()
            except Exception as e:
                logger.warning("[VoiceAgent] Error disconnecting room: %s", e)

        asyncio.create_task(_disconnect_soon())
        return "Call ended successfully."

    @agents.function_tool
    async def escalate_to_human(
        self,
        reason: Annotated[str, "Why the caller needs to speak with a person"],
        caller_name: Annotated[str, "Caller's name"] = "",
        phone: Annotated[str, "Caller's phone number"] = "",
    ) -> str:
        """Transfer the caller to a human staff member or schedule a callback."""
        result = await _execute_tool(
            name="escalate_to_human",
            args={
                "reason": reason,
                "caller_name": caller_name,
                "phone": phone or self._caller_phone,
            },
            tenant_ctx=self._tenant,
            caller_phone=self._caller_phone,
        )

        raw_dest = result.get("destination", "")
        destination = _normalise_transfer_dest(raw_dest)
        if raw_dest and raw_dest != destination:
            logger.info(
                "[VoiceAgent] Escalation number normalised: %r -> %r",
                raw_dest, destination,
            )

        if not destination:
            logger.warning(
                "[VoiceAgent] No valid escalation number configured for tenant=%s",
                self._tenant.slug if self._tenant else "unknown",
            )
            return (
                "I'm sorry, I wasn't able to connect you directly right now, "
                "but I've sent an urgent alert to our team. "
                "Someone will call you back as soon as possible."
            )

        logger.info("[VoiceAgent] Initiating SIP transfer to: %s", destination)

        # Find the SIP participant in the room
        sip_participant = None
        for p in self._room.remote_participants.values():
            if p.identity.startswith("sip_") or (
                p.attributes and any(k.startswith("sip.") for k in p.attributes)
            ):
                sip_participant = p
                break

        if not sip_participant:
            logger.warning(
                "[VoiceAgent] No SIP participant found in room %s — cannot transfer",
                self._room.name,
            )
            return (
                "I've notified our team and they'll call you back shortly. "
                "Is there anything else I can help you with in the meantime?"
            )

        lk_client = None
        try:
            from livekit import api as lk_api
            lk_client = lk_api.LiveKitAPI(
                url=settings.LIVEKIT_URL,
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET,
            )
            logger.info(
                "[VoiceAgent] Transferring SIP participant %s to tel:%s",
                sip_participant.identity, destination,
            )
            await lk_client.sip.transfer_sip_participant(
                lk_api.TransferSIPParticipantRequest(
                    room_name=self._room.name,
                    participant_identity=sip_participant.identity,
                    transfer_to=f"tel:{destination}",
                )
            )
            logger.info("[VoiceAgent] SIP transfer succeeded -> %s", destination)
            # Schedule room disconnect — the caller's leg has moved to the
            # human's phone, so there is nobody left in this room.
            async def _close_after_transfer():
                await asyncio.sleep(2.0)
                try:
                    await self._room.disconnect()
                except Exception:
                    pass
            asyncio.create_task(_close_after_transfer())
            return "Connecting you to our team now. Please hold on."
        except Exception as e:
            logger.error("[VoiceAgent] SIP transfer failed: %s", e)
            return (
                "I tried to connect you but hit a technical issue. "
                "I've alerted our team and they'll call you back very soon."
            )
        finally:
            if lk_client:
                try:
                    await lk_client.aclose()
                except Exception:
                    pass

    @agents.function_tool
    async def send_callback_request(
        self,
        caller_name: Annotated[str, "Caller's name"],
        phone: Annotated[str, "Callback phone number"],
        reason: Annotated[str, "Reason for the callback request"] = "",
    ) -> str:
        """Log a callback request when the caller prefers to be called back."""
        return await self._tool(
            "send_callback_request",
            caller_name=caller_name,
            phone=phone or self._caller_phone,
            reason=reason,
        )


# ── Farewell detection — deterministic transcript check ──────────────────────
#
# When the ENTIRE utterance is a farewell we skip the LLM entirely, speak a
# warm goodbye via TTS, and disconnect.  This is faster + more reliable than
# waiting for the LLM to decide to call end_call.
#
# Criteria for a "farewell" utterance:
#   1. No question mark (still asking something → not a farewell)
#   2. Length ≤ 80 characters (long messages always have more content)
#   3. fullmatch against _FAREWELL_RE (the whole utterance is a goodbye)

_FAREWELL_RE = re.compile(
    r"(?:"
    # Pure goodbye words + cheers
    r"bye(?:\s+bye)?|goodbye|good[\s\-]?bye|ta[\s\-]?ta|ciao|cheerio|cheers|so\s+long"
    # Take care / see you (commas already stripped by _is_farewell)
    r"|take\s+care(?:\s+(?:bye|goodbye))?"
    r"|see\s+(?:you|ya)(?:\s+(?:later|soon|bye|tomorrow))?"
    # Thanks / Thank you
    r"|thanks?(?:\s+(?:so\s+much|a\s+lot|very\s+much|bye|goodbye|take\s+care|see\s+you))?"
    r"|thank\s+(?:you|u)(?:\s+(?:so\s+much|very\s+much|bye|goodbye|take\s+care))?"
    # Confirmation word(s) + optional thanks/bye
    r"|(?:ok(?:ay)?|alright|great|perfect|sure|yep|right)(?:\s+(?:thanks?|thank\s+(?:you|u)|bye|goodbye))*"
    # Wrap-up signals
    r"|that(?:'s|s)?\s+(?:all|it|fine|okay|good)(?:\s+(?:thanks?|thank\s+(?:you|u)))?"
    r"|(?:i(?:'m|m)?\s+)?(?:all\s+)?(?:good|fine|set|done|sorted)(?:\s+(?:thanks?|thank\s+(?:you|u)))?"
    r"|no(?:\s*)(?:that(?:'s|s)?\s+(?:all|it)|thanks?|thank\s+(?:you|u)|more\s+(?:questions?|queries?))"
    r"|nothing\s+(?:else|more|further)(?:\s+(?:thanks?|thank\s+(?:you|u)))?"
    r")",
    re.IGNORECASE,
)


def _is_farewell(text: str) -> bool:
    """
    Return True only when the ENTIRE utterance is a farewell with no stray questions.

    Guards:
    - Empty or too long -> False (real farewells are short)
    - Contains '?' -> False (still asking something)
    - fullmatch against _FAREWELL_RE (whole utterance must be a goodbye pattern)

    Commas are treated as natural speech pauses and stripped before matching
    (e.g. "thanks, bye" -> "thanks bye" before fullmatch).
    """
    if not text or "?" in text:
        return False
    # Strip trailing punctuation and speech-pause commas
    cleaned = text.strip().rstrip("!.,?").strip()
    cleaned = re.sub(r",", " ", cleaned)    # "thanks, bye" -> "thanks  bye"
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()  # collapse whitespace
    if not cleaned or len(cleaned) > 80:
        return False
    return bool(_FAREWELL_RE.fullmatch(cleaned))


# ── TTS text filter — strip leaked tool call syntax ───────────────────────────

# Some models (Gemini thinking variants, smaller Ollama) occasionally emit the
# tool call JSON or "tool_code ..." as plain text instead of executing it.
# This filter runs on every token stream before it reaches Cartesia TTS.
_TOOL_KW = r'"(?:function|arguments|tool_name|tool_call)"'
# Matches JSON objects (one level of nesting) that contain tool call keywords
_INLINE_JSON_RE = re.compile(
    r'\{(?:[^{}]|\{[^{}]*\})*' + _TOOL_KW + r'(?:[^{}]|\{[^{}]*\})*\}',
    re.DOTALL,
)
# Matches whole lines that are tool call output
_TOOL_CALL_LINE_RE = re.compile(
    r'^\s*(?:'
    r'\{[\s\S]*?' + _TOOL_KW +  # starts with { and contains a tool keyword
    r'|tool_code\s+\w'           # tool_code print(...)
    r')',
    re.IGNORECASE,
)


async def _filter_tool_syntax(text: AsyncIterable[str]) -> AsyncIterable[str]:
    """
    Strip model-leaked tool call syntax before it reaches TTS.

    Handles two patterns:
    - Whole lines that ARE a tool call (skipped entirely)
    - Inline JSON blobs embedded in otherwise normal text (stripped out)
    """
    buffer = ""
    async for chunk in text:
        buffer += chunk
        # Flush complete lines only — avoids splitting a pattern across chunks
        if "\n" in buffer:
            lines = buffer.split("\n")
            buffer = lines.pop()  # last (incomplete) line stays in buffer
            for line in lines:
                cleaned = _INLINE_JSON_RE.sub("", line).strip()
                if cleaned and not _TOOL_CALL_LINE_RE.match(cleaned):
                    yield cleaned + "\n"
    # Flush remaining buffer
    if buffer:
        cleaned = _INLINE_JSON_RE.sub("", buffer).strip()
        if cleaned and not _TOOL_CALL_LINE_RE.match(cleaned):
            yield cleaned


# ── Call record & usage tracking ──────────────────────────────────────────────

async def _save_call_record(
    room_name: str,
    tenant_ctx: "TenantContext | None",
    caller_phone: str,
    duration_seconds: int,
) -> None:
    """
    Persist a Call row and increment billing usage when a call ends.
    Called from the JobContext shutdown callback so it always fires even on
    abrupt disconnects.
    """
    from backend.database import async_session
    from backend.models.call import Call
    from backend.services.usage_service import record_call_minutes

    duration_minutes = max(0.0, duration_seconds / 60.0)
    ended_at = datetime.now(timezone.utc)
    started_at = ended_at - timedelta(seconds=duration_seconds)

    try:
        async with async_session() as session:
            call = Call(
                vapi_call_id=room_name,   # reuse nullable field — room name is unique
                tenant_id=tenant_ctx.tenant_id if tenant_ctx else None,
                caller_number=caller_phone or None,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
            )
            session.add(call)
            await session.commit()
        logger.info("[VoiceAgent] Call saved: room=%s tenant=%s duration=%ds",
                    room_name, tenant_ctx.slug if tenant_ctx else "?", duration_seconds)
    except Exception as exc:
        logger.error("[VoiceAgent] Failed to save call record: %s", exc)

    if tenant_ctx:
        try:
            await record_call_minutes(tenant_ctx.tenant_id, duration_minutes)
        except Exception as exc:
            logger.error("[VoiceAgent] Failed to record call minutes: %s", exc)


# ── Entrypoint — called once per inbound call ─────────────────────────────────

async def entrypoint(ctx: JobContext):
    """
    LiveKit calls this function when a new room is created (i.e. a call comes in).
    We resolve the tenant, build the agent, and start the voice pipeline.
    """
    await ctx.connect()
    call_start = time.monotonic()

    # Resolve tenant from SIP call metadata
    tenant_ctx, caller_phone, called_phone = await _resolve_tenant(ctx)

    # Register call-end callback to record duration + billing usage
    async def _on_call_end() -> None:
        duration_seconds = max(0, int(time.monotonic() - call_start))
        await _save_call_record(
            room_name=ctx.room.name,
            tenant_ctx=tenant_ctx,
            caller_phone=caller_phone,
            duration_seconds=duration_seconds,
        )

    ctx.add_shutdown_callback(_on_call_end)

    # Cartesia TTS — free tier at cartesia.ai, set CARTESIA_API_KEY in .env
    # Default: "a0e99841-438c-4a64-b679-ae501e7d6091" = Barbra (warm female, en-US)
    # Browse voices at play.cartesia.ai — copy the UUID from the voice card.
    # Per-tenant: set voice_config["voiceId"] to a Cartesia UUID in agent settings.
    DEFAULT_CARTESIA_VOICE = "a0e99841-438c-4a64-b679-ae501e7d6091"  # Barbra
    cartesia_voice = DEFAULT_CARTESIA_VOICE
    if tenant_ctx and isinstance(tenant_ctx.voice_config, dict):
        configured = tenant_ctx.voice_config.get("voiceId", "")
        # Use only if it looks like a UUID (36 chars, 4 dashes)
        if configured and len(configured) == 36 and configured.count("-") == 4:
            cartesia_voice = configured

    tts_engine = cartesia.TTS(
        voice=cartesia_voice,
        model="sonic-2",
        api_key=os.getenv("CARTESIA_API_KEY", ""),
    )
    logger.info("[VoiceAgent] TTS: Cartesia voice=%s", cartesia_voice)

    # Build STT — Deepgram with Indian English
    stt_engine = deepgram.STT(
        model="nova-2",
        language="en-IN",   # Indian English; change to "hi" for Hindi
        api_key=os.getenv("DEEPGRAM_API_KEY", ""),
    )

    # Create session with full pipeline
    # vad is omitted — AgentSession now bundles silero VAD by default
    # tts_text_transforms: filter_markdown (default) + our custom tool-call stripper
    session = AgentSession(
        stt=stt_engine,
        llm=_build_llm(),
        tts=tts_engine,
        tts_text_transforms=["filter_markdown", _filter_tool_syntax],
    )

    agent = FrontDeskAgent(tenant_ctx=tenant_ctx, caller_phone=caller_phone, room=ctx.room)

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )

    # ── Farewell fast-path: bypass LLM for obvious goodbye utterances ─────────
    # We listen for the final transcript of each user turn.  If the ENTIRE
    # utterance is a recognised farewell phrase (short, no question mark,
    # matches _FAREWELL_RE) we:
    #   1. Set a flag so the LLM pipeline is not started for that turn
    #   2. Interrupt any in-progress agent speech
    #   3. Speak a warm, short goodbye via TTS
    #   4. Disconnect the room after a short pause for TTS playback
    #
    # This guarantees call teardown in ~3 s instead of waiting for the LLM
    # to (maybe) decide to call end_call.

    _call_ended = asyncio.Event()   # guard against double-disconnect

    biz_name_goodbye = (tenant_ctx.business_name if tenant_ctx else None) or "us"

    async def _hangup_gracefully() -> None:
        """Speak goodbye and disconnect.  Safe to call multiple times."""
        if _call_ended.is_set():
            return
        _call_ended.set()
        farewell_line = f"Thank you for calling {biz_name_goodbye}. Have a wonderful day! Goodbye!"
        try:
            session.interrupt()
        except Exception:
            pass
        try:
            # allow_interruptions=False so the caller can't restart the turn
            await session.say(farewell_line, allow_interruptions=False)
        except Exception:
            pass
        # Give Cartesia time to stream the last chunk to the caller's phone
        await asyncio.sleep(3.5)
        try:
            await ctx.room.disconnect()
        except Exception as _e:
            logger.warning("[VoiceAgent] Room disconnect error: %s", _e)

    @session.on("user_input_transcribed")
    def _on_transcript(event) -> None:
        """
        Fired by AgentSession after STT finalises each user turn.
        `event` has at minimum: .transcript (str) and .is_final (bool).
        """
        try:
            transcript = getattr(event, "transcript", "") or ""
            is_final   = getattr(event, "is_final", True)
            if not is_final:
                return
            if _is_farewell(transcript):
                logger.info(
                    "[VoiceAgent] Farewell detected (%r) — initiating graceful hangup", transcript
                )
                asyncio.ensure_future(_hangup_gracefully())
        except Exception as _exc:
            logger.debug("[VoiceAgent] _on_transcript error (non-fatal): %s", _exc)


    # Look up returning caller in the database to greet them by first name
    greeting = "Hello! How can I help you today?"
    if caller_phone:
        try:
            from backend.services import caller_service
            # Resolve tenant ID scope
            t_id = tenant_ctx.tenant_id if tenant_ctx else None
            caller_rec = await caller_service.get_caller_by_phone(caller_phone, tenant_id=t_id)
            if caller_rec and caller_rec.name and caller_rec.name.strip() and caller_rec.name.lower() != "unknown":
                first_name = caller_rec.name.strip().split()[0]
                biz_name = tenant_ctx.business_name if tenant_ctx else "Bright Future Coaching"
                greeting = f"Hello {first_name}! Welcome back to {biz_name}. How can I help you today?"
                logger.info("[VoiceAgent] Greeting returning caller by name: %s", caller_rec.name)
            elif tenant_ctx:
                greeting = tenant_ctx.greeting_message or greeting
        except Exception as exc:
            logger.warning("[VoiceAgent] Failed to look up caller for name-greeting: %s", exc)
            if tenant_ctx:
                greeting = tenant_ctx.greeting_message or greeting
    elif tenant_ctx:
        greeting = tenant_ctx.greeting_message or greeting

    await session.say(greeting, allow_interruptions=True)


# ── Worker entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
            ws_url=settings.LIVEKIT_URL,
            agent_name="receptico",
        )
    )
