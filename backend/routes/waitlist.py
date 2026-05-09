"""
Waitlist management API routes.

GET    /api/waitlist              -> list waitlist entries for the tenant
DELETE /api/waitlist/{entry_id}   -> cancel a waitlist entry
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.models.tenant import Tenant
from backend.services import auth_service, waitlist_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/waitlist", tags=["Waitlist"])


# -- Routes --------------------------------------------------------------------


@router.get("")
async def list_waitlist_entries(
    status: Optional[str] = Query(None, description="Filter by waitlist entry status"),
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """List waitlist entries for the authenticated tenant, with optional filters."""
    logger.info("[Waitlist] Listing entries for tenant=%s status=%s date=%s",
                current_user.slug, status, date)
    try:
        entries = await waitlist_service.get_waitlist_entries(
            current_user.id, status=status, date=date,
        )
        return entries
    except Exception as exc:
        logger.error("[Waitlist] Failed to list entries for tenant=%s: %s", current_user.slug, exc)
        raise HTTPException(status_code=500, detail="Failed to list waitlist entries.")


@router.delete("/{entry_id}")
async def cancel_waitlist_entry(
    entry_id: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Cancel a waitlist entry."""
    logger.info("[Waitlist] Cancelling entry %s for tenant=%s", entry_id, current_user.slug)
    try:
        result = await waitlist_service.cancel_waitlist_entry(entry_id)
        if not result:
            raise HTTPException(status_code=404, detail="Waitlist entry not found.")
        return {"status": "cancelled", "entry_id": entry_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[Waitlist] Failed to cancel entry %s: %s", entry_id, exc)
        raise HTTPException(status_code=500, detail="Failed to cancel waitlist entry.")
