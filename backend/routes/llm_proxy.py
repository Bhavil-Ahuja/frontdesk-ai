"""
OpenAI-compatible LLM proxy endpoint for Vapi.

Multi-tenant: extracts the assistant_id from Vapi's request, resolves it to a
TenantContext, and threads that context through all service calls so each
tenant uses their own Twilio creds, timezone, KB, and prompts.

Architecture:
  1. Vapi sends conversation → we resolve tenant + inject tenant-specific system prompt
  2. We call Ollama (non-streaming) with tool definitions
  3. If Ollama requests a tool call → execute it → feed result back → call again
  4. Wrap the final text response as SSE stream for Vapi
     (Vapi REQUIRES streaming SSE from custom-llm providers)
"""

import json
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from openai import AsyncOpenAI, OpenAI

from backend.config import settings
from backend.prompts.agent_prompt import build_system_prompt
from backend.services.llm_service import get_tools
from backend.services import calendar_service, sms_service, patient_service
from backend.services.tenant_service import (
    resolve_by_assistant_id,
    resolve_by_phone_number_id,
    resolve_default_tenant,
    TenantContext,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["LLM Proxy"])

_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None

MAX_TOOL_ROUNDS = 5  # Safety limit: max tool call round-trips per request


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.ollama_openai_base,
            api_key="ollama",
        )
    return _client


