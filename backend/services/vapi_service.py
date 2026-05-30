"""
Vapi.ai webhook processing and assistant management.

Multi-tenant: assistant creation/update can be tenant-specific using the
tenant's Vapi API key and configuration. The webhook handler resolves
tenant context from call data.

Handles:
  - Assistant creation / update on startup (legacy mode)
  - Webhook event routing (call-start, transcript, function-call, call-end)
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.config import settings
from backend.defaults import DEFAULT_AGENT_NAME
from backend.services import llm_service
from backend.services.http_client import http

logger = logging.getLogger(__name__)

VAPI_API_BASE = "https://api.vapi.ai"

# ── Vapi platform defaults ──────────────────────────────────────────────────
# These are Vapi assistant-level settings, managed on the Vapi platform.
# Kept here (not in defaults.py) because they're Vapi-specific implementation
# details, not general application config.

_VOICE_PROVIDER = "11labs"
_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel"
_VOICE_STABILITY = 0.5
_VOICE_SIMILARITY_BOOST = 0.75
_END_CALL_PHRASES = [
    "goodbye",
    "thank you bye",
    "have a good day",
    "have a great day",
    "that's all I needed",
    "nothing else thank you",
    "no that's it",
    "I'm good thanks",
]


def _vapi_headers(api_key: str | None = None) -> dict[str, str]:
    key = api_key or settings.VAPI_API_KEY
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ── Assistant management ──────────────────────────────────────────────────────


async def register_assistant(tenant_ctx: Any | None = None) -> str | None:
    """
    Create or update a Vapi assistant.

    If tenant_ctx is provided, uses tenant-specific config (name, voice, greeting).
    Otherwise uses legacy global settings.
    """
    # Option A (centralised SaaS): one global Vapi API key for all tenants.
    # Tenant-level key is used as override only if explicitly set (legacy).
    if tenant_ctx:
        api_key = tenant_ctx.vapi_api_key or settings.VAPI_API_KEY
        assistant_id = tenant_ctx.vapi_assistant_id
        agent_name = tenant_ctx.agent_name or DEFAULT_AGENT_NAME
        business_name = tenant_ctx.business_name or "Office"
        greeting = tenant_ctx.greeting_message or f"Thank you for calling {business_name}. How can I help you today?"
        # Resolve tenant's chosen voice. voice_config is a JSONB dict that may
        # be a plain mapping or, defensively, an attribute-style object.
        voice_cfg = getattr(tenant_ctx, "voice_config", None) or {}
        if isinstance(voice_cfg, dict):
            voice_provider = voice_cfg.get("provider") or _VOICE_PROVIDER
            voice_id = voice_cfg.get("voiceId") or _VOICE_ID
        else:
            voice_provider = _VOICE_PROVIDER
            voice_id = _VOICE_ID
    else:
        api_key = settings.VAPI_API_KEY
        assistant_id = settings.VAPI_ASSISTANT_ID
        agent_name = DEFAULT_AGENT_NAME
        business_name = settings.OFFICE_NAME
        greeting = f"Thank you for calling {business_name}. This is {agent_name}. How can I help you today?"
        voice_provider = _VOICE_PROVIDER
        voice_id = _VOICE_ID

    if not api_key:
        logger.warning("VAPI_API_KEY not set — skipping assistant registration.")
        return None

    webhook_url = f"{settings.SERVER_BASE_URL}/webhook/vapi"
    webhook_secret = tenant_ctx.vapi_webhook_secret if tenant_ctx else settings.VAPI_WEBHOOK_SECRET

    assistant_config = {
        "name": f"{agent_name} - {business_name}",
        "model": {
            "provider": "custom-llm",
            "url": f"{settings.SERVER_BASE_URL}/api/llm",
            "model": settings.OLLAMA_MODEL,
        },
        "voice": {
            "provider": voice_provider,
            "voiceId": voice_id,
            "stability": _VOICE_STABILITY,
            "similarityBoost": _VOICE_SIMILARITY_BOOST,
        },
        "firstMessage": greeting,
        "endCallPhrases": list(_END_CALL_PHRASES),
        "serverUrl": webhook_url,
        "serverUrlSecret": webhook_secret,
    }

    try:
        if assistant_id:
            resp = await http.patch(
                f"{VAPI_API_BASE}/assistant/{assistant_id}",
                headers=_vapi_headers(api_key),
                json=assistant_config,
            )
        else:
            resp = await http.post(
                f"{VAPI_API_BASE}/assistant",
                headers=_vapi_headers(api_key),
                json=assistant_config,
            )
        resp.raise_for_status()
        data = resp.json()

        result_id = data.get("id", assistant_id)
        slug = tenant_ctx.slug if tenant_ctx else "default"
        logger.info("[Vapi][%s] Assistant registered: %s (webhook: %s)", slug, result_id, webhook_url)
        return result_id

    except httpx.HTTPStatusError as exc:
        logger.error("Vapi assistant registration failed (HTTP %s): %s",
                      exc.response.status_code, exc.response.text)
        return None
    except Exception as exc:
        logger.error("Vapi assistant registration error: %s", exc)
        return None


# ── Webhook event processing ─────────────────────────────────────────────────


async def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Route a Vapi webhook event to the appropriate handler.
    Returns the response dict that Vapi expects.
    """
    message = payload.get("message", {})
    event_type = message.get("type", "")
    call_data = message.get("call", {})
    call_id = call_data.get("id", "")

    logger.info("Vapi webhook: type=%s call_id=%s", event_type, call_id)

    if event_type == "assistant-request":
        # Resolve tenant for assistant-request
        assistant_id = call_data.get("assistantId", "")
        return await _handle_assistant_request(assistant_id)

    elif event_type == "status-update":
        status = message.get("status", "")
        if status == "in-progress":
            return await _handle_call_start(call_id, call_data)
        elif status == "ended":
            return await _handle_call_end(call_id, call_data)
        return {"status": "ok"}

    elif event_type == "transcript":
        return await _handle_transcript(call_id, message)

    elif event_type == "function-call":
        return await _handle_function_call(call_id, message)

    elif event_type == "conversation-update":
        return await _handle_conversation_update(call_id, message)

    elif event_type == "end-of-call-report":
        return await _handle_end_of_call_report(call_id, message)

    else:
        logger.debug("Unhandled Vapi event type: %s", event_type)
        return {"status": "ok"}


