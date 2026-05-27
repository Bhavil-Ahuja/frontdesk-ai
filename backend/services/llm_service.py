"""
LLM service — stateful conversation manager using Ollama
via the OpenAI-compatible API (model configured in .env as OLLAMA_MODEL).

Maintains per-call session state in an in-memory dict keyed by vapi_call_id.
Implements tool-calling for appointment operations and escalation.

Multi-tenant: when a TenantContext is provided, tool definitions are filtered
based on what integrations the tenant has configured (e.g. hide escalation
tools when Twilio isn't set up) and all downstream service calls receive the
tenant context so they use the correct credentials.
"""

import asyncio
import json
import logging
import re as _re
import time
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI, OpenAI

# New `google-genai` SDK — supports ThinkingConfig with thinking_level=MINIMAL
# which turns OFF Gemma's chain-of-thought reasoning at the source.
# This replaces the deprecated `google-generativeai` v0.8.6 SDK.
from google import genai
from google.genai import types as gtypes

from backend.config import settings
from backend.services import calendar_service, sms_service, knowledge_service
from backend.prompts.agent_prompt import build_system_prompt

logger = logging.getLogger(__name__)


# ── Tool-call-as-text detection ───────────────────────────────────────────────
# Some models (Qwen3, etc.) output tool calls as text tags instead of using
# the proper function calling API. These helpers detect, strip, and parse them.

_TOOL_TAG_PATTERNS = [
    ("<tool_call>", "</tool_call>"),
    ("<function_call>", "</function_call>"),
    ("<|tool_call|>", "<|/tool_call|>"),
    ("<|function|>", "<|/function|>"),
    ("<tool>", "</tool>"),
    ("<function>", "</function>"),
]


def _has_tool_tag_start(text: str) -> bool:
    return any(start in text for start, _ in _TOOL_TAG_PATTERNS)


def _has_tool_tag_end(text: str) -> bool:
    return any(end in text for _, end in _TOOL_TAG_PATTERNS)


def _strip_tool_block(text: str) -> tuple[str, str]:
    """Strip a tool call block from text, returning (before, after)."""
    for start_tag, end_tag in _TOOL_TAG_PATTERNS:
        if start_tag in text and end_tag in text:
            before = text.split(start_tag, 1)[0]
            after = text.split(end_tag, 1)[1] if end_tag in text else ""
            return before, after
    return text, ""


def _parse_tool_call_text(text: str) -> dict | None:
    """
    Parse a tool call from text-based output (e.g., <tool_call>{...}</tool_call>).
    Returns dict with 'name' and 'arguments' or None if parsing fails.
    """
    for start_tag, end_tag in _TOOL_TAG_PATTERNS:
        pat = _re.escape(start_tag) + r"\s*(\{.*?\})\s*" + _re.escape(end_tag)
        match = _re.search(pat, text, _re.DOTALL)
        if match:
            try:
                tc_json = json.loads(match.group(1))
                fn_name = tc_json.get("name", "")
                fn_args = tc_json.get("arguments", {})
                if isinstance(fn_args, str):
                    fn_args = json.loads(fn_args)
                return {"name": fn_name, "arguments": fn_args}
            except (json.JSONDecodeError, KeyError):
                continue
    return None


# ── In-memory session store ──────────────────────────────────────────────────
# Keyed by vapi_call_id. Each session holds conversation state for one call.

sessions: dict[str, dict[str, Any]] = {}

# Maximum age (seconds) for a session before it's considered abandoned.
# Vapi calls rarely last more than 30 minutes; 2 hours is very generous.
_SESSION_MAX_AGE = 2 * 60 * 60  # 2 hours


def _cleanup_stale_sessions() -> int:
    """Remove sessions older than _SESSION_MAX_AGE. Returns count removed."""
    now = time.time()
    stale = [
        cid for cid, s in sessions.items()
        if now - s.get("call_start_time", now) > _SESSION_MAX_AGE
    ]
    for cid in stale:
        sessions.pop(cid, None)
    if stale:
        logger.warning("Cleaned up %d stale session(s): %s", len(stale),
                        ", ".join(stale[:5]))
    return len(stale)


def _refresh_system_time(session: dict[str, Any]) -> None:
    """Update the CURRENT TIME line in the system prompt so the agent always
    knows the real time, not the time when the session was created."""
    import re
    from zoneinfo import ZoneInfo
    msgs = session.get("messages")
    if not msgs or msgs[0].get("role") != "system":
        return
    tenant_ctx = session.get("tenant_ctx")
    tz_name = getattr(tenant_ctx, "timezone", None) or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    time_str = now.strftime("%I:%M %p").lstrip("0")
    if now.hour < 12:
        period = "morning"
    elif now.hour < 17:
        period = "afternoon"
    else:
        period = "evening"
    new_line = f"CURRENT TIME is {time_str} {period} ({tz_name})."
    msgs[0]["content"] = re.sub(
        r"CURRENT TIME is .+?\.",
        new_line,
        msgs[0]["content"],
        count=1,
    )

# ── OpenAI client pointed at Ollama ──────────────────────────────────────────

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        logger.info("Initializing OpenAI client → Ollama at %s (model: %s)",
                     settings.ollama_openai_base, settings.OLLAMA_MODEL)
        _client = OpenAI(
            base_url=settings.ollama_openai_base,
            api_key="ollama",  # Ollama ignores the key but the SDK requires one
            timeout=45.0,  # 45s timeout to prevent indefinite hangs
        )
    return _client


_async_client: AsyncOpenAI | None = None


def _get_async_client() -> AsyncOpenAI:
    """Async client for true token-by-token streaming from Ollama."""
    global _async_client
    if _async_client is None:
        logger.info("Initializing AsyncOpenAI (streaming) → Ollama at %s",
                     settings.ollama_openai_base)
        _async_client = AsyncOpenAI(
            base_url=settings.ollama_openai_base,
            api_key="ollama",
            timeout=45.0,  # 45s timeout to prevent indefinite hangs
        )
    return _async_client


# ── Gemini client (google-genai SDK) ─────────────────────────────────────────

_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    """Lazily create a singleton google-genai Client."""
    global _gemini_client
    if _gemini_client is None:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set in .env")
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info("Gemini client initialized — model: %s", settings.GEMINI_MODEL)
    return _gemini_client


def _build_gemini_config(
    system_instruction: str = "",
    tools: list | None = None,
    cached_content: str | None = None,
) -> gtypes.GenerateContentConfig:
    """
    Build a GenerateContentConfig with ThinkingLevel.MINIMAL.

    For Gemma 4 (and other thinking-capable models) MINIMAL turns the
    chain-of-thought OFF, so the model returns just the final response
    without reasoning leakage.

    If `cached_content` is provided, system_instruction and tools come from
    the cache (cheaper) and we pass only the dynamic per-call portions.
    """
    kwargs: dict[str, Any] = {
        "temperature": 0.7,
        "max_output_tokens": 1024,
        "thinking_config": gtypes.ThinkingConfig(
            thinking_level=gtypes.ThinkingLevel.MINIMAL,
        ),
    }
    if cached_content:
        kwargs["cached_content"] = cached_content
    else:
        # Only set these when NOT using a cache — caches already contain them.
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        if tools:
            kwargs["tools"] = tools
    return gtypes.GenerateContentConfig(**kwargs)


# ── Gemini history trimming ──────────────────────────────────────────────────

def _trim_gemini_history(
    history: list["gtypes.Content"],
    max_messages: int,
) -> list["gtypes.Content"]:
    """
    Trim chat history to the last `max_messages` entries.

    Preserves function_call ↔ function_response pairs: if the trim boundary
    falls in the middle of a tool-call/tool-response pair, we drop the
    dangling function_response(s) from the front so Gemini doesn't error
    with "function_response without preceding function_call".
    """
    if max_messages <= 0 or len(history) <= max_messages:
        return history

    trimmed = history[-max_messages:]

    # Drop any function_response(s) at the head with no matching call.
    while trimmed:
        first = trimmed[0]
        has_fn_response = (
            getattr(first, "role", None) == "user"
            and getattr(first, "parts", None)
            and any(getattr(p, "function_response", None) for p in first.parts)
        )
        if has_fn_response:
            trimmed = trimmed[1:]
        else:
            break

    logger.info(
        "[Gemini] Trimmed history %d → %d messages (max=%d)",
        len(history), len(trimmed), max_messages,
    )
    return trimmed


# ── Gemini explicit context cache pool ───────────────────────────────────────

# Per-tenant cache: tenant_id (or "default") → (cache_name, expires_at_unix)
# The cache stores the static system prompt + tool declarations so we don't
# re-send ~5–8K tokens of prefix on every call. Gemini bills cached input at
# ~25% of the regular rate.
_gemini_cache_pool: dict[str, tuple[str, float]] = {}


def _gemini_cache_key(tenant_ctx: Any | None, model: str) -> str:
    """Stable cache pool key per (tenant, model)."""
    if tenant_ctx is None:
        return f"default::{model}"
    return f"{getattr(tenant_ctx, 'id', 'default')}::{model}"


async def _get_or_create_gemini_cache(
    system_prompt: str,
    tools: list | None,
    tenant_ctx: Any | None,
) -> str | None:
    """
    Look up or lazily create a CachedContent for this (tenant, model).

    Returns the cache resource name if successful, or None if caching
    isn't supported / failed (so callers can fall back to inline send).
    """
    if not settings.GEMINI_USE_CONTEXT_CACHE:
        return None
    if not system_prompt and not tools:
        return None

    key = _gemini_cache_key(tenant_ctx, settings.GEMINI_MODEL)
    now = time.time()
    cached = _gemini_cache_pool.get(key)
    # 60s safety buffer — refresh before TTL actually expires
    if cached and cached[1] > now + 60:
        return cached[0]

    try:
        client = _get_gemini_client()
        cache = await client.aio.caches.create(
            model=settings.GEMINI_MODEL,
            config=gtypes.CreateCachedContentConfig(
                system_instruction=system_prompt or None,
                tools=tools,
                ttl=f"{settings.GEMINI_CACHE_TTL_SECONDS}s",
            ),
        )
        expires_at = now + settings.GEMINI_CACHE_TTL_SECONDS
        _gemini_cache_pool[key] = (cache.name, expires_at)
        logger.info(
            "[Gemini] Created context cache %s for %s (TTL=%ds)",
            cache.name, key, settings.GEMINI_CACHE_TTL_SECONDS,
        )
        return cache.name
    except Exception as exc:
        # Common failure modes: model doesn't support caching, prompt too
        # small (<1024 tokens), API quota. Disable for this key so we don't
        # retry hot in a loop.
        logger.warning(
            "[Gemini] Context cache creation failed for %s — falling back to "
            "inline send. (%s: %s)",
            key, type(exc).__name__, exc,
        )
        # Cache the failure for a minute so we don't hammer the API.
        _gemini_cache_pool[key] = ("", now + 60)
        return None


