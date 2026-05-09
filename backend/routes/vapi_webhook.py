"""
Vapi webhook route — receives all call events from Vapi.ai and routes them
through the vapi_service for processing.

Multi-tenant: resolves the tenant from the assistant_id in the call data
and scopes all DB writes (calls, patients) to that tenant.

POST /webhook/vapi
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.call import Call, CallOutcome
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia
from backend.models.patient import Patient
from backend.services import vapi_service, llm_service
from backend.services.tenant_service import resolve_by_assistant_id, resolve_by_phone_number_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vapi Webhook"])


@router.post("/webhook/vapi")
async def vapi_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Main Vapi webhook endpoint. Handles all event types.
    Resolves tenant from call.assistantId for scoped DB writes.
    """
    try:
        payload = await request.json()
    except Exception:
        logger.error("Failed to parse Vapi webhook JSON body.")
        return Response(status_code=400, content="Invalid JSON")

    message = payload.get("message", {})
    event_type = message.get("type", "")
    call_data = message.get("call", {})
    call_id = call_data.get("id", "")

    # ── Resolve tenant (phoneNumberId first, then assistantId) ──────────
    phone_number_id = call_data.get("phoneNumberId", "") or ""
    assistant_id = call_data.get("assistantId", "") or call_data.get("assistant", {}).get("id", "")
    tenant_ctx = None
    tenant_id = None

    if phone_number_id:
        tenant_ctx = await resolve_by_phone_number_id(phone_number_id)
    if not tenant_ctx and assistant_id:
        tenant_ctx = await resolve_by_assistant_id(assistant_id)
    if tenant_ctx:
        tenant_id = tenant_ctx.tenant_id
        logger.info("[Webhook] Resolved tenant: %s for call %s", tenant_ctx.slug, call_id)

    # ── Route through vapi_service ────────────────────────────────────────
    result = await vapi_service.handle_webhook(payload)

    # ── Persist call start to DB ──────────────────────────────────────────
    if event_type == "status-update" and message.get("status") == "in-progress" and call_id:
        existing = await db.execute(
            select(Call).where(Call.vapi_call_id == call_id)
        )
        if existing.scalar_one_or_none() is None:
            caller_number = call_data.get("customer", {}).get("number", "")
            new_call = Call(
                tenant_id=tenant_id,
                vapi_call_id=call_id,
                caller_number=caller_number,
                started_at=datetime.now(timezone.utc),
                outcome=None,
                transcript=[],
            )
            db.add(new_call)
            await db.flush()
            logger.info("Call record created: %s (tenant=%s)", call_id, tenant_id)

    # ── Persist call end to DB ────────────────────────────────────────────
    if event_type == "end-of-call-report" and call_id:
        await _persist_call_end(db, call_id, message, tenant_id=tenant_id)

    return result


async def _persist_call_end(
    db: AsyncSession,
    call_id: str,
    message: dict,
    tenant_id: uuid.UUID | None = None,
):
    """Save final call data: transcript, duration, outcome, and any appointments."""
    try:
        stmt = select(Call).where(Call.vapi_call_id == call_id)
        row = await db.execute(stmt)
        call = row.scalar_one_or_none()
        if call is None:
            logger.warning("Call %s not found in DB for end-of-call report.", call_id)
            return

        # Update call record
        call.ended_at = datetime.now(timezone.utc)
        call.duration_seconds = message.get("durationSeconds", 0)
        call.summary = message.get("summary", "")

        # Build transcript from messages
        raw_messages = message.get("messages", [])
        transcript_entries = []
        for msg in raw_messages:
            transcript_entries.append({
                "role": msg.get("role", ""),
                "content": msg.get("content", msg.get("message", "")),
                "timestamp": msg.get("time", datetime.now(timezone.utc).isoformat()),
            })
        call.transcript = transcript_entries

        # Determine outcome from session state / messages
        session = llm_service.get_session(call_id)
        if session and session.get("current_state") == "escalated":
            call.outcome = CallOutcome.ESCALATED
        elif any("book" in str(m.get("content", "")).lower() for m in raw_messages if m.get("role") == "assistant"):
            call.outcome = CallOutcome.BOOKED
        else:
            ended_reason = message.get("endedReason", "")
            if ended_reason in ("customer-ended-call", "assistant-ended-call"):
                call.outcome = CallOutcome.INQUIRY
            else:
                call.outcome = CallOutcome.ABANDONED

        # Persist any appointment data from the session
        if session and session.get("patient_info"):
            info = session["patient_info"]
            if info.get("name"):
                await _upsert_patient(db, info, tenant_id=tenant_id)

        await db.flush()
        logger.info("Call %s persisted: outcome=%s duration=%ds tenant=%s",
                     call_id, call.outcome, call.duration_seconds or 0, tenant_id)

        # Clean up session
        llm_service.end_session(call_id)

    except Exception as exc:
        logger.error("Error persisting call end for %s: %s", call_id, exc, exc_info=True)


async def _upsert_patient(
    db: AsyncSession,
    info: dict,
    tenant_id: uuid.UUID | None = None,
):
    """Create or update a patient record scoped to a tenant."""
    phone = info.get("phone", "")
    if not phone:
        return

    from sqlalchemy import and_
    filters = [Patient.phone == phone]
    if tenant_id:
        filters.append(Patient.tenant_id == tenant_id)

    stmt = select(Patient).where(and_(*filters))
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()

    if patient is None:
        patient = Patient(
            tenant_id=tenant_id,
            name=info.get("name", ""),
            phone=phone,
            email=info.get("email"),
            date_of_birth=info.get("dob"),
            insurance_provider=info.get("insurance"),
            is_new_patient=True,
        )
        db.add(patient)
    else:
        patient.name = info.get("name", patient.name)
        patient.email = info.get("email") or patient.email
        patient.insurance_provider = info.get("insurance") or patient.insurance_provider
        patient.is_new_patient = False

    await db.flush()