async def _handle_assistant_request(assistant_id: str = "") -> dict[str, Any]:
    """
    Return assistant configuration when Vapi requests it.
    If we can resolve a tenant, use their config; otherwise default.
    """
    tenant_ctx = None
    if assistant_id:
        from backend.services.tenant_service import resolve_by_assistant_id
        tenant_ctx = await resolve_by_assistant_id(assistant_id)

    if tenant_ctx:
        # If the owner has turned off the agent, tell Vapi to forward the
        # call to the business phone immediately instead of running the AI.
        if not getattr(tenant_ctx, "agent_active", True):
            forward_number = (
                getattr(tenant_ctx, "business_phone", None)
                or getattr(tenant_ctx, "escalation_phone", None)
                or ""
            )
            business_name = tenant_ctx.business_name or "the office"
            logger.info(
                "Agent is OFF for %s — forwarding call to %s",
                tenant_ctx.slug if hasattr(tenant_ctx, 'slug') else '?',
                forward_number or '(none)',
            )
            return {
                "assistant": {
                    "name": f"Forwarding - {business_name}",
                    "model": {
                        "provider": "custom-llm",
                        "url": f"{settings.SERVER_BASE_URL}/api/llm",
                        "model": settings.OLLAMA_MODEL,
                    },
                    "voice": {"provider": _VOICE_PROVIDER, "voiceId": _VOICE_ID},
                    "firstMessage": (
                        f"Thank you for calling {business_name}. "
                        f"Please hold while I transfer you to the office."
                    ),
                    **({"forwardingPhoneNumber": forward_number} if forward_number else {}),
                }
            }

        agent_name = tenant_ctx.agent_name or DEFAULT_AGENT_NAME
        business_name = tenant_ctx.business_name
        greeting = tenant_ctx.greeting_message or f"Thank you for calling {business_name}. How can I help you today?"
        voice_cfg = getattr(tenant_ctx, "voice_config", None) or {}
        if isinstance(voice_cfg, dict):
            voice_provider = voice_cfg.get("provider") or _VOICE_PROVIDER
            voice_id = voice_cfg.get("voiceId") or _VOICE_ID
        else:
            voice_provider = _VOICE_PROVIDER
            voice_id = _VOICE_ID
    else:
        agent_name = DEFAULT_AGENT_NAME
        business_name = settings.OFFICE_NAME
        greeting = f"Thank you for calling {business_name}. This is {agent_name}. How can I help you today?"
        voice_provider = _VOICE_PROVIDER
        voice_id = _VOICE_ID

    return {
        "assistant": {
            "name": f"{agent_name} - {business_name}",
            "model": {
                "provider": "custom-llm",
                "url": f"{settings.SERVER_BASE_URL}/api/llm",
                "model": settings.OLLAMA_MODEL,
            },
            "voice": {
                "provider": voice_provider,
                "voiceId": voice_id,
            },
            "firstMessage": greeting,
        }
    }