# ── Tool definitions (sent to the LLM for function calling) ──────────────────

# Full list of all tools. Use get_tools(tenant_ctx) to get the filtered
# subset appropriate for a given tenant's configured integrations.
ALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Look up available appointment slots for a given date and type. If the patient requested a specific provider, include their ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date to check in YYYY-MM-DD format.",
                    },
                    "appointment_type": {
                        "type": "string",
                        "description": "Type of appointment.",
                    },
                    "provider_id": {
                        "type": "string",
                        "description": "Optional. ID of the provider the patient wants to see (from get_providers).",
                    },
                },
                "required": ["date", "appointment_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment for the patient. Include provider_id if the patient chose a specific provider.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string", "description": "Patient email (optional — system provides default if not given)."},
                    "dob": {"type": "string", "description": "Date of birth (MM/DD/YYYY)."},
                    "appointment_type": {
                        "type": "string",
                        "description": "Type of appointment.",
                    },
                    "slot_time": {"type": "string", "description": "ISO datetime of the chosen slot."},
                    "provider_id": {
                        "type": "string",
                        "description": "Optional. ID of the provider to book with (from get_providers).",
                    },
                },
                "required": ["patient_name", "phone", "appointment_type", "slot_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {"type": "string", "description": "Booking reference ID from the original booking."},
                    "new_slot_time": {"type": "string", "description": "New ISO datetime."},
                },
                "required": ["booking_uid", "new_slot_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["booking_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Transfer the call to a human receptionist. ONLY call this for: (1) immediate medical emergencies, severe distress, or explicit human requests — no confirmation needed; (2) office-specific questions you cannot answer, or billing disputes — but ONLY after asking 'Would you like me to connect you with a team member?' and the patient says yes. NEVER call this for general knowledge questions (medical info, health facts, world knowledge) — answer those directly using your training. NEVER call this on greetings or simple chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the call is being escalated.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_callback_request",
            "description": "Request that the office call the patient back.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["patient_name", "phone", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_office_info",
            "description": (
                "Get accurate office information. ALWAYS call this tool when the patient "
                "asks about: business hours, office location, phone number, services, pricing, "
                "procedure details, treatment duration, 'how long does X take?', or any factual "
                "question about the office. "
                "Do NOT answer from memory or general knowledge — always call this tool and "
                "read the exact answer from the result. Do not embellish or add information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": ["hours", "location", "services", "faqs", "all"],
                        "description": (
                            "What info to retrieve: "
                            "'hours' for business hours, "
                            "'location' for address/phone, "
                            "'services' for pricing and costs (use this for 'how much' or 'price of X'), "
                            "'faqs' for procedure questions like 'how long does X take', "
                            "'all' to get everything (use when unsure)."
                        ),
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_patient_appointments",
            "description": (
                "Look up a patient's upcoming appointments by their phone number. "
                "Use when a returning patient wants to reschedule, cancel, or check "
                "on an existing appointment. Returns appointment details including "
                "booking_uid needed for reschedule/cancel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Patient's phone number.",
                    },
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_waitlist",
            "description": "Add a patient to the waitlist when their preferred date/time has no available slots. The patient will be automatically notified by SMS if a slot opens up. CRITICAL: Reuse any patient_name, phone, appointment_type, and preferred_date you already learned in this conversation or from the CALLER INFORMATION section. Do NOT re-ask the patient for fields you already know — that's a failure mode. ALSO include preferred_time_start / preferred_time_end (24h HH:MM format) whenever the patient mentioned a time preference — admins rely on this to match slots and to contact the patient at the right time. If the patient asked for a specific doctor, pass that doctor's id as provider_id so the office can match them when the right doctor has an opening.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient's full name."},
                    "phone": {"type": "string", "description": "Patient's phone number."},
                    "appointment_type": {"type": "string", "description": "Type of appointment."},
                    "preferred_date": {"type": "string", "description": "Preferred date in YYYY-MM-DD format."},
                    "preferred_time_start": {
                        "type": "string",
                        "description": "Optional start of the patient's preferred time window in 24-hour HH:MM format (e.g. '09:00'). Pass this whenever the patient says they want morning/afternoon/evening or names a time.",
                    },
                    "preferred_time_end": {
                        "type": "string",
                        "description": "Optional end of the patient's preferred time window in 24-hour HH:MM format (e.g. '12:00').",
                    },
                    "provider_id": {
                        "type": "string",
                        "description": "Optional UUID of the doctor the patient asked for. Use the id from get_providers. Omit if the patient said 'anyone is fine'.",
                    },
                },
                "required": ["patient_name", "phone", "appointment_type", "preferred_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_providers",
            "description": "Get the list of available providers at this practice. Call this when a patient asks to see a specific provider or when you need to offer provider choices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_type": {
                        "type": "string",
                        "description": "Optional. Filter providers who handle this appointment type.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_patient",
            "description": (
                "Look up a patient's full CRM record — personal details, past appointments, "
                "and upcoming appointments. Use this when you need to verify or retrieve patient "
                "information mid-conversation (e.g. DOB, allergies, visit history). "
                "ALWAYS use the caller's phone number (from caller-ID in your system prompt) as the "
                "primary lookup key. Only use name as a last resort — multiple patients can share a name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Patient's phone number — ALWAYS provide this. You have it from caller-ID.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Patient's name. Only use as last resort if phone is truly unavailable. May return multiple matches.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_patient_info",
            "description": (
                "Update a patient's personal information in the CRM. Use when a patient "
                "provides new or corrected details during the conversation — for example, "
                "their date of birth, allergies, or notes. Use the caller's phone number "
                "from caller-ID (in your system prompt) to identify them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Patient's phone number (from caller-ID in your system prompt).",
                    },
                    "name": {
                        "type": "string",
                        "description": "Updated patient name (only if correcting).",
                    },
                    "dob": {
                        "type": "string",
                        "description": "Date of birth (MM/DD/YYYY).",
                    },
                    "email": {
                        "type": "string",
                        "description": "Patient's email address.",
                    },
                    "allergies": {
                        "type": "string",
                        "description": "Patient's allergies (comma-separated).",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Receptionist notes about the patient.",
                    },
                },
                "required": ["phone"],
            },
        },
    },
]

# Backwards-compat alias (llm_proxy.py imports this symbol)
TOOLS = ALL_TOOLS


# ── Tools that require specific integrations ──────────────────────────────────
# If the tenant hasn't configured the relevant service, these tools are hidden
# from the LLM so it can't accidentally trigger actions the tenant can't handle.

_TOOLS_REQUIRING_TWILIO = {"escalate_to_human", "send_callback_request"}
_TOOLS_REQUIRING_SCHEDULING = {
    "get_available_slots", "book_appointment", "reschedule_appointment", "cancel_appointment",
    "add_to_waitlist",
}


def get_tools(tenant_ctx: Any | None = None) -> list[dict]:
    """
    Return the tool definitions appropriate for `tenant_ctx`.

    • If tenant_ctx is None (legacy / global mode) → all tools.
    • Otherwise, hide tools whose backing integration isn't configured,
      and dynamically inject the tenant's appointment type enum.

    Calendar tools are available if the tenant has ANY of:
      - Google Calendar connected (OAuth refresh token), OR
      - Business hours configured (native scheduling via Postgres)
    """
    if tenant_ctx is None:
        return ALL_TOOLS

    has_twilio = bool(tenant_ctx.twilio_account_sid and tenant_ctx.twilio_auth_token)
    has_google_cal = bool(tenant_ctx.google_calendar_connected and tenant_ctx.google_calendar_refresh_token)
    has_native_scheduling = bool(tenant_ctx.business_hours)
    has_scheduling = has_google_cal or has_native_scheduling
    has_escalation = bool(tenant_ctx.emergency_guidance)

    # Build dynamic appointment type enum from tenant config
    appt_keys = None
    if tenant_ctx.appointment_types:
        appt_keys = [at.get("code", "consultation") for at in tenant_ctx.appointment_types]

    filtered = []
    for tool in ALL_TOOLS:
        import copy
        name = tool.get("function", {}).get("name") or ""
        if name in _TOOLS_REQUIRING_TWILIO and not has_twilio:
            continue
        if name in _TOOLS_REQUIRING_TWILIO and not has_escalation:
            continue
        if name in _TOOLS_REQUIRING_SCHEDULING and not has_scheduling:
            continue

        # Inject tenant-specific appointment type enum into relevant tools
        if appt_keys and name in ("get_available_slots", "book_appointment", "add_to_waitlist"):
            tool = copy.deepcopy(tool)
            props = tool["function"]["parameters"]["properties"]
            if "appointment_type" in props:
                props["appointment_type"]["enum"] = appt_keys
        filtered.append(tool)

    logger.info("[LLM] Tool filter: twilio=%s gcal=%s native_sched=%s escalation=%s → %d/%d tools available",
                has_twilio, has_google_cal, has_native_scheduling, has_escalation, len(filtered), len(ALL_TOOLS))
    return filtered


# ── Simple-chat detection (suppress tools for greetings / small talk) ─────────

def _looks_like_simple_chat(user_message: str, session_messages: list | None = None) -> bool:
    """
    Heuristic: when True, suppress tool definitions for this turn so the
    model replies conversationally instead of hallucinating a tool call on
    a bare 'hi' or 'how are you'.

    CRITICAL: Only applies to the FIRST user message in a conversation.
    Once a multi-turn flow is underway (e.g. booking), tools must ALWAYS
    be available — the user might respond with short answers like "doc1",
    "yes", "2pm", etc. that don't match any keyword but still need tools.
    """
    # If we're past the first exchange, NEVER suppress tools.
    # The user could be responding to a provider selection, time slot question, etc.
    if session_messages and len(session_messages) > 2:
        # More than system prompt + first user message → conversation in progress
        return False

    text = user_message.strip().lower()
    if not text or len(text) > 80:
        return False
    tool_keywords = [
        # Scheduling
        "book", "schedule", "appointment", "slot", "available", "availability",
        "reschedule", "cancel", "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday", "tomorrow", "today", "next week",
        "this week", "morning", "afternoon", "evening", "am", "pm",
        ":", "o'clock", "9", "10", "11", "12", "1pm", "2pm", "3pm", "4pm", "5pm",
        # Emergency / escalation
        "emergency", "urgent", "pain", "broken", "knocked",
        "human", "person", "transfer", "callback", "call back",
        # Office info (triggers get_office_info tool)
        "hour", "hours", "open", "close", "location", "address", "where",
        "phone", "number", "service", "pricing",
        "price", "cost", "how much", "faq", "question",
        "do you", "can you", "what do", "offer",
        # Procedure/treatment questions (trigger FAQ lookup)
        "how long", "procedure", "treatment", "duration", "take",
        "rct", "root canal", "filling", "crown", "extraction", "cleaning",
        # Patient lookup / CRM
        "my appointment", "existing", "upcoming", "check on",
        "do i have", "any appointment", "look up", "find my",
        "my record", "my info", "my details", "date of birth", "dob",
        "allergies", "allergy", "update my",
    ]
    return not any(kw in text for kw in tool_keywords)


