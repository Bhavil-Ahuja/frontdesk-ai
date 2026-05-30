"""
SMS conversation history API routes.

GET /api/sms/conversations  -> list unique patient phone conversations
GET /api/sms/messages       -> list messages (optionally filtered by patient_phone)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, and_, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.tenant import Tenant
from backend.models.patient import Patient
from backend.models.sms_message import SMSMessage, SMSDirection
from backend.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sms", tags=["SMS"])


@router.get("/conversations")
async def list_conversations(
    search: str = Query("", description="Search by patient name or phone number"),
    include_test: bool = Query(False, description="Include test/demo SMS data"),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    List unique SMS conversations grouped by patient phone number.
    Returns: patient_phone, patient_name, message_count, last_message_at,
             last_message_body, last_direction
    """
    logger.info("[SMS] Listing conversations for tenant=%s include_test=%s search=%r",
                current_user.slug, include_test, search)
    async with async_session() as session:
        # Build base filters
        sms_filters = [SMSMessage.tenant_id == current_user.id]
        if not include_test:
            sms_filters.append(SMSMessage.is_test == False)  # noqa: E712

        # Subquery to get per-phone aggregates
        stmt = (
            select(
                SMSMessage.patient_phone,
                func.count(SMSMessage.id).label("message_count"),
                func.max(SMSMessage.created_at).label("last_message_at"),
            )
            .where(and_(*sms_filters))
            .group_by(SMSMessage.patient_phone)
            .order_by(desc(func.max(SMSMessage.created_at)))
        )
        result = await session.execute(stmt)
        rows = result.all()

        # Build a phone → patient_name mapping via a single query
        phone_list = [row.patient_phone for row in rows]
        patient_name_map: dict[str, str] = {}
        if phone_list:
            patient_stmt = (
                select(Patient.phone, Patient.name)
                .where(
                    and_(
                        Patient.tenant_id == current_user.id,
                        Patient.phone.in_(phone_list),
                    )
                )
            )
            patient_result = await session.execute(patient_stmt)
            for p_row in patient_result.all():
                patient_name_map[p_row.phone] = p_row.name

        # Apply search filter (by name or phone) after gathering data
        search_term = search.strip().lower() if search else ""

        conversations = []
        for row in rows:
            patient_name = patient_name_map.get(row.patient_phone, None)

            # Filter by search term if provided
            if search_term:
                phone_match = search_term in (row.patient_phone or "").lower()
                name_match = patient_name and search_term in patient_name.lower()
                if not phone_match and not name_match:
                    continue

            # Fetch the last message for preview (respecting test filter)
            preview_filters = [
                SMSMessage.tenant_id == current_user.id,
                SMSMessage.patient_phone == row.patient_phone,
            ]
            if not include_test:
                preview_filters.append(SMSMessage.is_test == False)  # noqa: E712
            last_msg_stmt = (
                select(SMSMessage)
                .where(and_(*preview_filters))
                .order_by(desc(SMSMessage.created_at))
                .limit(1)
            )
            last_msg_result = await session.execute(last_msg_stmt)
            last_msg = last_msg_result.scalar_one_or_none()

            conversations.append({
                "patient_phone": row.patient_phone,
                "patient_name": patient_name,
                "message_count": row.message_count,
                "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
                "last_message_body": (last_msg.body[:100] + "..." if len(last_msg.body) > 100 else last_msg.body) if last_msg else "",
                "last_direction": last_msg.direction.value if last_msg else None,
            })

        return conversations


@router.get("/messages")
async def list_messages(
    patient_phone: str = Query(..., description="Patient phone number to filter by"),
    include_test: bool = Query(False, description="Include test/demo SMS data"),
    limit: int = Query(100, ge=1, le=500),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """List SMS messages for a specific patient phone, ordered oldest first."""
    logger.info("[SMS] Listing messages for tenant=%s patient=%s include_test=%s", current_user.slug, patient_phone, include_test)
    async with async_session() as session:
        msg_filters = [
            SMSMessage.tenant_id == current_user.id,
            SMSMessage.patient_phone == patient_phone,
        ]
        if not include_test:
            msg_filters.append(SMSMessage.is_test == False)  # noqa: E712

        stmt = (
            select(SMSMessage)
            .where(and_(*msg_filters))
            .order_by(SMSMessage.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        messages = result.scalars().all()

        return [
            {
                "id": str(msg.id),
                "direction": msg.direction.value,
                "from_number": msg.from_number,
                "to_number": msg.to_number,
                "body": msg.body,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ]