async def _handle_call_start(call_id: str, call_data: dict) -> dict[str, Any]:
    """Initialise a new session when a call begins, with caller recognition."""
    caller_number = call_data.get("customer", {}).get("number", "")

    # ── Resolve tenant so we can scope the patient lookup ──────────────
    tenant_ctx = None
    phone_number_id = call_data.get("phoneNumberId", "") or ""
    assistant_id = (call_data.get("assistantId", "") or
                    call_data.get("assistant", {}).get("id", ""))
    if phone_number_id:
        from backend.services.tenant_service import resolve_by_phone_number_id
        tenant_ctx = await resolve_by_phone_number_id(phone_number_id)
    if not tenant_ctx and assistant_id:
        from backend.services.tenant_service import resolve_by_assistant_id
        tenant_ctx = await resolve_by_assistant_id(assistant_id)

    # ── Per-tenant Vapi feature flag ─────────────────────────────────
    # The global flag is already checked in the webhook route layer.
    # Here we enforce the per-tenant toggle (mirrors sms_service pattern).
    if tenant_ctx and hasattr(tenant_ctx, "feature_vapi_enabled") and not tenant_ctx.feature_vapi_enabled:
        logger.warning(
            "[CallStart] Vapi disabled for tenant %s — ignoring call %s",
            tenant_ctx.slug, call_id,
        )
        return {"status": "ok"}

    # ── Caller recognition → patient context ──────────────────────────
    # Skip recognition if the caller phone is the clinic's own Twilio number
    # (happens when testing via Vapi web dialer — no real caller).
    patient_context = None
    tenant_id = tenant_ctx.tenant_id if tenant_ctx else None
    _is_own_number = False
    if caller_number and tenant_ctx and tenant_ctx.twilio_phone_number:
        from backend.services.patient_service import _phone_digits_tail
        _is_own_number = (
            _phone_digits_tail(caller_number) == _phone_digits_tail(tenant_ctx.twilio_phone_number)
        )
        if _is_own_number:
            logger.info(
                "[CallStart] Caller %s matches clinic Twilio number — skipping caller recognition",
                caller_number,
            )
            # Clear so downstream doesn't treat clinic's number as the patient's
            caller_number = ""

    if caller_number and not _is_own_number:
        try:
            from backend.services import patient_service
            tz_name = tenant_ctx.timezone if tenant_ctx else None
            patient_context = await patient_service.get_patient_history(
                caller_number, tenant_id=tenant_id, tz_name=tz_name,
            )
            if patient_context:
                logger.info("[CallStart] 🎯 RETURNING PATIENT: %s (%d visits)",
                            patient_context["patient"]["name"],
                            patient_context["patient"]["visit_count"])
        except Exception as exc:
            logger.warning("[CallStart] Patient lookup failed: %s", exc)

    llm_service.create_session(
        call_id, caller_number,
        tenant_ctx=tenant_ctx,
        patient_context=patient_context,
    )
    logger.info("Call started: %s from %s (tenant=%s, recognised=%s)",
                call_id, caller_number,
                tenant_ctx.slug if tenant_ctx else "none",
                bool(patient_context))
    return {"status": "ok"}


async def _handle_transcript(call_id: str, message: dict) -> dict[str, Any]:
    """Process intermediate transcript updates."""
    transcript = message.get("transcript", "")
    role = message.get("role", "user")

    session = llm_service.get_session(call_id)
    if session and transcript:
        if message.get("transcriptType") == "final":
            logger.debug("Transcript [%s]: %s", role, transcript[:80])
    return {"status": "ok"}


async def _handle_conversation_update(call_id: str, message: dict) -> dict[str, Any]:
    """Handle conversation updates."""
    messages = message.get("messages", [])
    if not messages:
        return {"status": "ok"}

    latest = messages[-1]
    if latest.get("role") != "user":
        return {"status": "ok"}

    user_text = latest.get("content", "")
    if not user_text:
        return {"status": "ok"}

    response = await llm_service.process_message(call_id, user_text)
    return {"result": response}


async def _handle_function_call(call_id: str, message: dict) -> dict[str, Any]:
    """Execute a function call requested by Vapi."""
    fn_call = message.get("functionCall", {})
    fn_name = fn_call.get("name", "")
    fn_params = fn_call.get("parameters", {})

    logger.info("Vapi function call: %s(%s)", fn_name, fn_params)

    result = await llm_service._execute_tool(call_id, fn_name, fn_params)
    return {"result": result}


async def _handle_call_end(call_id: str, call_data: dict) -> dict[str, Any]:
    """Finalise a call — flush session to DB."""
    session = llm_service.end_session(call_id)
    if session:
        logger.info("Call ended: %s", call_id)
    return {"status": "ok", "session": session}


async def _handle_end_of_call_report(call_id: str, message: dict) -> dict[str, Any]:
    """Process Vapi's end-of-call report for analytics."""
    report = message.get("endedReason", "unknown")
    duration = message.get("durationSeconds", 0)
    logger.info("End-of-call report: call=%s reason=%s duration=%ds", call_id, report, duration)
    return {"status": "ok"}