# ── Session management ────────────────────────────────────────────────────────


def create_session(
    call_id: str,
    caller_number: str = "",
    tenant_ctx: Any | None = None,
    patient_context: dict | None = None,
) -> dict[str, Any]:
    """Initialise a new conversation session for a call.

    If ``patient_context`` is supplied (from patient_service.get_patient_history),
    it is woven into the system prompt so the agent recognises returning callers,
    greets them by name, and already knows their upcoming appointments.
    """
    session = {
        "messages": [
            {
                "role": "system",
                "content": build_system_prompt(
                    patient_context=patient_context,
                    tenant_ctx=tenant_ctx,
                    caller_phone=caller_number,
                ),
            }
        ],
        "patient_info": patient_context.get("patient", {}) if patient_context else {},
        "current_state": "greeting",
        "call_start_time": time.time(),
        "caller_number": caller_number,
        "tenant_ctx": tenant_ctx,  # stored so _execute_tool can use it
    }
    # Housekeeping: clean up any abandoned sessions before adding a new one.
    # Cheap check — only runs the sweep when session count grows beyond 50.
    if len(sessions) > 50:
        _cleanup_stale_sessions()

    sessions[call_id] = session
    logger.info("Session created for call %s (tenant=%s, patient=%s, active=%d)",
                call_id,
                tenant_ctx.slug if tenant_ctx else "global",
                patient_context["patient"]["name"] if patient_context else "new caller",
                len(sessions))
    return session


def get_session(call_id: str) -> dict[str, Any] | None:
    return sessions.get(call_id)


def end_session(call_id: str) -> dict[str, Any] | None:
    """Remove and return the session for final persistence."""
    session = sessions.pop(call_id, None)
    if session:
        logger.info("Session ended for call %s (duration %.0fs).",
                     call_id, time.time() - session["call_start_time"])
    return session


# ── Gemini helpers (format conversion) ──────────────────────────────────────


def _extract_gemini_text(response) -> str:
    """Extract only the spoken-text parts from a Gemini response,
    skipping 'thought' parts that contain chain-of-thought reasoning."""
    try:
        parts = response.candidates[0].content.parts
    except (IndexError, AttributeError):
        return ""

    text_parts = []
    for part in parts:
        # Skip thought/thinking parts (Gemma thinking_config)
        if hasattr(part, "thought") and part.thought:
            continue
        # Skip function calls
        if part.function_call and part.function_call.name:
            continue
        # Collect actual text
        if hasattr(part, "text") and part.text:
            text_parts.append(part.text)

    return "".join(text_parts).strip()


def _openai_tools_to_gemini(tools: list[dict]) -> list | None:
    """
    Convert OpenAI tool format to google-genai FunctionDeclaration objects.

    OpenAI: {"type": "function", "function": {"name": "...", "parameters": {...}}}
    google-genai: types.Tool(function_declarations=[types.FunctionDeclaration(...)])

    The new SDK accepts raw JSON Schema via `parameters_json_schema` so we
    don't need to convert types to uppercase enums.
    """
    function_declarations = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            params = func.get("parameters", {})

            function_declarations.append(
                gtypes.FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters_json_schema=params,
                )
            )

    if not function_declarations:
        return None
    return [gtypes.Tool(function_declarations=function_declarations)]


# ── Core LLM conversation ────────────────────────────────────────────────────