def _get_async_client() -> AsyncOpenAI:
    """Async client for true token-by-token streaming to Vapi."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(
            base_url=settings.ollama_openai_base,
            api_key="ollama",
        )
    return _async_client


@router.post("/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI-compatible chat completions endpoint.
    Vapi sends the full conversation here; we resolve the tenant, inject
    the tenant-specific system prompt, forward to Ollama with tools,
    execute any tool calls, and return the final response as SSE stream.
    """
    try:
        body = await request.json()
    except Exception:
        logger.error("Failed to parse LLM proxy request body")
        return _error_response("Invalid request")

    messages = body.get("messages", [])
    model = body.get("model", settings.OLLAMA_MODEL)

    # ── Resolve tenant ────────────────────────────────────────────────
    # Priority: phoneNumberId (platform-managed model, 1 assistant + N numbers)
    #       →   assistantId   (legacy BYO model, N assistants)
    #       →   default tenant fallback
    call_data = body.get("call", {})
    phone_number_id = call_data.get("phoneNumberId", "") or ""
    assistant_id = (
        call_data.get("assistantId", "")
        or call_data.get("assistant", {}).get("id", "")
        or ""
    )

    tenant_ctx: TenantContext | None = None

    # 1. Try phone number first (platform-managed — 1 assistant, N phone numbers)
    if phone_number_id:
        tenant_ctx = await resolve_by_phone_number_id(phone_number_id)
        if tenant_ctx:
            logger.info("[LLM Proxy] Resolved tenant: %s (%s) from phoneNumberId=%s",
                        tenant_ctx.slug, tenant_ctx.business_name, phone_number_id)

    # 2. Fall back to assistant_id (legacy BYO model)
    if not tenant_ctx and assistant_id:
        tenant_ctx = await resolve_by_assistant_id(assistant_id)
        if tenant_ctx:
            logger.info("[LLM Proxy] Resolved tenant: %s (%s) from assistantId=%s",
                        tenant_ctx.slug, tenant_ctx.business_name, assistant_id)
        else:
            logger.warning("[LLM Proxy] No tenant for assistantId=%s or phoneNumberId=%s",
                           assistant_id, phone_number_id)

    # 3. Last resort — default tenant
    if not tenant_ctx:
        tenant_ctx = await resolve_default_tenant()
        if tenant_ctx:
            logger.info("[LLM Proxy] Using default tenant: %s (%s)", tenant_ctx.slug, tenant_ctx.business_name)

    # ── Extract caller phone from Vapi's request ────────────────────────
    caller_phone = (
        body.get("call", {}).get("customer", {}).get("number", "")
        or body.get("metadata", {}).get("caller_number", "")
        or ""
    )

    logger.info("[LLM Proxy] Received request: %d messages, model=%s, caller=%s, tenant=%s",
                len(messages), model, caller_phone or "unknown",
                tenant_ctx.slug if tenant_ctx else "none")

    # ── Caller recognition → patient context ────────────────────────────
    patient_context = None
    tenant_id = tenant_ctx.tenant_id if tenant_ctx else None
    if caller_phone:
        try:
            tz_name = tenant_ctx.timezone if tenant_ctx else None
            patient_context = await patient_service.get_patient_history(
                caller_phone, tenant_id=tenant_id, tz_name=tz_name,
            )
            if patient_context:
                pname = patient_context["patient"]["name"]
                visits = patient_context["patient"]["visit_count"]
                upcoming = len(patient_context.get("upcoming_appointments", []))
                logger.info(
                    "[LLM Proxy] 🎯 RETURNING PATIENT: %s (%d visits, %d upcoming appts)",
                    pname, visits, upcoming,
                )
            else:
                logger.info("[LLM Proxy] Caller %s not in patient DB (new caller)", caller_phone)
        except Exception as exc:
            logger.warning("[LLM Proxy] Patient lookup failed: %s", exc)

    # ALWAYS inject our full system prompt — replace Vapi's generic one
    system_prompt = build_system_prompt(
        patient_context=patient_context,
        tenant_ctx=tenant_ctx,
        caller_phone=caller_phone,
    )
    if messages and messages[0].get("role") == "system":
        vapi_prompt = messages[0].get("content", "")
        logger.info("[LLM Proxy] Replacing Vapi's system prompt (%d chars) with ours (%d chars)",
                    len(vapi_prompt), len(system_prompt))
        messages[0]["content"] = system_prompt
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})
        logger.info("[LLM Proxy] Injected system prompt (%d chars)", len(system_prompt))

    # Log conversation context
    logger.info("[LLM Proxy] ── Messages being sent to Ollama ──")
    for idx, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if role == "system":
            logger.info("[LLM Proxy]   [%d] %s: (%d chars — system prompt)", idx, role, len(content or ""))
        else:
            preview = (content or "")[:300]
            logger.info("[LLM Proxy]   [%d] %s: %s", idx, role, preview)
    logger.info("[LLM Proxy] ── End messages ──")

    client = _get_client()
    t0 = time.time()

    try:
        # ── Route-level escalation short-circuit ─────────────────────────
        # Only perform escalation if the tenant has configured emergency_guidance
        has_escalation = bool(tenant_ctx and tenant_ctx.emergency_guidance)
        if _is_explicit_human_request(messages) and has_escalation:
            logger.info("[LLM Proxy] Explicit human request detected at route level")
            try:
                await _execute_tool(
                    "escalate_to_human",
                    {"reason": "Patient explicitly asked to speak to a human"},
                    tenant_ctx=tenant_ctx,
                )
            except Exception as exc:
                logger.warning("[LLM Proxy] escalate_to_human side-effect failed: %s", exc)

            transfer_number = ""
            if tenant_ctx:
                transfer_number = (tenant_ctx.escalation_transfer_number or "").strip()
            else:
                transfer_number = (settings.ESCALATION_TRANSFER_NUMBER or "").strip()

            biz_name = tenant_ctx.business_name if tenant_ctx else settings.OFFICE_NAME

            if transfer_number:
                logger.info("[LLM Proxy] Live-transferring call to %s", transfer_number)
                return _stream_transfer_call(
                    "Of course — let me transfer you to one of our team members now. Please hold.",
                    transfer_number,
                    model,
                )
            else:
                logger.info("[LLM Proxy] No transfer number set — emitting callback + endCall")
                return _stream_text_then_end_call(
                    (
                        f"Of course. I've alerted our team and someone will call you back at "
                        f"this number very shortly. Thank you for calling {biz_name}. "
                        f"Have a great day."
                    ),
                    model,
                )
        elif _is_explicit_human_request(messages) and not has_escalation:
            logger.info("[LLM Proxy] Explicit human request detected but escalation not configured — skipping short-circuit")

        # ── True streaming: tokens flow to Vapi as Ollama generates them ──
        async_client = _get_async_client()
        return StreamingResponse(
            _stream_with_tools_sse(async_client, model, messages, t0, tenant_ctx=tenant_ctx),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except Exception as exc:
        # Catches errors BEFORE streaming starts (e.g. tenant resolution, client init)
        elapsed = (time.time() - t0) * 1000
        logger.error("[LLM Proxy] Request failed after %.0fms: %s", elapsed, exc, exc_info=True)
        return _stream_text_response(
            "I apologize, I'm having a brief technical difficulty. Could you repeat that?",
            model,
        )


def _stream_text_response(text: str, model: str) -> StreamingResponse:
    """
    Wrap a final text response as SSE stream that Vapi can consume.
    Sends the text in word-sized chunks to simulate natural streaming.
    """
    def generate():
        response_id = f"chatcmpl-{int(time.time())}"

        # First chunk: role
        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }) + "\n\n"

        # Content chunks: send a few words at a time for natural pacing
        words = text.split(" ")
        chunk_size = 3  # words per chunk
        for i in range(0, len(words), chunk_size):
            chunk_text = " ".join(words[i:i+chunk_size])
            if i > 0:
                chunk_text = " " + chunk_text
            yield "data: " + json.dumps({
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}],
            }) + "\n\n"

        # Final chunk: finish
        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }) + "\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def _stream_transfer_call(spoken_text: str, destination: str, model: str) -> StreamingResponse:
    """
    Emit a Vapi `transferCall` tool call as SSE so Vapi hands the call off
    to a real phone number.
    """
    def generate():
        response_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }) + "\n\n"

        words = spoken_text.split(" ")
        for i in range(0, len(words), 3):
            chunk_text = " ".join(words[i:i+3])
            if i > 0:
                chunk_text = " " + chunk_text
            yield "data: " + json.dumps({
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}],
            }) + "\n\n"

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": f"call_transfer_{created}",
                        "type": "function",
                        "function": {
                            "name": "transferCall",
                            "arguments": json.dumps({"destination": destination}),
                        },
                    }]
                },
                "finish_reason": None,
            }],
        }) + "\n\n"

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }) + "\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _stream_text_then_end_call(spoken_text: str, model: str) -> StreamingResponse:
    """
    Speak `spoken_text`, then emit a Vapi `endCall` tool call so the call
    hangs up cleanly.
    """
    def generate():
        response_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }) + "\n\n"

        words = spoken_text.split(" ")
        for i in range(0, len(words), 3):
            chunk_text = " ".join(words[i:i+3])
            if i > 0:
                chunk_text = " " + chunk_text
            yield "data: " + json.dumps({
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}],
            }) + "\n\n"

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": f"call_endcall_{created}",
                        "type": "function",
                        "function": {
                            "name": "endCall",
                            "arguments": "{}",
                        },
                    }]
                },
                "finish_reason": None,
            }],
        }) + "\n\n"

        yield "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }) + "\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _stream_with_tools_sse(
    client: AsyncOpenAI,
    model: str,
    messages: list,
    t0: float,
    tenant_ctx: TenantContext | None = None,
):
    """
    Async generator yielding SSE chunks with true token-by-token streaming.
    Handles tool calls internally — pauses SSE during tool execution, then
    streams the follow-up response. Vapi's TTS starts speaking as soon as
    the first token arrives (~200-500ms) instead of waiting for the full reply.
    """
    import re as _re

    response_id = f"chatcmpl-{int(time.time())}"
    created = int(time.time())

    def _sse(delta, finish_reason=None):
        return "data: " + json.dumps({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }) + "\n\n"

    # Role chunk
    yield _sse({"role": "assistant"})

    suppress_tools_round1 = _looks_like_simple_chat(messages)
    if suppress_tools_round1:
        logger.info("[LLM Proxy] Simple chat — suppressing tools for round 1 (stream)")

    full_content = ""

    try:
        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            logger.info("[LLM Proxy] ── Streaming round %d ──", round_num)

            use_tools = not (suppress_tools_round1 and round_num == 1)
            t_round = time.time()

            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1024,
                "stream": True,
            }
            if use_tools:
                kwargs["tools"] = get_tools(tenant_ctx)

            stream = await client.chat.completions.create(**kwargs)

            round_content = ""
            tool_calls_acc: dict[int, dict] = {}

            # <think> block suppression buffer
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

                # Already past the think block — yield immediately
                if flushing:
                    yield _sse({"content": token})
                    full_content += token
                    continue

                buf += token

                if "<think>" in buf:
                    if "</think>" in buf:
                        after = buf.split("</think>", 1)[1].lstrip()
                        if after:
                            yield _sse({"content": after})
                            full_content += after
                        buf = ""
                        flushing = True
                elif _has_tool_tag_start(buf):
                    # Don't yield tool call text — wait for closing tag
                    # Handles: <tool_call>, <function_call>, <|tool_call|>, etc.
                    if _has_tool_tag_end(buf):
                        # Strip the tool block, keep any text before/after
                        before, after = _strip_tool_block(buf)
                        if before.strip():
                            yield _sse({"content": before})
                            full_content += before
                        buf = after.lstrip()
                        # Don't set flushing yet — there might be more content
                    # else: keep buffering until we see closing tag
                elif len(buf) > 20:
                    yield _sse({"content": buf})
                    full_content += buf
                    buf = ""
                    flushing = True

            # Flush remaining buffer
            if buf and not flushing:
                clean = buf
                if "<think>" in clean:
                    clean = _re.sub(r"<think>.*?</think>\s*", "", clean, flags=_re.DOTALL).strip()
                if clean:
                    yield _sse({"content": clean})
                    full_content += clean

            # ── Detect text-based tool calls (Qwen3 quirk) ────────────────
            # Sometimes models output <tool_call>...</tool_call> (or similar) as text
            # instead of using the proper function calling API. Parse and execute.
            if _has_tool_tag_start(round_content) and _has_tool_tag_end(round_content):
                parsed = _parse_tool_call_text(round_content)
                if parsed:
                    logger.warning("[LLM Proxy]   ⚠️ Text-based tool call detected: %s — executing", parsed["name"])
                    # Inject into tool_calls_acc so it gets executed
                    tool_calls_acc[0] = {
                        "id": f"text_tc_{round_num}",
                        "name": parsed["name"],
                        "arguments": json.dumps(parsed["arguments"]),
                    }

            round_ms = (time.time() - t_round) * 1000
            logger.info("[LLM Proxy]   Round %d: %.0fms, content=%d chars, tool_calls=%d",
                        round_num, round_ms, len(round_content), len(tool_calls_acc))

            if not tool_calls_acc:
                if round_content:
                    logger.info("[LLM Proxy]   Round %d → streamed: %s", round_num, round_content[:200])
                break

            # ── Execute tool calls ────────────────────────────────────
            for idx in sorted(tool_calls_acc.keys()):
                tc_info = tool_calls_acc[idx]
                fn_name = tc_info["name"]
                try:
                    fn_args = json.loads(tc_info["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                logger.info("[LLM Proxy]   🔧 TOOL: %s(%s)", fn_name, json.dumps(fn_args)[:300])

                # Date correction for get_available_slots
                if fn_name == "get_available_slots":
                    user_text = _last_user_message(messages)
                    tenant_tz = tenant_ctx.timezone if tenant_ctx else "America/Chicago"
                    resolved = _resolve_dow_to_date(user_text, tz_name=tenant_tz)
                    model_date = fn_args.get("date", "")
                    if resolved and resolved != model_date:
                        logger.warning("[LLM Proxy]   📅 Date correction: %r → %r",
                                       model_date, resolved)
                        fn_args["date"] = resolved

                tool_result = await _execute_tool(fn_name, fn_args, tenant_ctx=tenant_ctx)
                logger.info("[LLM Proxy]   🔧 RESULT: %s",
                            json.dumps(tool_result, default=str)[:500])

                messages.append({
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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_info["id"],
                    "content": json.dumps(tool_result, default=str),
                })

    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        logger.error("[LLM Proxy] Streaming failed after %.0fms: %s", elapsed, exc, exc_info=True)
        yield _sse({"content": "I apologize, I'm having a brief technical difficulty. Could you repeat that?"})

    elapsed = (time.time() - t0) * 1000
    logger.info("=" * 70)
    logger.info("[LLM Proxy] STREAMED RESPONSE TO VAPI")
    logger.info("[LLM Proxy]   Total time:   %.0fms", elapsed)
    logger.info("[LLM Proxy]   Content len:  %d chars", len(full_content))
    logger.info("[LLM Proxy]   Content:      %s", full_content[:500])
    logger.info("=" * 70)

    yield _sse({}, finish_reason="stop")
    yield "data: [DONE]\n\n"


def _error_response(msg: str) -> dict:
    """Return an OpenAI-format error response."""
    return {
        "id": "error",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": msg}, "finish_reason": "stop"}],
    }


_DOW_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


# ── Tool call text detection (for models that output tool calls as text) ─────
# Some models (Qwen3, etc.) sometimes output tool calls as text instead of using
# the proper function calling API. These helpers detect and strip such patterns.

_TOOL_TAG_PATTERNS = [
    ("<tool_call>", "</tool_call>"),
    ("<function_call>", "</function_call>"),
    ("<|tool_call|>", "<|/tool_call|>"),
    ("<|function|>", "<|/function|>"),
    ("<tool>", "</tool>"),
    ("<function>", "</function>"),
]


def _has_tool_tag_start(text: str) -> bool:
    """Check if text contains the start of any tool call tag pattern."""
    return any(start in text for start, _ in _TOOL_TAG_PATTERNS)


def _has_tool_tag_end(text: str) -> bool:
    """Check if text contains the end of any tool call tag pattern."""
    return any(end in text for _, end in _TOOL_TAG_PATTERNS)


def _strip_tool_block(text: str) -> tuple[str, str]:
    """
    Strip a tool call block from text, returning (before, after).
    Handles multiple tag formats.
    """
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
    import re as _re_mod
    for start_tag, end_tag in _TOOL_TAG_PATTERNS:
        pattern = _re_mod.escape(start_tag) + r"\s*(\{.*?\})\s*" + _re_mod.escape(end_tag)
        match = _re_mod.search(pattern, text, _re_mod.DOTALL)
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


def _last_user_message(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip().lower()
    return ""


_HUMAN_REQUEST_PHRASES = [
    "speak to a human", "speak with a human", "talk to a human",
    "real person", "real human", "speak to someone",
    "transfer me", "transfer to a", "human receptionist",
    "speak to a person", "talk to a person",
]


def _is_explicit_human_request(messages: list) -> bool:
    user_text = _last_user_message(messages)
    return any(p in user_text for p in _HUMAN_REQUEST_PHRASES)


def _resolve_dow_to_date(user_text: str, tz_name: str = "America/Chicago") -> str | None:
    """
    If the user's message mentions a day-of-week or 'tomorrow'/'today',
    return the corresponding YYYY-MM-DD in the tenant's timezone.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo
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


def _looks_like_simple_chat(messages: list) -> bool:
    """
    Heuristic: detect short greetings / generic small-talk where the model
    should NOT have tools available.

    CRITICAL: Only applies to the FIRST user message. Once a multi-turn
    conversation is underway, tools must ALWAYS be available — the user
    might respond with short answers like "doc1", "yes", "2pm" that need tools.
    """
    # Count user messages — if more than 1, conversation is in progress
    user_msg_count = sum(1 for m in messages if m.get("role") == "user")
    if user_msg_count > 1:
        return False

    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = (m.get("content") or "").strip().lower()
            break

    if not last_user:
        return False

    if len(last_user) > 80:
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
        # Patient lookup
        "my appointment", "existing", "upcoming", "check on",
        "do i have", "any appointment", "look up", "find my",
    ]
    if any(kw in last_user for kw in tool_keywords):
        return False

    return True


async def _call_with_tools(
    client: OpenAI,
    model: str,
    messages: list,
    t0: float,
    tenant_ctx: TenantContext | None = None,
) -> str:
    """
    Call Ollama with tool definitions. If it requests a tool call,
    execute it, add the result to messages, and call again.
    """
    content = ""

    # ── Deterministic escalation short-circuit ──────────────────────────
    has_escalation = bool(tenant_ctx and tenant_ctx.emergency_guidance)
    if _is_explicit_human_request(messages) and has_escalation:
        logger.info("[LLM Proxy] Explicit human request — short-circuiting LLM in _call_with_tools")
        try:
            await _execute_tool(
                "escalate_to_human",
                {"reason": "Patient explicitly asked to speak to a human"},
                tenant_ctx=tenant_ctx,
            )
        except Exception as exc:
            logger.warning("[LLM Proxy] escalate_to_human side-effect failed: %s", exc)
        return "Of course — let me connect you with one of our team members. Please hold."
    elif _is_explicit_human_request(messages) and not has_escalation:
        logger.info("[LLM Proxy] Explicit human request but escalation not configured — skipping short-circuit")

    suppress_tools_round1 = _looks_like_simple_chat(messages)
    if suppress_tools_round1:
        logger.info("[LLM Proxy] Detected simple chat — suppressing tools for round 1")

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        logger.info("[LLM Proxy] ── LLM call round %d ──", round_num)

        use_tools = not (suppress_tools_round1 and round_num == 1)

        t_round = time.time()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": False,
        }
        if use_tools:
            kwargs["tools"] = get_tools(tenant_ctx)
        response = client.chat.completions.create(**kwargs)
        round_ms = (time.time() - t_round) * 1000

        choice = response.choices[0]
        content = choice.message.content or ""
        finish = choice.finish_reason

        # Strip Qwen3 thinking blocks
        if "<think>" in content:
            import re
            content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
            logger.info("[LLM Proxy]   Stripped <think> block, post-strip=%d chars", len(content))

        logger.info("[LLM Proxy]   Round %d: %.0fms, finish=%s, content=%d chars, tool_calls=%s",
                    round_num, round_ms, finish, len(content), bool(choice.message.tool_calls))

        if not choice.message.tool_calls:
            if content:
                logger.info("[LLM Proxy]   Round %d → text response: %s", round_num, content[:200])
            return content

        # ── Handle tool calls ────────────────────────────────────────
        for tc in choice.message.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logger.info("[LLM Proxy]   🔧 TOOL CALL: %s(%s)", fn_name, json.dumps(fn_args)[:300])

            # ── Correct date if user said a day-of-week ──
            if fn_name == "get_available_slots":
                user_text = _last_user_message(messages)
                tenant_tz = tenant_ctx.timezone if tenant_ctx else "America/Chicago"
                resolved = _resolve_dow_to_date(user_text, tz_name=tenant_tz)
                model_date = fn_args.get("date", "")
                if resolved and resolved != model_date:
                    logger.warning("[LLM Proxy]   📅 Date correction: model said %r → user-implied %r",
                                   model_date, resolved)
                    fn_args["date"] = resolved

            tool_result = await _execute_tool(fn_name, fn_args, tenant_ctx=tenant_ctx)

            logger.info("[LLM Proxy]   🔧 TOOL RESULT: %s", json.dumps(tool_result, default=str)[:500])

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": tc.function.arguments,
                        },
                    }
                ],
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result, default=str),
            })

    logger.warning("[LLM Proxy] Exceeded %d tool rounds — returning last content", MAX_TOOL_ROUNDS)
    return content or "I apologize, I'm having difficulty processing your request. Could you repeat that?"


async def _execute_tool(
    name: str,
    args: dict,
    tenant_ctx: TenantContext | None = None,
) -> dict[str, Any]:
    """
    Execute a tool call and return the result dict.
    Uses tenant_ctx for per-tenant API keys, event types, etc.
    """
    t0 = time.time()
    logger.info("[Tool Exec] Executing: %s (tenant=%s)", name,
                tenant_ctx.slug if tenant_ctx else "default")

    try:
        if name == "get_available_slots":
            appt_type = args.get("appointment_type", "consultation")

            date = args.get("date", "")
            if not date:
                from datetime import timedelta
                date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            slots = await calendar_service.get_available_slots(
                date_from=date,
                date_to=date,
                tenant_ctx=tenant_ctx,
                appointment_type_key=appt_type,
            )

            formatted_slots = []
            for s in slots:
                try:
                    from dateutil import parser as dt_parser
                    dt = dt_parser.parse(s)
                    formatted_slots.append({
                        "time_label": dt.strftime("%I:%M %p").lstrip("0"),
                        "exact_slot_time": s,
                    })
                except Exception:
                    formatted_slots.append({"time_label": s, "exact_slot_time": s})

            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] get_available_slots → %d slots in %.0fms", len(slots), elapsed)

            from dateutil import parser as dt_parser
            try:
                friendly_date = dt_parser.parse(date).strftime("%A, %B %d")
            except Exception:
                friendly_date = date

            if not formatted_slots:
                summary = (
                    f"There are no available appointment slots on {friendly_date}. "
                    f"Tell the patient politely that day is fully booked or closed, "
                    f"and offer to check a different day. Do NOT read this message verbatim — "
                    f"speak naturally in 1-2 sentences."
                )
            else:
                top = formatted_slots[:3]
                time_list = ", ".join(s["time_label"] for s in top)
                summary = (
                    f"Available times on {friendly_date}: {time_list}. "
                    f"Offer these to the patient in natural conversation (1-2 sentences). "
                    f"When they pick one, call book_appointment with the matching exact_slot_time. "
                    f"Include provider_id if the patient chose a specific provider. "
                    f"Do NOT read JSON or field names aloud."
                )

            return {
                "summary_for_assistant": summary,
                "available_slots": formatted_slots,
                "date": date,
                "count": len(slots),
            }

        elif name == "book_appointment":
            # ── Validate provider_id is present ──────────────────────
            if not args.get("provider_id", "").strip():
                logger.warning("[Tool Exec] book_appointment rejected — no provider_id")
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
                logger.warning("[Tool Exec] book_appointment rejected — missing: %s",
                               [f for f, _ in missing])
                return {
                    "ok": False,
                    "error": "missing_required_fields",
                    "missing": [f for f, _ in missing],
                    "summary_for_assistant": (
                        f"Cannot book yet — missing: {missing_list}. "
                        f"Ask the patient ONLY for the missing items above in a natural sentence."
                    ),
                }

            appt_type = args.get("appointment_type", "new_patient")

            # Email: leave blank if patient didn't provide one
            email = args.get("email", "") or ""

            # Provider: look up name for confirmation message
            provider_id_str = args.get("provider_id", "")
            provider_id = None
            provider_name = None
            if provider_id_str:
                try:
                    from backend.services import provider_service
                    import uuid as uuid_mod
                    provider_id = uuid_mod.UUID(provider_id_str)
                    provider = await provider_service.get_provider(provider_id)
                    if provider:
                        provider_name = provider.get("name", "")
                        logger.info("[Tool Exec] Provider selected: %s (%s)", provider_name, provider_id)
                except Exception as prov_exc:
                    logger.warning("[Tool Exec] Provider lookup failed: %s", prov_exc)

            patient_info = {
                "name": args.get("patient_name", ""),
                "phone": args.get("phone", ""),
                "email": email,
                "dob": args.get("dob", ""),
            }

            slot_time = args.get("slot_time", "")

            # ── Smart slot matching ──────────────────────────────────
            logger.info("[Tool Exec] LLM provided slot_time: '%s' — will attempt smart matching", slot_time)
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
                        break

                if not matched:
                    for real_slot in available:
                        slot_dt = dt_parser.parse(real_slot)
                        if slot_dt.hour == target_hour:
                            slot_time = real_slot
                            matched = True
                            break

            except Exception as match_exc:
                logger.warning("[Tool Exec] Slot matching failed: %s — using original", match_exc)

            result = await calendar_service.book_appointment(
                patient_info=patient_info,
                start_time=slot_time,
                tenant_ctx=tenant_ctx,
                appointment_type_key=appt_type,
            )

            if result:
                # Send SMS confirmation
                try:
                    scheduled_dt = datetime.fromisoformat(args.get("slot_time", ""))
                    sms_service.send_confirmation(
                        patient_name=args.get("patient_name", ""),
                        phone=args.get("phone", ""),
                        appointment_type=args.get("appointment_type", "").replace("_", " ").title(),
                        scheduled_at=scheduled_dt,
                        tenant_ctx=tenant_ctx,
                    )
                except Exception as sms_exc:
                    logger.warning("[Tool Exec] SMS failed: %s", sms_exc)

                # Upsert patient + record appointment in DB
                try:
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
                    logger.info("[Tool Exec] Appointment recorded in DB (uid=%s, provider=%s)",
                                booking_uid, provider_id)
                except Exception as db_exc:
                    logger.warning("[Tool Exec] Patient/appointment DB upsert failed: %s", db_exc)

                elapsed = (time.time() - t0) * 1000
                logger.info("[Tool Exec] book_appointment → SUCCESS in %.0fms: %s", elapsed, result)
                return {"success": True, "booking": result}

            elapsed = (time.time() - t0) * 1000
            logger.error("[Tool Exec] book_appointment → FAILED in %.0fms", elapsed)
            return {"success": False, "error": "Failed to create booking."}

        elif name == "reschedule_appointment":
            booking_uid = args.get("booking_uid", "")
            new_slot_time = args.get("new_slot_time", "")
            result = await calendar_service.reschedule_appointment(
                booking_uid=booking_uid,
                new_start_time=new_slot_time,
                tenant_ctx=tenant_ctx,
            )
            elapsed = (time.time() - t0) * 1000
            if result:
                # Send reschedule SMS
                try:
                    from dateutil import parser as dt_parser
                    new_dt = dt_parser.parse(new_slot_time)
                    sms_service.send_reschedule(
                        patient_name="",  # not available in Vapi context
                        phone="",
                        new_scheduled_at=new_dt,
                        appointment_type="Appointment",
                        tenant_ctx=tenant_ctx,
                    )
                except Exception as sms_exc:
                    logger.warning("[Tool Exec] Reschedule SMS failed: %s", sms_exc)
                # Update DB
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
                            logger.info("[Tool Exec] ✓ DB appointment rescheduled: %s", booking_uid)
                except Exception as db_exc:
                    logger.warning("[Tool Exec] DB reschedule update failed: %s", db_exc)
                logger.info("[Tool Exec] reschedule → SUCCESS in %.0fms", elapsed)
                return {"success": True, "reschedule": result}
            logger.error("[Tool Exec] reschedule → FAILED in %.0fms", elapsed)
            return {"success": False, "error": "Failed to reschedule"}

        elif name == "cancel_appointment":
            booking_uid = args.get("booking_uid", "")
            success = await calendar_service.cancel_appointment(
                booking_uid=booking_uid,
                reason=args.get("reason", ""),
                tenant_ctx=tenant_ctx,
            )
            if success:
                # Update DB status
                try:
                    from backend.database import async_session as get_async_session
                    from sqlalchemy import select as sa_select
                    from backend.models.appointment import Appointment as ApptModel, AppointmentStatus
                    async with get_async_session() as db_session:
                        stmt = sa_select(ApptModel).where(ApptModel.cal_booking_uid == booking_uid)
                        db_result = await db_session.execute(stmt)
                        appt = db_result.scalar_one_or_none()
                        if appt:
                            appt.status = AppointmentStatus.CANCELLED
                            await db_session.commit()
                            logger.info("[Tool Exec] ✓ DB appointment cancelled: %s", booking_uid)
                except Exception as db_exc:
                    logger.warning("[Tool Exec] DB cancel update failed: %s", db_exc)
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] cancel → %s in %.0fms", success, elapsed)
            return {"success": success}

        elif name == "escalate_to_human":
            sms_service.send_office_alert(
                reason=args.get("reason", "Patient requested human assistance"),
                caller_number="unknown",
                tenant_ctx=tenant_ctx,
            )
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] escalate → done in %.0fms", elapsed)
            return {"success": True, "action": "transfer"}

        elif name == "send_callback_request":
            sms_service.send_escalation_notification(
                patient_name=args.get("patient_name", ""),
                phone=args.get("phone", ""),
                tenant_ctx=tenant_ctx,
            )
            sms_service.send_office_alert(
                reason=f"Callback: {args.get('reason', 'N/A')}",
                caller_number=args.get("phone", ""),
                tenant_ctx=tenant_ctx,
            )
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] callback → done in %.0fms", elapsed)
            return {"success": True, "message": "Callback request sent"}

        elif name == "get_office_info":
            from backend.services.llm_service import _build_office_info
            result = _build_office_info(args.get("topic", "all"), tenant_ctx)
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] get_office_info(%s) → done in %.0fms", args.get("topic"), elapsed)
            return result

        elif name == "lookup_patient_appointments":
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
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] lookup_patient_appointments → %d upcoming for %s in %.0fms",
                        len(upcoming), patient_name, elapsed)

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

            appt_lines = []
            for a in upcoming:
                appt_lines.append(f"{a['type']} on {a['date']} at {a['time']}")

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
            result = await waitlist_service.add_to_waitlist(
                tenant_id=tenant_ctx.tenant_id if tenant_ctx else None,
                patient_name=args.get("patient_name", ""),
                patient_phone=args.get("phone", ""),
                appointment_type=args.get("appointment_type", "consultation"),
                preferred_date=args.get("preferred_date", ""),
            )
            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] add_to_waitlist → %s in %.0fms", result.get("status"), elapsed)
            return result

        elif name == "lookup_patient":
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

            # Fallback: search by name
            if not history and patient_name:
                patient_record = await patient_service.get_patient_by_name(
                    patient_name, tenant_id=tenant_id,
                )
                if patient_record:
                    history = await patient_service.get_patient_history(
                        patient_record.phone, tenant_id=tenant_id, tz_name=tz_name,
                    )

            if not history:
                elapsed = (time.time() - t0) * 1000
                logger.info("[Tool Exec] lookup_patient → not found in %.0fms (phone=%s, name=%s)",
                            elapsed, phone, patient_name)
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
            logger.info("[Tool Exec] lookup_patient → found %s (%d upcoming, %d past) in %.0fms",
                        p['name'], len(upcoming), len(past), elapsed)
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
            phone = args.get("phone", "")
            if not phone:
                return {
                    "ok": False,
                    "summary_for_assistant": "I need the patient's phone number to update their record.",
                }

            tenant_id = tenant_ctx.tenant_id if tenant_ctx else None

            existing = await patient_service.get_patient_by_phone(phone, tenant_id=tenant_id)
            if not existing:
                return {
                    "ok": False,
                    "summary_for_assistant": (
                        f"No patient record found for {phone}. Cannot update a non-existent record. "
                        "If this is a new patient, their record will be created when you book their appointment."
                    ),
                }

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
            logger.info("[Tool Exec] update_patient_info → updated %s for %s in %.0fms",
                        updated_fields, phone, elapsed)
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
                summary = "This practice doesn't have individual provider profiles configured. Any available provider can see the patient."
            else:
                names = ", ".join(f"{p['name']} ({p.get('title', '')})" for p in providers)
                summary = f"Available providers: {names}. Ask the patient if they have a preference, or offer the first available."

            elapsed = (time.time() - t0) * 1000
            logger.info("[Tool Exec] get_providers → %d providers in %.0fms", len(providers), elapsed)
            return {
                "summary_for_assistant": summary,
                "providers": providers,
                "count": len(providers),
            }

        else:
            logger.warning("[Tool Exec] Unknown tool: %s", name)
            return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        logger.error("[Tool Exec] %s failed after %.0fms: %s", name, elapsed, exc, exc_info=True)
        return {"error": str(exc)}
