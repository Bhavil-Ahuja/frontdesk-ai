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

from backend.config import settings
from backend.models.tenant import Tenant
from backend.services import auth_service, llm_service
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


class ChatEnabledResponse(BaseModel):
    enabled: bool


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/enabled", response_model=ChatEnabledResponse)
async def chat_enabled():
    """Public — lets the frontend decide whether to show the chat page."""
    return ChatEnabledResponse(enabled=settings.LOCAL_CHAT_MODE)


@router.post("/reset")
async def reset_chat(
    body: ChatRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """End the LLM session for this conversation_id (clears history)."""
    if not settings.LOCAL_CHAT_MODE:
        raise HTTPException(status_code=404, detail="Local chat mode is disabled.")
    session_key = _session_key(current_user, body.conversation_id)
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
    if not settings.LOCAL_CHAT_MODE:
        raise HTTPException(
            status_code=404,
            detail="Local chat mode is disabled. Set LOCAL_CHAT_MODE=true in .env.",
        )

    session_key = _session_key(current_user, body.conversation_id)
    model = settings.OLLAMA_MODEL

    # ── Resolve tenant context from the authenticated user ──────────────
    # This ensures all downstream service calls (SMS, calendar, etc.) use
    # the tenant's own credentials — NEVER the global .env fallback.
    tenant_ctx: TenantContext | None = await resolve_by_id(current_user.id)
    if not tenant_ctx:
        logger.warning("[Chat] No TenantContext for user %s — tools will be limited", current_user.slug)

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


def _session_key(user: Tenant, conversation_id: Optional[str]) -> str:
    """
    Build a deterministic session key so multi-turn chats keep their history.
    Scoped per-tenant to prevent cross-tenant leakage in shared dev environments.
    """
    conv = conversation_id or "default"
    return f"chat-{user.id}-{conv}"


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