async def process_message(
    call_id: str,
    user_message: str,
    tenant_ctx: Any | None = None,
    caller_number: str = "",
) -> str:
    """
    Process an inbound user message and return the agent's response.
    Handles tool calls internally (two-step pattern).

    Args:
        tenant_ctx: If provided, tool definitions are filtered by tenant
            capabilities and all service calls use the tenant's credentials.
        caller_number: Caller phone number for system prompt injection.
    """
    # Route based on LLM provider
    if settings.LLM_PROVIDER == "gemini":
        return await _process_message_gemini(call_id, user_message, tenant_ctx, caller_number)
    else:
        return await _process_message_ollama(call_id, user_message, tenant_ctx, caller_number)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect a rate-limit (429) error from any of the google-genai error paths."""
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        name in ("ResourceExhausted", "ClientError", "APIError")
        and ("429" in msg or "resource_exhausted" in msg or "rate" in msg or "quota" in msg)
    )


async def _gemini_send_with_retry(chat, content):
    """Send a message via async chat with retry on rate-limit (429) errors."""
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            return await chat.send_message(content)
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < MAX_RETRIES - 1:
                wait = min(15 * (2 ** attempt), 60)
                logger.warning(
                    "Gemini rate limited — retrying in %.0fs (attempt %d/%d): %s",
                    wait, attempt + 1, MAX_RETRIES, exc,
                )
                await asyncio.sleep(wait)
                continue
            raise


async def _process_message_gemini(
    call_id: str,
    user_message: str,
    tenant_ctx: Any | None = None,
    caller_number: str = "",
) -> str:
    """
    Gemini implementation with function calling support (google-genai SDK).
    Uses ThinkingLevel.MINIMAL to disable Gemma's chain-of-thought output.
    NOTE: For MVP/testing with fake data ONLY — not HIPAA-compliant.
    """
    session = get_session(call_id)
    if session is None:
        session = create_session(call_id, caller_number=caller_number, tenant_ctx=tenant_ctx)
    if tenant_ctx and not session.get("tenant_ctx"):
        session["tenant_ctx"] = tenant_ctx

    effective_ctx = session.get("tenant_ctx")

    # Refresh the time in the system prompt so "what time is it?" is accurate.
    _refresh_system_time(session)

    session["messages"].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    logger.info("[Call %s] Processing (Gemini) user message (%d chars)", call_id, len(user_message))

    try:
        t0 = time.time()

        # Simple chat detection (same as Ollama)
        suppress_tools = _looks_like_simple_chat(user_message, session["messages"])
        tools_for_request = None if suppress_tools else get_tools(effective_ctx)
        if suppress_tools:
            logger.info("[Call %s] Simple chat detected — suppressing tools (Gemini)", call_id)

        # Extract system prompt and build Gemini history (including tool calls).
        # google-genai uses types.Content / types.Part objects.
        history: list[gtypes.Content] = []
        system_prompt = ""
        all_msgs = session["messages"]
        for i, msg in enumerate(all_msgs):
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                if msg["content"] != user_message:  # Skip the current message
                    history.append(gtypes.Content(
                        role="user",
                        parts=[gtypes.Part(text=msg["content"])],
                    ))
            elif msg["role"] == "assistant":
                if msg.get("tool_calls"):
                    parts = []
                    for tc in msg["tool_calls"]:
                        try:
                            args = json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"]
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        parts.append(gtypes.Part(
                            function_call=gtypes.FunctionCall(name=tc["name"], args=args),
                        ))
                    history.append(gtypes.Content(role="model", parts=parts))
                elif msg.get("content"):
                    history.append(gtypes.Content(
                        role="model",
                        parts=[gtypes.Part(text=msg["content"])],
                    ))
            elif msg["role"] == "tool":
                try:
                    result = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                except (json.JSONDecodeError, TypeError):
                    result = {"result": msg.get("content", "")}
                if not isinstance(result, dict):
                    result = {"result": result}
                tool_name = "unknown"
                if i > 0 and all_msgs[i - 1].get("tool_calls"):
                    tool_name = all_msgs[i - 1]["tool_calls"][0]["name"]
                history.append(gtypes.Content(
                    role="user",
                    parts=[gtypes.Part(
                        function_response=gtypes.FunctionResponse(name=tool_name, response=result),
                    )],
                ))

        # Trim history before sending so long calls don't keep growing the
        # per-request token count. Full transcript is still saved in
        # session["messages"] — only the *forwarded* history is trimmed.
        history = _trim_gemini_history(
            history,
            max_messages=settings.GEMINI_HISTORY_MAX_MESSAGES,
        )

        # Build config with ThinkingLevel.MINIMAL — disables CoT output for Gemma 4.
        gemini_tools = _openai_tools_to_gemini(tools_for_request) if tools_for_request else None

        # Optionally use an explicit context cache for the system prompt + tools.
        # This is a per-tenant cache that's lazily created and reused for an
        # hour, cutting per-call cost ~75% on the cached prefix. If caching
        # isn't supported (or fails) we silently fall back to inline send.
        cached_name = await _get_or_create_gemini_cache(
            system_prompt=system_prompt,
            tools=gemini_tools,
            tenant_ctx=effective_ctx,
        )
        if cached_name:
            config = _build_gemini_config(cached_content=cached_name)
        else:
            config = _build_gemini_config(
                system_instruction=system_prompt,
                tools=gemini_tools,
            )

        # Create async chat
        client = _get_gemini_client()
        chat = client.aio.chats.create(
            model=settings.GEMINI_MODEL,
            config=config,
            history=history,
        )

        response = await _gemini_send_with_retry(chat, user_message)

        llm_time = (time.time() - t0) * 1000
        logger.info("[Call %s] Gemini responded in %.0fms", call_id, llm_time)

        # Handle function calls
        MAX_TOOL_ROUNDS = 5
        reply = ""

        for tool_round in range(MAX_TOOL_ROUNDS):
            if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                logger.warning("[Call %s] Gemini returned empty response (possibly blocked by safety filters)", call_id)
                reply = "I'm sorry, I wasn't able to process that. Could you rephrase your question?"
                break

            # Find a function_call part (skipping thought parts)
            fc_part = None
            for part in response.candidates[0].content.parts:
                if getattr(part, "thought", False):
                    continue
                if part.function_call and part.function_call.name:
                    fc_part = part
                    break

            if fc_part:
                fn_name = fc_part.function_call.name
                fn_args = dict(fc_part.function_call.args) if fc_part.function_call.args else {}

                logger.info("[Call %s] Gemini function call: %s(%s)", call_id, fn_name, fn_args)

                tool_result = await _execute_tool(call_id, fn_name, fn_args, tenant_ctx=effective_ctx)
                logger.info("[Call %s] Tool result: %s", call_id, json.dumps(tool_result, default=str)[:500])

                # Ensure tool_result is a dict (FunctionResponse.response expects a dict)
                if not isinstance(tool_result, dict):
                    tool_result = {"result": tool_result}

                # Send the function response back
                response = await _gemini_send_with_retry(
                    chat,
                    gtypes.Part(
                        function_response=gtypes.FunctionResponse(
                            name=fn_name, response=tool_result,
                        ),
                    ),
                )

                session["messages"].append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"name": fn_name, "arguments": json.dumps(fn_args)}],
                })
                session["messages"].append({
                    "role": "tool",
                    "content": json.dumps(tool_result),
                })
            else:
                reply = _extract_gemini_text(response)
                break
        else:
            reply = _extract_gemini_text(response) or "I apologize, I'm having difficulty. Could you repeat that?"
            logger.warning("[Call %s] Exceeded %d tool rounds (Gemini)", call_id, MAX_TOOL_ROUNDS)

        if not reply:
            reply = "I'm sorry, could you say that again?"

        # Save reply
        session["messages"].append({
            "role": "assistant",
            "content": reply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        total_time = (time.time() - t0) * 1000
        logger.info("[Call %s] Gemini final reply (%.0fms): %s", call_id, total_time, reply[:200])
        return reply

    except Exception as exc:
        logger.error("Gemini processing error for call %s: %s", call_id, exc, exc_info=True)
        return (
            "I apologize, I'm having a brief technical difficulty. "
            "Could you repeat that? Or I can connect you with a team member."
        )


async def _process_message_ollama(
    call_id: str,
    user_message: str,
    tenant_ctx: Any | None = None,
    caller_number: str = "",
) -> str:
    """Ollama/OpenAI implementation (original code)."""
    session = get_session(call_id)
    if session is None:
        session = create_session(call_id, caller_number=caller_number, tenant_ctx=tenant_ctx)
    # Ensure tenant_ctx is stored (e.g. if session was pre-created without it)
    if tenant_ctx and not session.get("tenant_ctx"):
        session["tenant_ctx"] = tenant_ctx

    # Use session's tenant_ctx for consistency within the conversation
    effective_ctx = session.get("tenant_ctx")

    # Refresh the time in the system prompt so "what time is it?" is accurate.
    _refresh_system_time(session)

    # Append user turn
    session["messages"].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    msg_count = len(session["messages"])
    logger.info("[Call %s] Processing user message (%d chars, %d messages in history)",
                call_id, len(user_message), msg_count)
    logger.debug("[Call %s] User said: %s", call_id, user_message[:200])

    try:
        client = _get_client()

        # ── Step 1: LLM call (may request a tool) ────────────────────────
        logger.info("[Call %s] Sending to Ollama (model: %s, %d messages)...",
                    call_id, settings.OLLAMA_MODEL, msg_count)
        t0 = time.time()

        # Suppress tools on greetings / small talk to prevent hallucinated
        # tool calls (e.g. escalate_to_human on "hi").
        # Only applies to the first message — mid-conversation always gets tools.
        suppress_tools = _looks_like_simple_chat(user_message, session["messages"])
        tools_for_request = None if suppress_tools else get_tools(effective_ctx)
        if suppress_tools:
            logger.info("[Call %s] Simple chat detected — suppressing tools", call_id)

        kwargs: dict[str, Any] = {
            "model": settings.OLLAMA_MODEL,
            "messages": _strip_timestamps(session["messages"]),
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        if tools_for_request:
            kwargs["tools"] = tools_for_request

        response = client.chat.completions.create(**kwargs)

        llm_time = (time.time() - t0) * 1000
        choice = response.choices[0]
        assistant_msg = choice.message
        finish_reason = choice.finish_reason

        logger.info("[Call %s] Ollama responded in %.0fms (finish_reason=%s, tool_calls=%s)",
                    call_id, llm_time, finish_reason,
                    bool(assistant_msg.tool_calls))

        # ── Step 2: Tool call loop (up to MAX_TOOL_ROUNDS) ────────────────
        MAX_TOOL_ROUNDS = 5
        current_msg = assistant_msg
        reply = ""

        for tool_round in range(MAX_TOOL_ROUNDS):
            if not current_msg.tool_calls:
                reply = current_msg.content or ""
                break

            # Execute ALL tool calls in this round
            for tool_call in current_msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                logger.info("[Call %s] Tool call (round %d): %s(%s)",
                            call_id, tool_round + 1, fn_name, fn_args)

                tool_result = await _execute_tool(call_id, fn_name, fn_args, tenant_ctx=effective_ctx)

                logger.info("=" * 60)
                logger.info("[Call %s] TOOL RESULT for %s:", call_id, fn_name)
                logger.info("[Call %s]   %s", call_id, json.dumps(tool_result, default=str)[:1000])
                logger.info("=" * 60)

                session["messages"].append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {"name": fn_name, "arguments": tool_call.function.arguments},
                        }
                    ],
                })
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result),
                })

            # Call LLM again with tool results — may trigger another tool or produce text
            logger.info("[Call %s] Generating follow-up (round %d)...", call_id, tool_round + 1)
            t1 = time.time()

            followup_kwargs: dict[str, Any] = {
                "model": settings.OLLAMA_MODEL,
                "messages": _strip_timestamps(session["messages"]),
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            # Include tools so the LLM can chain (e.g. get_slots → book)
            if tools_for_request:
                followup_kwargs["tools"] = tools_for_request

            followup = client.chat.completions.create(**followup_kwargs)
            followup_time = (time.time() - t1) * 1000
            current_msg = followup.choices[0].message
            logger.info("[Call %s] Follow-up round %d in %.0fms (tool_calls=%s, content=%d chars)",
                        call_id, tool_round + 1, followup_time,
                        bool(current_msg.tool_calls), len(current_msg.content or ""))

            if not current_msg.tool_calls:
                reply = current_msg.content or ""
                break
        else:
            # Exceeded max rounds — use whatever content we have
            reply = current_msg.content or "I apologize, I'm having difficulty. Could you repeat that?"
            logger.warning("[Call %s] Exceeded %d tool rounds", call_id, MAX_TOOL_ROUNDS)

        # ── Strip Qwen3 thinking blocks if /no_think is partially honored ───
        if "<think>" in reply:
            reply = _re.sub(r"<think>.*?</think>\s*", "", reply, flags=_re.DOTALL).strip()
            logger.info("[Call %s] Stripped <think> block, post-strip=%d chars", call_id, len(reply))

        # Save assistant reply
        session["messages"].append({
            "role": "assistant",
            "content": reply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        total_time = (time.time() - t0) * 1000
        logger.info("=" * 60)
        logger.info("[Call %s] FINAL LLM REPLY (%0.fms total):", call_id, total_time)
        # Log full reply in chunks to avoid truncation
        for i in range(0, max(len(reply), 1), 500):
            logger.info("[Call %s]   >>> %s", call_id, reply[i:i+500])
        logger.info("=" * 60)
        return reply

    except Exception as exc:
        logger.error("LLM processing error for call %s: %s", call_id, exc, exc_info=True)
        return (
            "I apologize, I'm having a brief technical difficulty. "
            "Could you repeat that? Or I can connect you with a team member."
        )


# ── Streaming variant ─────────────────────────────────────────────────────────


async def process_message_stream(
    call_id: str,
    user_message: str,
    tenant_ctx: Any | None = None,
    caller_number: str = "",
):
    """
    Async generator version of process_message(). Yields content tokens as
    they stream from Ollama — the caller sees the first token in ~200-500ms
    instead of waiting 3-10s for the full response.

    Tool calls are handled internally: when the LLM requests a tool, token
    streaming pauses while the tool executes, then the follow-up response
    streams token-by-token.

    Yields: str (content token fragments)

    NOTE: Gemini streaming not yet implemented — falls back to non-streaming
    for Gemini provider.
    """
    # Gemini: non-streaming API, then simulate token-by-token delivery
    if settings.LLM_PROVIDER == "gemini":
        reply = await process_message(call_id, user_message, tenant_ctx, caller_number)
        # Yield word-by-word with tiny async pauses so the event loop
        # actually flushes each SSE chunk to the browser
        words = reply.split(" ")
        for i, word in enumerate(words):
            yield word if i == 0 else " " + word
            await asyncio.sleep(0.03)  # 30ms per word ≈ natural reading speed
        return

    session = get_session(call_id)
    if session is None:
        session = create_session(call_id, caller_number=caller_number, tenant_ctx=tenant_ctx)
    if tenant_ctx and not session.get("tenant_ctx"):
        session["tenant_ctx"] = tenant_ctx

    effective_ctx = session.get("tenant_ctx")

    session["messages"].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    msg_count = len(session["messages"])
    logger.info("[Call %s] Streaming user message (%d chars, %d msgs)",
                call_id, len(user_message), msg_count)

    try:
        client = _get_async_client()

        suppress_tools = _looks_like_simple_chat(user_message, session["messages"])
        tools_for_request = None if suppress_tools else get_tools(effective_ctx)
        if suppress_tools:
            logger.info("[Call %s] Simple chat — suppressing tools for stream", call_id)

        full_reply = ""
        t0 = time.time()

        for tool_round in range(5):  # MAX_TOOL_ROUNDS
            kwargs: dict[str, Any] = {
                "model": settings.OLLAMA_MODEL,
                "messages": _strip_timestamps(session["messages"]),
                "temperature": 0.7,
                "max_tokens": 1024,
                "stream": True,
            }
            if tools_for_request:
                kwargs["tools"] = tools_for_request

            t_round = time.time()
            stream = await client.chat.completions.create(**kwargs)

            round_content = ""
            tool_calls_acc: dict[int, dict] = {}

            # <think> block suppression — buffer initial tokens to detect
            # Qwen3 reasoning blocks, then flush once we know the real
            # content is starting.
            buf = ""
            flushing = False

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta

                # Accumulate streamed tool-call fragments
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if getattr(tc.function, "name", None):
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if getattr(tc.function, "arguments", None):
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

                token = delta.content or ""
                if not token:
                    continue

                round_content += token

                # ── Smart buffer: suppresses <think> and <tool_call> blocks ──
                # Even when flushing, re-enter buffering if a `<` appears
                # (could be the start of a tool/think tag).
                if flushing:
                    if "<" in token:
                        # Might be start of a tag — buffer it instead of yielding
                        buf = token
                        flushing = False
                    else:
                        yield token
                        full_reply += token
                        continue
                else:
                    buf += token

                if "<think>" in buf:
                    # Still in think block — wait for closing tag
                    if "</think>" in buf:
                        after = buf.split("</think>", 1)[1].lstrip()
                        if after:
                            yield after
                            full_reply += after
                        buf = ""
                        flushing = True
                elif _has_tool_tag_start(buf):
                    # Tool call text detected — do NOT yield to user.
                    # Wait for closing tag, then strip it.
                    if _has_tool_tag_end(buf):
                        before, after = _strip_tool_block(buf)
                        if before.strip():
                            yield before
                            full_reply += before
                        buf = after.lstrip() if after else ""
                        if not buf:
                            flushing = True
                    # else: keep buffering until closing tag arrives
                elif len(buf) > 50:
                    # No tags found — safe to flush. Use 50 chars to ensure
                    # full tag names (e.g. "<tool_call>") can be detected.
                    yield buf
                    full_reply += buf
                    buf = ""
                    flushing = True

            # Flush remaining buffer
            if buf:
                clean = buf
                # Strip think blocks
                if "<think>" in clean:
                    clean = _re.sub(r"<think>.*?</think>\s*", "", clean, flags=_re.DOTALL).strip()
                # Strip tool call blocks
                if _has_tool_tag_start(clean) and _has_tool_tag_end(clean):
                    before, _ = _strip_tool_block(clean)
                    clean = before.strip()
                elif _has_tool_tag_start(clean):
                    # Incomplete tool tag — strip from tag start onwards
                    for start_tag, _ in _TOOL_TAG_PATTERNS:
                        if start_tag in clean:
                            clean = clean.split(start_tag, 1)[0].strip()
                            break
                if clean:
                    yield clean
                    full_reply += clean

            # ── Detect text-based tool calls (Qwen3 quirk) ────────────
            # Sometimes models output <tool_call>...</tool_call> as text
            # instead of using the proper function calling API.
            if not tool_calls_acc and _has_tool_tag_start(round_content) and _has_tool_tag_end(round_content):
                parsed = _parse_tool_call_text(round_content)
                if parsed:
                    logger.warning("[Call %s] ⚠️ Text-based tool call detected: %s — executing",
                                   call_id, parsed["name"])
                    tool_calls_acc[0] = {
                        "id": f"text_tc_{tool_round}",
                        "name": parsed["name"],
                        "arguments": json.dumps(parsed["arguments"]),
                    }

            round_ms = (time.time() - t_round) * 1000
            logger.info("[Call %s] Stream round %d: %.0fms, content=%d chars, tools=%d",
                        call_id, tool_round + 1, round_ms,
                        len(round_content), len(tool_calls_acc))

            if not tool_calls_acc:
                break  # Pure text response — done

            # ── Execute tool calls, add results to session ──────────
            for idx in sorted(tool_calls_acc.keys()):
                tc_info = tool_calls_acc[idx]
                fn_name = tc_info["name"]
                try:
                    fn_args = json.loads(tc_info["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                logger.info("[Call %s] Stream tool (round %d): %s(%s)",
                            call_id, tool_round + 1, fn_name, fn_args)

                tool_result = await _execute_tool(
                    call_id, fn_name, fn_args, tenant_ctx=effective_ctx,
                )
                logger.info("[Call %s] Stream tool result: %s",
                            call_id, json.dumps(tool_result, default=str)[:500])

                session["messages"].append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc_info["id"],
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": tc_info["arguments"],
                        },
                    }],
                })
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc_info["id"],
                    "content": json.dumps(tool_result, default=str),
                })

        # Save complete reply to session history
        # Handle empty response from LLM (timeout, context overflow, etc.)
        if not full_reply:
            fallback = (
                "I apologize, I didn't catch that. Could you please repeat your request? "
                "I'm here to help with scheduling appointments."
            )
            logger.warning("[Call %s] LLM returned empty response after %.0fms — sending fallback",
                          call_id, (time.time() - t0) * 1000)
            yield fallback
            full_reply = fallback

        if full_reply:
            session["messages"].append({
                "role": "assistant",
                "content": full_reply,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        total_ms = (time.time() - t0) * 1000
        logger.info("[Call %s] Stream complete: %d chars in %.0fms",
                    call_id, len(full_reply), total_ms)

    except Exception as exc:
        logger.error("LLM streaming error for call %s: %s", call_id, exc, exc_info=True)
        yield (
            "I apologize, I'm having a brief technical difficulty. "
            "Could you repeat that? Or I can connect you with a team member."
        )


# ── Tool execution ────────────────────────────────────────────────────────────


async def _execute_tool(
    call_id: str,
    name: str,
    args: dict,
    tenant_ctx: Any | None = None,
) -> dict[str, Any]:
    """Route a tool call to the appropriate service and return a result dict.

    Args:
        tenant_ctx: When set, all downstream service calls (calendar, SMS) use
            the tenant's own credentials. When None, falls back to global .env
            settings (legacy single-tenant mode).
    """
    session = get_session(call_id)
    logger.info("[Call %s] Executing tool: %s with args: %s (tenant=%s)",
                call_id, name, json.dumps(args)[:300],
                tenant_ctx.slug if tenant_ctx else "global")
    t0 = time.time()

    try:
        if name == "get_available_slots":
            appt_type = args.get("appointment_type", "consultation")
            provider_id_str = args.get("provider_id", "")

            date = args.get("date", "")
            if not date:
                from datetime import timedelta
                date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            # ── Date correction: resolve user's day-of-week to actual date ──
            if session:
                user_text = ""
                for m in reversed(session["messages"]):
                    if m.get("role") == "user":
                        user_text = (m.get("content") or "").strip().lower()
                        break
                if user_text:
                    resolved = _resolve_dow_to_date(user_text, tenant_ctx)
                    if resolved and resolved != date:
                        logger.warning("[Call %s] Date correction: LLM said %r → user implied %r",
                                       call_id, date, resolved)
                        date = resolved

            # ── Past-date guard: never run scheduling for a date that has
            #    already passed. The LLM sometimes obeys a literal user
            #    request ("book for 26th May") without noticing today is the
            #    27th. We refuse here so the agent doesn't loop into a
            #    "no slots → waitlist" suggestion for an impossible date.
            try:
                from datetime import date as _date_cls
                from zoneinfo import ZoneInfo as _ZI
                _tz_name = (tenant_ctx.timezone if tenant_ctx and getattr(tenant_ctx, "timezone", None) else "America/Chicago")
                try:
                    _tz = _ZI(_tz_name)
                except Exception:
                    _tz = _ZI("America/Chicago")
                _today_local = datetime.now(_tz).date()
                _req_date = datetime.strptime(date, "%Y-%m-%d").date()
                if _req_date < _today_local:
                    friendly = _req_date.strftime("%A, %B %d")
                    logger.warning("[Call %s] get_available_slots refused — past date %s (today=%s)",
                                   call_id, date, _today_local.isoformat())
                    return {
                        "ok": False,
                        "error": "past_date",
                        "date": date,
                        "today": _today_local.isoformat(),
                        "summary_for_assistant": (
                            f"That date ({friendly}) has already passed — today is "
                            f"{_today_local.strftime('%A, %B %d, %Y')}. Politely let the patient know "
                            f"that date is in the past and ask which upcoming day they'd like instead. "
                            f"Do NOT offer the waitlist for a past date. Do NOT call add_to_waitlist."
                        ),
                        "available_slots": [],
                        "count": 0,
                    }
            except (ValueError, TypeError):
                # If date parsing fails, fall through — downstream will handle it.
                pass

            # ── Get provider-aware slots ──────────────────────────────────
            from backend.services import native_scheduling
            import uuid as uuid_mod

            provider_uuid = None
            if provider_id_str:
                try:
                    provider_uuid = uuid_mod.UUID(provider_id_str)
                except (ValueError, TypeError):
                    pass

            # Get duration from appointment config
            duration = 60
            if tenant_ctx and tenant_ctx.appointment_types:
                for at in tenant_ctx.appointment_types:
                    if at.get("code") == appt_type:
                        duration = at.get("duration_minutes", 60)
                        break

            # Use provider-aware scheduling to check per-provider concurrency
            provider_slots_result = await native_scheduling.get_provider_aware_slots(
                date_str=date,
                duration_minutes=duration,
                tenant_id=tenant_ctx.tenant_id if tenant_ctx else None,
                business_hours=tenant_ctx.business_hours if tenant_ctx else None,
                tz_name=tenant_ctx.timezone if tenant_ctx else "America/Chicago",
                provider_id=provider_uuid,
                holidays=(tenant_ctx.holidays if tenant_ctx and getattr(tenant_ctx, "holidays", None) else None),
            )

            # ── Holiday short-circuit ─────────────────────────────────────
            #    If the requested date is a configured tenant holiday, the
            #    slot generator returns {"holiday": {...}} with empty slots.
            #    Tell the LLM exactly why so it can communicate the closure
            #    by name (and refuse waitlist).
            holiday_info = provider_slots_result.get("holiday")
            if holiday_info:
                try:
                    from dateutil import parser as dt_parser
                    _friendly = dt_parser.parse(date).strftime("%A, %B %d")
                except Exception:
                    _friendly = date
                holiday_name = holiday_info.get("name") or "a holiday"
                logger.info("[Call %s] get_available_slots refused — %s is a holiday (%s) for tenant",
                            call_id, date, holiday_name)
                return {
                    "ok": False,
                    "error": "holiday",
                    "date": date,
                    "holiday": holiday_info,
                    "summary_for_assistant": (
                        f"The office is CLOSED on {_friendly} for {holiday_name}. "
                        f"Tell the patient we're closed that day for {holiday_name} and "
                        f"ask which other day works. Do NOT offer the waitlist for a holiday. "
                        f"Do NOT call add_to_waitlist for this date."
                    ),
                    "available_slots": [],
                    "count": 0,
                }

            provider_slots = provider_slots_result.get("slots", [])

            # Format slots with human-readable time labels and provider info
            formatted_slots = []
            for slot_data in provider_slots:
                slot_time = slot_data.get("time", "")
                available_provs = slot_data.get("available_providers", [])
                try:
                    from dateutil import parser as dt_parser
                    dt = dt_parser.parse(slot_time)
                    formatted_slots.append({
                        "time_label": dt.strftime("%I:%M %p").lstrip("0"),
                        "exact_slot_time": slot_time,
                        "available_providers": available_provs,
                    })
                except Exception:
                    formatted_slots.append({
                        "time_label": slot_time,
                        "exact_slot_time": slot_time,
                        "available_providers": available_provs,
                    })

            # Build friendly date and summary for the LLM
            try:
                from dateutil import parser as dt_parser
                friendly_date = dt_parser.parse(date).strftime("%A, %B %d")
            except Exception:
                friendly_date = date

            if not formatted_slots:
                # Check if there are ANY providers with capacity at different times
                summary = (
                    f"There are no available appointment slots on {friendly_date}. "
                    f"Tell the patient politely that day is fully booked or closed, "
                    f"and offer to check a different day. Do NOT read this message verbatim — "
                    f"speak naturally in 1-2 sentences."
                )
            else:
                top = formatted_slots[:3]
                time_list = ", ".join(s["time_label"] for s in top)

                # Check if specific provider was requested but has no availability
                if provider_id_str:
                    # Find slots where the requested provider is available
                    provider_available_slots = [
                        s for s in formatted_slots
                        if any(p["id"] == provider_id_str for p in s.get("available_providers", []))
                    ]
                    if not provider_available_slots and formatted_slots:
                        # Requested provider is full, but others are available
                        other_providers = set()
                        for s in formatted_slots[:5]:
                            for p in s.get("available_providers", []):
                                other_providers.add(p["name"])
                        other_names = ", ".join(list(other_providers)[:2])
                        summary = (
                            f"The requested provider is fully booked on {friendly_date}, "
                            f"but {other_names} {'has' if len(other_providers) == 1 else 'have'} availability. "
                            f"Ask the patient if they'd like to see another provider instead. "
                            f"Available times: {time_list}."
                        )
                    else:
                        summary = (
                            f"Available times on {friendly_date}: {time_list}. "
                            f"Offer these to the patient in natural conversation (1-2 sentences). "
                            f"When they pick one, call book_appointment with the matching exact_slot_time and provider_id. "
                            f"Do NOT read JSON or field names aloud."
                        )
                else:
                    summary = (
                        f"Available times on {friendly_date}: {time_list}. "
                        f"Offer these to the patient in natural conversation (1-2 sentences). "
                        f"When they pick one, call book_appointment with the matching exact_slot_time. "
                        f"Include provider_id if the patient chose a specific provider. "
                        f"Do NOT read JSON or field names aloud."
                    )

            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] get_available_slots → %d slots in %.0fms (provider=%s)",
                        call_id, len(formatted_slots), elapsed, provider_id_str or "any")
            return {
                "summary_for_assistant": summary,
                "available_slots": formatted_slots,
                "date": date,
                "count": len(formatted_slots),
                "provider_filter": provider_id_str or None,
            }

        elif name == "book_appointment":
            # ── Validate provider_id is present ──────────────────────
            if not args.get("provider_id", "").strip():
                logger.warning("[Call %s] book_appointment rejected — no provider_id", call_id)
                return {
                    "ok": False,
                    "error": "missing_provider",
                    "summary_for_assistant": (
                        "Provider is required — please ask the patient for their provider "
                        "preference first, or assign any available provider."
                    ),
                }

            # ── Validate required fields ──────────────────────────────
            required = {
                "patient_name": "the patient's full name",
                "phone": "the patient's phone number",
                "dob": "the patient's date of birth",
                "slot_time": "a confirmed appointment time (call get_available_slots first)",
                "appointment_type": "the appointment type",
            }
            missing = []
            for field, desc in required.items():
                val = args.get(field, "")
                if not val or not str(val).strip():
                    missing.append((field, desc))

            if missing:
                missing_list = "; ".join(f"{f} ({d})" for f, d in missing)
                logger.warning("[Call %s] book_appointment rejected — missing: %s",
                               call_id, [f for f, _ in missing])
                return {
                    "ok": False,
                    "error": "missing_required_fields",
                    "missing": [f for f, _ in missing],
                    "summary_for_assistant": (
                        f"Cannot book yet — missing: {missing_list}. "
                        f"Ask the patient ONLY for the missing items above in a natural sentence."
                    ),
                }

            appt_type = args.get("appointment_type", "consultation")

            # Email: leave blank if patient didn't provide one
            email = args.get("email", "") or ""

            # Provider: look up name for confirmation message
            provider_id_str = args.get("provider_id", "")
            provider_id = None
            provider_name = None
            if provider_id_str:
                try:
                    from backend.services import provider_service
                    import uuid
                    provider_id = uuid.UUID(provider_id_str)
                    provider = await provider_service.get_provider(provider_id)
                    if provider:
                        provider_name = provider.get("name", "")
                        logger.info("[Call %s] Provider selected: %s (%s)", call_id, provider_name, provider_id)
                except Exception as prov_exc:
                    logger.warning("[Call %s] Provider lookup failed: %s", call_id, prov_exc)

            patient_info = {
                "name": args.get("patient_name", ""),
                "phone": args.get("phone", ""),
                "email": email,
                "dob": args.get("dob", ""),
            }
            # Store patient info in session for later DB persistence
            if session:
                session["patient_info"] = patient_info

            slot_time = args.get("slot_time", "")

            # ── Smart slot matching ──────────────────────────────────
            # The LLM may pass slot_time in a slightly different format
            # than what the calendar API returned. Re-fetch available
            # slots for that day and match by hour/minute.
            logger.info("[Call %s] LLM provided slot_time: '%s' — attempting smart match",
                        call_id, slot_time)
            try:
                from dateutil import parser as dt_parser
                requested_dt = dt_parser.parse(slot_time)
                target_hour = requested_dt.hour
                target_minute = requested_dt.minute
                correct_date = requested_dt.replace(year=datetime.now().year)
                date_str = correct_date.strftime("%Y-%m-%d")

                available = await calendar_service.get_available_slots(
                    date_from=date_str,
                    date_to=date_str,
                    tenant_ctx=tenant_ctx,
                    appointment_type_key=appt_type,
                )

                matched = False
                for real_slot in available:
                    slot_dt = dt_parser.parse(real_slot)
                    if slot_dt.hour == target_hour and slot_dt.minute == target_minute:
                        slot_time = real_slot
                        matched = True
                        logger.info("[Call %s] Exact slot match: %s", call_id, slot_time)
                        break

                if not matched:
                    # Fallback: match by hour only
                    for real_slot in available:
                        slot_dt = dt_parser.parse(real_slot)
                        if slot_dt.hour == target_hour:
                            slot_time = real_slot
                            matched = True
                            logger.info("[Call %s] Hour-level slot match: %s", call_id, slot_time)
                            break

                if not matched:
                    logger.warning("[Call %s] No slot match found — using original: %s",
                                   call_id, slot_time)
            except Exception as match_exc:
                logger.warning("[Call %s] Slot matching failed: %s — using original",
                               call_id, match_exc)

            result = await calendar_service.book_appointment(
                patient_info=patient_info,
                start_time=slot_time,
                tenant_ctx=tenant_ctx,
                appointment_type_key=appt_type,
                provider_id=provider_id,
            )

            # Race lost — the unique-index fired because someone booked this
            # provider+time between when we showed the slot and committed.
            # Hand control back to the LLM with a clear message so it can
            # apologize and offer a different slot.
            if result and isinstance(result, dict) and result.get("status") == "CONFLICT":
                elapsed = (time.time() - t0) * 1000
                logger.warning(
                    "[Call %s] Booking conflict — slot taken (provider=%s, %s) in %.0fms",
                    call_id, provider_id, slot_time, elapsed,
                )
                return {
                    "ok": False,
                    "error": "slot_taken",
                    "summary_for_assistant": (
                        "That slot was just booked by someone else. "
                        "Apologize, then offer the patient another available time."
                    ),
                }
            if result:
                # Send SMS confirmation (uses tenant's Twilio — will no-op if unconfigured)
                try:
                    scheduled_dt = datetime.fromisoformat(args.get("slot_time", slot_time))
                    sms_service.send_confirmation(
                        patient_name=args.get("patient_name", ""),
                        phone=args.get("phone", ""),
                        appointment_type=args.get("appointment_type", "").replace("_", " ").title(),
                        scheduled_at=scheduled_dt,
                        tenant_ctx=tenant_ctx,
                    )
                except Exception as sms_exc:
                    logger.warning("[Call %s] SMS confirmation failed: %s", call_id, sms_exc)

                # ── Persist appointment + patient in DB ──────────────
                try:
                    from backend.services import patient_service
                    tenant_id = tenant_ctx.tenant_id if tenant_ctx else None
                    booking_uid = result.get("uid", "") if isinstance(result, dict) else ""
                    booking_id = result.get("id", "") if isinstance(result, dict) else ""
                    await patient_service.record_appointment(
                        patient_phone=args.get("phone", ""),
                        appointment_type=args.get("appointment_type", ""),
                        scheduled_at=datetime.fromisoformat(slot_time),
                        cal_booking_uid=str(booking_uid),
                        cal_booking_id=str(booking_id),
                        patient_name=args.get("patient_name", ""),
                        patient_email=email,
                        dob=args.get("dob", ""),
                        tenant_id=tenant_id,
                        provider_id=provider_id,
                    )
                    logger.info("[Call %s] ✓ Appointment recorded in DB (uid=%s)", call_id, booking_uid)
                except Exception as db_exc:
                    logger.warning("[Call %s] Patient/appointment DB upsert failed: %s",
                                   call_id, db_exc)

                elapsed = (time.time() - t0) * 1000
                logger.info("[Call %s] book_appointment → SUCCESS in %.0fms: %s",
                            call_id, elapsed, result)
                # Format time for the confirmation message
                try:
                    booked_dt = datetime.fromisoformat(slot_time)
                    time_str = booked_dt.strftime("%I:%M %p").lstrip("0")
                    date_str = booked_dt.strftime("%A, %B %d")
                except Exception:
                    time_str = slot_time
                    date_str = "the requested date"

                # Build confirmation message with provider if specified
                provider_msg = f" with {provider_name}" if provider_name else ""
                return {
                    "success": True,
                    "booking": result,
                    "provider_name": provider_name,
                    "summary_for_assistant": (
                        f"Booking confirmed for {time_str} on {date_str}{provider_msg}. "
                        f"Tell the patient their appointment is booked and they'll receive an SMS confirmation. "
                        f"Do NOT make up any details not provided. "
                        f"Just confirm the time, date{', and provider' if provider_name else ''}, wish them well, and ask if there's anything else."
                    ),
                }

            elapsed = (time.time() - t0) * 1000
            logger.error("[Call %s] book_appointment → FAILED in %.0fms", call_id, elapsed)
            return {
                "success": False,
                "error": "Failed to create booking.",
                "summary_for_assistant": (
                    "The booking could not be completed due to a technical issue. "
                    "Apologize to the patient and offer to try again or check a different time. "
                    "Do NOT make up reasons for the failure."
                ),
            }

        elif name == "reschedule_appointment":
            booking_uid = args.get("booking_uid", "")
            new_slot_time = args.get("new_slot_time", "")
            if not booking_uid or not new_slot_time:
                return {
                    "success": False,
                    "summary_for_assistant": "Cannot reschedule — I need the booking reference and a new time. "
                    "Ask the patient for these details.",
                }
            result = await calendar_service.reschedule_appointment(
                booking_uid=booking_uid,
                new_start_time=new_slot_time,
                tenant_ctx=tenant_ctx,
            )
            if result:
                # Send reschedule SMS
                try:
                    from dateutil import parser as dt_parser
                    new_dt = dt_parser.parse(new_slot_time)
                    sms_service.send_reschedule(
                        patient_name=session.get("patient_info", {}).get("name", "") if session else "",
                        phone=session.get("patient_info", {}).get("phone", "") if session else "",
                        new_scheduled_at=new_dt,
                        appointment_type="Appointment",
                        tenant_ctx=tenant_ctx,
                    )
                except Exception as sms_exc:
                    logger.warning("[Call %s] Reschedule SMS failed: %s", call_id, sms_exc)
                # Update appointment in DB
                try:
                    from backend.database import async_session as get_async_session
                    from sqlalchemy import select as sa_select
                    from backend.models.appointment import Appointment as ApptModel
                    async with get_async_session() as db_session:
                        stmt = sa_select(ApptModel).where(ApptModel.cal_booking_uid == booking_uid)
                        db_result = await db_session.execute(stmt)
                        appt = db_result.scalar_one_or_none()
                        if appt:
                            appt.scheduled_at = datetime.fromisoformat(new_slot_time)
                            await db_session.commit()
                            logger.info("[Call %s] ✓ DB appointment rescheduled: %s", call_id, booking_uid)
                except Exception as db_exc:
                    logger.warning("[Call %s] DB reschedule update failed: %s", call_id, db_exc)
                elapsed = (time.time() - t0) * 1000
                logger.info("[Call %s] reschedule → SUCCESS in %.0fms", call_id, elapsed)
                return {"success": True, "reschedule": result}
            elapsed = (time.time() - t0) * 1000
            logger.error("[Call %s] reschedule → FAILED in %.0fms", call_id, elapsed)
            return {"success": False, "error": "Failed to reschedule."}

        elif name == "cancel_appointment":
            booking_uid = args.get("booking_uid", "")
            if not booking_uid:
                return {
                    "success": False,
                    "summary_for_assistant": "Cannot cancel — I need the booking reference. "
                    "Ask the patient for their booking details or phone number to look it up.",
                }
            success = await calendar_service.cancel_appointment(
                booking_uid=booking_uid,
                reason=args.get("reason", ""),
                tenant_ctx=tenant_ctx,
            )
            if success:
                # Send cancellation SMS
                try:
                    patient_phone = session.get("patient_info", {}).get("phone", "") if session else ""
                    patient_name = session.get("patient_info", {}).get("name", "") if session else ""
                    if patient_phone:
                        sms_service.send_cancellation(
                            patient_name=patient_name,
                            phone=patient_phone,
                            scheduled_at=datetime.now(),  # approximate — we don't have original time
                            tenant_ctx=tenant_ctx,
                        )
                except Exception as sms_exc:
                    logger.warning("[Call %s] Cancel SMS failed: %s", call_id, sms_exc)
                # Update DB
                try:
                    from backend.database import async_session as get_async_session
                    from backend.models.appointment import Appointment as ApptModel, AppointmentStatus
                    async with get_async_session() as db_session:
                        from sqlalchemy import select as sa_select
                        stmt = sa_select(ApptModel).where(ApptModel.cal_booking_uid == booking_uid)
                        db_result = await db_session.execute(stmt)
                        appt = db_result.scalar_one_or_none()
                        if appt:
                            appt.status = AppointmentStatus.CANCELLED
                            await db_session.commit()
                            logger.info("[Call %s] ✓ DB appointment cancelled: %s", call_id, booking_uid)
                except Exception as db_exc:
                    logger.warning("[Call %s] DB cancel update failed: %s", call_id, db_exc)
            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] cancel → %s in %.0fms", call_id, success, elapsed)
            return {"success": success}

        elif name == "escalate_to_human":
            caller = session["caller_number"] if session else "unknown"
            sms_service.send_office_alert(
                reason=args.get("reason", "Patient requested human assistance"),
                caller_number=caller,
                tenant_ctx=tenant_ctx,
            )
            if session:
                session["current_state"] = "escalated"
            # Prefer the dedicated `escalation_transfer_number` (set by an
            # admin for live phone transfers) — fall back to `escalation_phone`
            # so older tenants still escalate even if they only set one field.
            if tenant_ctx:
                transfer_dest = (
                    (tenant_ctx.escalation_transfer_number or "").strip()
                    or (tenant_ctx.escalation_phone or "").strip()
                )
            else:
                transfer_dest = (
                    (settings.ESCALATION_TRANSFER_NUMBER or "").strip()
                    or (settings.ESCALATION_PHONE_NUMBER or "").strip()
                )
            return {
                "success": True,
                "action": "transfer",
                "destination": transfer_dest,
            }

        elif name == "send_callback_request":
            sms_service.send_escalation_notification(
                patient_name=args.get("patient_name", ""),
                phone=args.get("phone", ""),
                tenant_ctx=tenant_ctx,
            )
            sms_service.send_office_alert(
                reason=f"Callback requested: {args.get('reason', 'N/A')}",
                caller_number=args.get("phone", ""),
                tenant_ctx=tenant_ctx,
            )
            return {"success": True, "message": "Callback request sent."}

        elif name == "get_office_info":
            result = _build_office_info(args.get("topic", "all"), tenant_ctx)
            return result

        elif name == "lookup_patient_appointments":
            from backend.services import patient_service
            phone = args.get("phone", "")
            if not phone:
                return {
                    "ok": False,
                    "summary_for_assistant": "I need the patient's phone number to look up their appointments.",
                }
            tenant_id = tenant_ctx.tenant_id if tenant_ctx else None
            tz_name = tenant_ctx.timezone if tenant_ctx else None
            history = await patient_service.get_patient_history(phone, tenant_id=tenant_id, tz_name=tz_name)
            if not history:
                return {
                    "ok": False,
                    "summary_for_assistant": (
                        f"No patient record found for {phone}. "
                        "This might be a new patient. Ask if they'd like to schedule a new appointment."
                    ),
                }
            upcoming = history.get("upcoming_appointments", [])
            patient_name = history["patient"]["name"]
            if not upcoming:
                return {
                    "ok": True,
                    "summary_for_assistant": (
                        f"{patient_name} has no upcoming appointments. "
                        "Ask if they'd like to schedule a new one."
                    ),
                    "patient_name": patient_name,
                    "upcoming": [],
                }
            appt_lines = [f"{a['type']} on {a['date']} at {a['time']}" for a in upcoming]
            return {
                "ok": True,
                "summary_for_assistant": (
                    f"{patient_name} has {len(upcoming)} upcoming appointment(s): "
                    + "; ".join(appt_lines) + ". "
                    "Tell the patient about their appointment(s) naturally. "
                    "If they want to reschedule, use the booking_uid with reschedule_appointment."
                ),
                "patient_name": patient_name,
                "upcoming": upcoming,
            }

        elif name == "add_to_waitlist":
            from backend.services import waitlist_service
            import uuid as uuid_mod

            # Capture the patient's preferred doctor (if any) so the admin
            # UI can match the right opening to them — and so the waitlist
            # auto-notifier scopes to that doctor's cancellations.
            wl_provider_uuid = None
            wl_provider_id_str = (args.get("provider_id") or "").strip()
            if wl_provider_id_str:
                try:
                    wl_provider_uuid = uuid_mod.UUID(wl_provider_id_str)
                except (ValueError, TypeError):
                    logger.warning("[Call %s] add_to_waitlist got invalid provider_id %r",
                                   call_id, wl_provider_id_str)

            result = await waitlist_service.add_to_waitlist(
                tenant_id=tenant_ctx.tenant_id if tenant_ctx else None,
                patient_name=args.get("patient_name", ""),
                patient_phone=args.get("phone", ""),
                appointment_type=args.get("appointment_type", "consultation"),
                preferred_date=args.get("preferred_date", ""),
                preferred_time_start=args.get("preferred_time_start") or None,
                preferred_time_end=args.get("preferred_time_end") or None,
                provider_id=wl_provider_uuid,
                tenant_ctx=tenant_ctx,
            )
            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] add_to_waitlist → %s in %.0fms", call_id, result.get("status"), elapsed)
            return result

        elif name == "lookup_patient":
            from backend.services import patient_service
            phone = args.get("phone", "")
            patient_name = args.get("name", "")

            if not phone and not patient_name:
                return {
                    "ok": False,
                    "summary_for_assistant": "I need either the patient's phone number or name to look them up.",
                }

            tenant_id = tenant_ctx.tenant_id if tenant_ctx else None
            tz_name = tenant_ctx.timezone if tenant_ctx else None

            # Primary: look up by phone
            history = None
            if phone:
                history = await patient_service.get_patient_history(phone, tenant_id=tenant_id, tz_name=tz_name)

            # Fallback: search by name if phone didn't match
            if not history and patient_name:
                matches = await patient_service.get_patient_by_name(
                    patient_name, tenant_id=tenant_id,
                )
                if len(matches) > 1:
                    # Multiple patients share this name — ask for phone to disambiguate
                    elapsed = (time.time() - t0) * 1000
                    match_lines = [
                        f"- {m.name} (phone ending ...{m.phone[-4:]})"
                        for m in matches
                    ]
                    logger.info("[Call %s] lookup_patient → %d name matches for '%s' in %.0fms — disambiguation needed",
                                call_id, len(matches), patient_name, elapsed)
                    return {
                        "ok": False,
                        "multiple_matches": True,
                        "match_count": len(matches),
                        "summary_for_assistant": (
                            f"Found {len(matches)} patients matching the name '{patient_name}': "
                            + "; ".join(match_lines) + ". "
                            "You already have the caller's phone number from caller-ID (in your system prompt). "
                            "Call lookup_patient again with the phone parameter to get the exact match. "
                            "If for some reason you don't have the phone, ask the patient to confirm it."
                        ),
                    }
                elif len(matches) == 1:
                    history = await patient_service.get_patient_history(
                        matches[0].phone, tenant_id=tenant_id, tz_name=tz_name,
                    )

            if not history:
                elapsed = (time.time() - t0) * 1000
                logger.info("[Call %s] lookup_patient → not found in %.0fms (phone=%s, name=%s)",
                            call_id, elapsed, phone, patient_name)
                return {
                    "ok": False,
                    "summary_for_assistant": (
                        f"No patient record found for {phone or patient_name}. "
                        "This appears to be a new patient. You will need to collect their "
                        "full name, date of birth, and reason for visit before booking."
                    ),
                }

            p = history["patient"]
            upcoming = history.get("upcoming_appointments", [])
            past = history.get("past_appointments", [])
            last_visit = history.get("last_visit")
            months_since = history.get("months_since_last_visit")

            # Build a natural-language summary for the LLM
            summary_parts = [f"Patient found: {p['name']}, phone {p['phone']}."]
            if p.get("dob"):
                summary_parts.append(f"DOB: {p['dob']}.")
            else:
                summary_parts.append("DOB: not on file — ask the patient.")
            if p.get("allergies"):
                summary_parts.append(f"Allergies: {p['allergies']}.")
            if p.get("notes"):
                summary_parts.append(f"Notes: {p['notes']}.")
            summary_parts.append(f"Visit count: {p.get('visit_count', 0)}.")

            if last_visit:
                ago = f" ({months_since} months ago)" if months_since is not None else ""
                summary_parts.append(f"Last visit: {last_visit['type']} on {last_visit['date']}{ago}.")

            if upcoming:
                appt_lines = [f"{a['type']} on {a['date']} at {a['time']}" for a in upcoming]
                summary_parts.append(f"Upcoming appointments: {'; '.join(appt_lines)}.")
            else:
                summary_parts.append("No upcoming appointments.")

            if past:
                past_lines = [f"{a['type']} on {a['date']} ({a['status']})" for a in past[:3]]
                summary_parts.append(f"Recent history: {'; '.join(past_lines)}.")

            summary_parts.append(
                "Use this data when speaking to the patient. Do NOT ask for info you already have. "
                "If DOB is missing, ask for it. If updating any info, use update_patient_info."
            )

            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] lookup_patient → found %s (%d upcoming, %d past) in %.0fms",
                        call_id, p['name'], len(upcoming), len(past), elapsed)
            return {
                "ok": True,
                "summary_for_assistant": " ".join(summary_parts),
                "patient": p,
                "upcoming_appointments": upcoming,
                "past_appointments": past,
                "last_visit": last_visit,
                "months_since_last_visit": months_since,
            }

        elif name == "update_patient_info":
            from backend.services import patient_service
            phone = args.get("phone", "")
            if not phone:
                return {
                    "ok": False,
                    "summary_for_assistant": "I need the patient's phone number to update their record.",
                }

            tenant_id = tenant_ctx.tenant_id if tenant_ctx else None

            # Check the patient exists first
            existing = await patient_service.get_patient_by_phone(phone, tenant_id=tenant_id)
            if not existing:
                return {
                    "ok": False,
                    "summary_for_assistant": (
                        f"No patient record found for {phone}. Cannot update a non-existent record. "
                        "If this is a new patient, their record will be created when you book their appointment."
                    ),
                }

            # Update specific fields
            updated_fields = []
            from backend.database import async_session as get_async_session
            async with get_async_session() as db_session:
                from sqlalchemy import select as sa_select
                from sqlalchemy import and_
                from backend.models.patient import Patient

                filters = [Patient.phone == patient_service._normalise_phone(phone)]
                if tenant_id:
                    filters.append(Patient.tenant_id == tenant_id)

                result = await db_session.execute(
                    sa_select(Patient).where(and_(*filters))
                )
                patient = result.scalar_one_or_none()

                if not patient:
                    return {"ok": False, "summary_for_assistant": "Patient record not found."}

                if args.get("name", "").strip():
                    patient.name = args["name"].strip()
                    updated_fields.append("name")
                if args.get("dob", "").strip():
                    patient.date_of_birth = args["dob"].strip()
                    updated_fields.append("date of birth")
                if args.get("email", "").strip():
                    patient.email = args["email"].strip()
                    updated_fields.append("email")
                if args.get("allergies", "").strip():
                    patient.allergies = args["allergies"].strip()
                    updated_fields.append("allergies")
                if args.get("notes", "").strip():
                    patient.notes = args["notes"].strip()
                    updated_fields.append("notes")

                if not updated_fields:
                    return {
                        "ok": False,
                        "summary_for_assistant": "No fields to update were provided. Specify at least one of: name, dob, email, allergies, notes.",
                    }

                await db_session.commit()

            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] update_patient_info → updated %s for %s in %.0fms",
                        call_id, updated_fields, phone, elapsed)
            return {
                "ok": True,
                "summary_for_assistant": (
                    f"Updated {', '.join(updated_fields)} for patient {existing.name} ({phone}). "
                    f"The changes are saved. Continue the conversation normally."
                ),
                "updated_fields": updated_fields,
            }

        elif name == "get_providers":
            from backend.services import provider_service
            appt_type = args.get("appointment_type", "")
            if appt_type and tenant_ctx:
                providers = await provider_service.get_providers_for_appointment_type(
                    tenant_ctx.tenant_id, appt_type,
                )
            elif tenant_ctx:
                providers = await provider_service.list_providers(tenant_ctx.tenant_id)
            else:
                providers = []

            if not providers:
                summary = "This practice doesn't have individual provider profiles configured. Any available provider can see the patient. Do not pass a provider_id when booking."
            else:
                provider_list = ", ".join(f"{p['name']} ({p.get('title', '')})" for p in providers)
                summary = (
                    f"Available providers: {provider_list}. "
                    f"Ask the patient if they have a preference. "
                    f"When they choose, use that provider's 'id' from the providers list below in get_available_slots and book_appointment. "
                    f"If they say 'anyone is fine', proceed without a provider_id."
                )

            elapsed = (time.time() - t0) * 1000
            logger.info("[Call %s] get_providers → %d providers in %.0fms", call_id, len(providers), elapsed)
            return {
                "summary_for_assistant": summary,
                "providers": providers,
                "count": len(providers),
            }

        else:
            logger.warning("[Call %s] Unknown tool requested: %s", call_id, name)
            return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        logger.error("[Call %s] Tool '%s' failed after %.0fms: %s", call_id, name, elapsed, exc, exc_info=True)
        return {"error": str(exc)}


# ── Office info builder (for get_office_info tool) ──────────────────────────


def _fmt_time_12h(t: str) -> str:
    """Convert '08:00' → '8:00 AM', '16:00' → '4:00 PM'."""
    try:
        parts = t.strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        suffix = "AM" if h < 12 else "PM"
        display_h = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
        return f"{display_h}:{m:02d} {suffix}"
    except Exception:
        return t


def _build_office_info(topic: str, tenant_ctx: Any | None) -> dict[str, Any]:
    """
    Build pre-formatted office info that the LLM can read verbatim.
    Returns a dict with 'summary_for_assistant' that contains the exact text
    the LLM should say — no interpretation needed.
    """
    parts = []

    # ── Hours ────────────────────────────────────────────────────────────
    if topic in ("hours", "all"):
        bh = tenant_ctx.business_hours if tenant_ctx else None
        if bh:
            day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

            # Smart grouping: consecutive days with same hours get grouped
            groups: list[tuple[list[str], str]] = []
            for i, day_key in enumerate(day_order):
                info = bh.get(day_key)
                if info and isinstance(info, dict) and info.get("open"):
                    label = f"{_fmt_time_12h(info['open'])} to {_fmt_time_12h(info['close'])}"
                else:
                    label = "Closed"
                if groups and groups[-1][1] == label:
                    groups[-1][0].append(day_names[i])
                else:
                    groups.append(([day_names[i]], label))

            sentence_parts = []
            for day_list, label in groups:
                if len(day_list) == 1:
                    sentence_parts.append(f"{day_list[0]} {label}")
                elif len(day_list) == 2:
                    sentence_parts.append(f"{day_list[0]} and {day_list[1]} {label}")
                else:
                    sentence_parts.append(f"{day_list[0]} through {day_list[-1]} {label}")

            hours_text = "Our hours are: " + ", ".join(sentence_parts) + "."
        else:
            hours_text = "Business hours have not been configured yet."
        parts.append(hours_text)

        # ── Upcoming holidays / closures ────────────────────────────────
        try:
            from backend.services.tenant_service import upcoming_holidays as _upcoming
            upcoming = _upcoming(tenant_ctx, limit=6) if tenant_ctx else []
        except Exception:
            upcoming = []
        if upcoming:
            from datetime import datetime as _dt
            holiday_lines = []
            for h in upcoming:
                try:
                    d = _dt.strptime(h["date"], "%Y-%m-%d").date()
                    holiday_lines.append(f"{d.strftime('%B %-d')} for {h.get('name') or 'Holiday'}")
                except Exception:
                    holiday_lines.append(f"{h.get('date')} for {h.get('name') or 'Holiday'}")
            parts.append(
                "We're also closed on the following upcoming dates: "
                + "; ".join(holiday_lines) + "."
            )

    # ── Location / contact ───────────────────────────────────────────────
    if topic in ("location", "all"):
        contact_parts = []
        if tenant_ctx:
            if tenant_ctx.business_address:
                contact_parts.append(f"We are located at {tenant_ctx.business_address}.")
            if tenant_ctx.business_phone:
                contact_parts.append(f"Our phone number is {tenant_ctx.business_phone}.")
        # Also check KB for office_info
        kb = _get_kb(tenant_ctx)
        office_info = kb.get("office_info", {})
        if not contact_parts:
            if office_info.get("address"):
                contact_parts.append(f"We are located at {office_info['address']}.")
            if office_info.get("phone"):
                contact_parts.append(f"Our phone number is {office_info['phone']}.")
        if contact_parts:
            parts.append(" ".join(contact_parts))
        else:
            parts.append("Office location and contact details are not configured yet.")

    # ── Services & pricing ───────────────────────────────────────────────
    if topic in ("services", "all"):
        kb = _get_kb(tenant_ctx)
        services = kb.get("services", [])
        if services:
            svc_lines = ["Here are our services and approximate pricing:"]
            for svc in services:
                name = svc.get("name", "Service")
                low = svc.get("price_min", "?")
                high = svc.get("price_max", "?")
                svc_lines.append(f"  - {name}: ${low} to ${high}")
            parts.append("\n".join(svc_lines))

    # ── FAQs ─────────────────────────────────────────────────────────────
    if topic in ("faqs", "all"):
        kb = _get_kb(tenant_ctx)
        faqs = kb.get("faqs", [])
        if faqs:
            faq_lines = ["Frequently asked questions:"]
            for faq in faqs:
                faq_lines.append(f"  Q: {faq.get('question', '')}")
                faq_lines.append(f"  A: {faq.get('answer', '')}")
            parts.append("\n".join(faq_lines))

    summary = "\n\n".join(parts) if parts else "I don't have that information available right now."

    return {
        "summary_for_assistant": (
            f"{summary}\n\n"
            f"Read the information above to the patient in 1-2 short sentences. "
            f"Use the EXACT answer from the FAQs — do NOT add generic information, "
            f"do NOT embellish with details not provided, and do NOT guess. "
            f"If the FAQ says 'Typically, 1 hr', say 'Typically about an hour' — nothing more."
        ),
    }


def _get_kb(tenant_ctx: Any | None) -> dict:
    """Get the knowledge base for a tenant (lazy import to avoid circular deps)."""
    from backend.services.knowledge_service import get_tenant_kb
    return get_tenant_kb(tenant_ctx)


# ── Date resolution helper ──────────────────────────────────────────────────

_DOW_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _resolve_dow_to_date(user_text: str, tenant_ctx: Any | None = None) -> str | None:
    """
    If the user's message mentions a day-of-week or 'tomorrow'/'today',
    return the corresponding YYYY-MM-DD in the tenant's timezone.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    tz_name = "America/Chicago"
    if tenant_ctx and getattr(tenant_ctx, "timezone", None):
        tz_name = tenant_ctx.timezone
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")

    today = datetime.now(tz)
    text = user_text.lower()

    if "today" in text:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    for dow_name, dow_idx in _DOW_MAP.items():
        if dow_name in text:
            today_idx = today.weekday()
            delta = (dow_idx - today_idx) % 7
            if "next" in text:
                delta = delta + 7 if delta != 0 else 7
            target = today + timedelta(days=delta)
            return target.strftime("%Y-%m-%d")

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_timestamps(messages: list[dict]) -> list[dict]:
    """Remove the 'timestamp' key from messages before sending to the LLM."""
    clean = []
    for msg in messages:
        m = {k: v for k, v in msg.items() if k != "timestamp"}
        clean.append(m)
    return clean
