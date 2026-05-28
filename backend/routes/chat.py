"""
Local chat endpoint — text-based replacement for Vapi voice during local dev.

When LOCAL_CHAT_MODE is enabled, the frontend exposes a /chat page that POSTs
user messages here. We reuse the exact same LLM + tool-calling pipeline that
Vapi uses (via `llm_service.process_message`) and stream the response back as
SSE in the OpenAI `chat.completion.chunk` format — identical to the wire format
emitted by `llm_proxy._stream_text_response`. This means the chat UI behaves
just like Vapi's transcript stream and the agent's tool calls (book_appointment,
get_available_slots, escalate_to_human, etc.) all execute normally.

Endpoints:
  GET  /api/chat/enabled       → whether local chat mode is on (public)
  POST /api/chat/stream        → stream a chat reply as SSE   (authenticated)
  POST /api/chat/reset         → clear server-side session    (authenticated)
"""

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from datetime import timezone as tz

from backend.config import settings
from backend.models.tenant import Tenant
from backend.services import auth_service, llm_service, patient_service
from backend.services.tenant_service import resolve_by_id, TenantContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["Chat"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = Field(
        default=None,
        description=(
            "Stable id used to keep a multi-turn session alive. If omitted, the "
            "client should generate one (e.g. uuid4) and pass it on every turn."
        ),
    )
    test_phone: Optional[str] = Field(
        default=None,
        description=(
            "Override which test caller phone to use for this chat session. "
            "Must be one of the tenant's registered test_caller_phones. "
            "If omitted, uses the tenant's default test_caller_phone."
        ),
    )
    test_patient_name: Optional[str] = Field(
        default=None,
        description=(
            "Override the test patient name for this chat session. "
            "Must be one of the tenant's registered test_patient_names. "
            "If omitted, uses the tenant's default test_patient_name."
        ),
    )


class ChatEnabledResponse(BaseModel):
    enabled: bool


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/enabled", response_model=ChatEnabledResponse)
async def chat_enabled():
    """Public — always enabled. The Test Agent chat is available regardless of LOCAL_CHAT_MODE."""
    return ChatEnabledResponse(enabled=True)


@router.post("/reset")
async def reset_chat(
    body: ChatRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """End the LLM session for this conversation_id (clears history)."""
    session_key = _session_key(current_user, body.conversation_id, body.test_phone)
    llm_service.end_session(session_key)
    return {"status": "reset", "conversation_id": body.conversation_id}


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Process a user message through the same LLM + tool pipeline Vapi uses,
    then stream the assistant's reply back as SSE in OpenAI
    `chat.completion.chunk` format — identical to the Vapi wire format.
    """
    # Include test_phone in session key so switching callers creates fresh sessions
    session_key = _session_key(current_user, body.conversation_id, body.test_phone)
    model = settings.OLLAMA_MODEL

    # ── Resolve tenant context from the authenticated user ──────────────
    # This ensures all downstream service calls (SMS, calendar, etc.) use
    # the tenant's own credentials — NEVER the global .env fallback.
    tenant_ctx: TenantContext | None = await resolve_by_id(current_user.id)
    if not tenant_ctx:
        logger.warning("[Chat] No TenantContext for user %s — tools will be limited", current_user.slug)

    # ── Pre-create session with patient context (first message only) ────
    # Use the tenant's test_caller_phone as the caller number so the Test
    # Agent chat works identically to a real phone call — patient lookup,
    # greeting by name, awareness of upcoming appointments, etc.
    existing_session = llm_service.get_session(session_key)
    if not existing_session and tenant_ctx and tenant_ctx.test_caller_phone:
        # Allow the client to pick which test phone to use for this session.
        # Validates against the tenant's registered phones to prevent spoofing.
        caller_phone = tenant_ctx.test_caller_phone
        if body.test_phone:
            allowed_phones = set(tenant_ctx.test_caller_phones or [])
            # Also allow the legacy single phone
            allowed_phones.add(tenant_ctx.test_caller_phone)
            if body.test_phone in allowed_phones:
                caller_phone = body.test_phone
            else:
                logger.warning("[Chat] Requested test_phone %s not in tenant's list — using default",
                               body.test_phone)
        patient_context = None
        try:
            patient_context = await patient_service.get_patient_history(
                caller_phone,
                tenant_id=tenant_ctx.tenant_id,
                tz_name=tenant_ctx.timezone,
            )
        except Exception as exc:
            logger.warning("[Chat] Patient lookup failed for test phone %s: %s",
                           caller_phone, exc)

        # If no real patient record exists for the test phone, build a
        # clean new-patient context so the agent can demo booking flows.
        # This is prompt-only — NO fake records are written to the DB.
        # The patient name comes from the test_callers mapping (phone → name).
        if not patient_context:
            # Look up the test patient name from test_callers by phone
            test_patient_name = "Test Patient"  # fallback
            for tc in (tenant_ctx.test_callers or []):
                if tc.get("phone") == caller_phone:
                    test_patient_name = tc.get("name", "Test Patient")
                    break
            else:
                # Fallback to legacy fields if no match in test_callers
                if body.test_patient_name:
                    test_patient_name = body.test_patient_name
                elif tenant_ctx.test_patient_name:
                    test_patient_name = tenant_ctx.test_patient_name
            logger.info("[Chat] Resolved test patient name '%s' for phone %s", test_patient_name, caller_phone)
            # For test mode, we create a NEW patient with no history.
            # This avoids confusion from fake appointments mixing with real ones.
            patient_context = {
                "patient": {
                    "name": test_patient_name,
                    "phone": caller_phone,
                    "dob": None,  # Unknown — agent must ASK for DOB
                    "is_new": True,  # New patient — no fake data
                    "visit_count": 0,
                    "preferred_type": None,  # Unknown — agent must ASK
                    "allergies": "",
                    "notes": "",
                },
                "upcoming_appointments": [],
                "past_appointments": [],
                "last_visit": None,
                "months_since_last_visit": None,
            }
            logger.info("[Chat] Built clean test patient context for phone %s (new patient, no fake history)",
                        caller_phone)

        llm_service.create_session(
            session_key,
            caller_number=caller_phone,
            tenant_ctx=tenant_ctx,
            patient_context=patient_context,
        )
        logger.info("[Chat] Pre-created session with test_caller_phone=%s patient=%s",
                    caller_phone,
                    patient_context["patient"]["name"] if patient_context else "new caller")

    logger.info(
        "[Chat] tenant=%s conv=%s msg=%r",
        current_user.slug, session_key, body.message[:120],
    )

    # True token-by-token streaming — the first token reaches the browser
    # in ~200-500ms instead of waiting 3-10s for the full response.
    token_stream = llm_service.process_message_stream(
        session_key, body.message, tenant_ctx=tenant_ctx,
    )

    return StreamingResponse(
        _stream_tokens_as_sse(token_stream, model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _session_key(user: Tenant, conversation_id: Optional[str], test_phone: Optional[str] = None) -> str:
    """
    Build a deterministic session key so multi-turn chats keep their history.
    Scoped per-tenant to prevent cross-tenant leakage in shared dev environments.
    Includes test_phone so switching callers creates a fresh session with correct patient context.
    """
    conv = conversation_id or "default"
    phone_suffix = f"-{test_phone}" if test_phone else ""
    return f"chat-{user.id}-{conv}{phone_suffix}"


async def _stream_tokens_as_sse(token_gen, model: str):
    """
    Wrap an async token generator into SSE chunks in OpenAI
    chat.completion.chunk format — identical wire format to Vapi.

    Unlike the old _stream_text_as_sse (which faked streaming by chopping a
    finished string into 3-word chunks), this yields REAL tokens as Ollama
    generates them — first token reaches the browser in ~200-500ms.
    """
    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())

    def _sse(delta, finish_reason=None):
        return "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish_reason}
            ],
        }) + "\n\n"

    # First chunk: role
    yield _sse({"role": "assistant"})

    # Content chunks: real tokens from the LLM
    async for token in token_gen:
        if token:
            yield _sse({"content": token})

    # Final chunk: finish_reason=stop
    yield _sse({}, finish_reason="stop")
    yield "data: [DONE]\n\n"
