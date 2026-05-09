"""
SMS conversation history API routes.

GET /api/sms/conversations  -> list unique patient phone conversations
GET /api/sms/messages       -> list messages (optionally filtered by patient_phone)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.tenant import Tenant
from backend.models.sms_message import SMSMessage, SMSDirection
from backend.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sms", tags=["SMS"])


@router.get("/conversations")
async def list_conversations(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    List unique SMS conversations grouped by patient phone number.
    Returns: patient_phone, message_count, last_message_at, last_message_body, last_direction
    """
    logger.info("[SMS] Listing conversations for tenant=%s", current_user.slug)
    async with async_session() as session:
        # Subquery to get per-phone aggregates
        stmt = (
            select(
                SMSMessage.patient_phone,
                func.count(SMSMessage.id).label("message_count"),
                func.max(SMSMessage.created_at).label("last_message_at"),
            )
            .where(SMSMessage.tenant_id == current_user.id)
            .group_by(SMSMessage.patient_phone)
            .order_by(desc(func.max(SMSMessage.created_at)))
        )
        result = await session.execute(stmt)
        rows = result.all()

        conversations = []
        for row in rows:
            # Fetch the last message for preview
            last_msg_stmt = (
                select(SMSMessage)
                .where(
                    and_(
                        SMSMessage.tenant_id == current_user.id,
                        SMSMessage.patient_phone == row.patient_phone,
                    )
                )
                .order_by(desc(SMSMessage.created_at))
                .limit(1)
            )
            last_msg_result = await session.execute(last_msg_stmt)
            last_msg = last_msg_result.scalar_one_or_none()

            conversations.append({
                "patient_phone": row.patient_phone,
                "message_count": row.message_count,
                "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
                "last_message_body": (last_msg.body[:100] + "..." if len(last_msg.body) > 100 else last_msg.body) if last_msg else "",
                "last_direction": last_msg.direction.value if last_msg else None,
            })

        return conversations


@router.get("/messages")
async def list_messages(
    patient_phone: str = Query(..., description="Patient phone number to filter by"),
    limit: int = Query(100, ge=1, le=500),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """List SMS messages for a specific patient phone, ordered oldest first."""
    logger.info("[SMS] Listing messages for tenant=%s patient=%s", current_user.slug, patient_phone)
    async with async_session() as session:
        stmt = (
            select(SMSMessage)
            .where(
                and_(
                    SMSMessage.tenant_id == current_user.id,
                    SMSMessage.patient_phone == patient_phone,
                )
            )
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
