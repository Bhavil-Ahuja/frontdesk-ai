"""
Tenant admin API routes — onboarding, approval, and management.

POST   /api/tenants                 → submit onboarding request (PENDING)
GET    /api/tenants                 → list all tenants (admin)
GET    /api/tenants/{id}            → get single tenant detail
PUT    /api/tenants/{id}            → update tenant config
POST   /api/tenants/{id}/approve    → approve PENDING → ACTIVE
POST   /api/tenants/{id}/suspend    → suspend an active tenant
POST   /api/tenants/{id}/reactivate → reactivate a suspended tenant
DELETE /api/tenants/{id}            → deactivate a tenant (soft delete)
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services import tenant_service, auth_service
from backend.models.tenant import Tenant, TenantStatus, BusinessType, PlanTier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


# ── Request / Response schemas ───────────────────────────────────────────────


class TenantOnboardRequest(BaseModel):
    """Payload for a new client onboarding request."""
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9_-]+$")
    business_name: str = Field(..., min_length=2, max_length=255)
    business_type: str = Field(default="dental")
    owner_name: str = Field(..., min_length=2, max_length=255)
    owner_email: str = Field(..., max_length=255)
    owner_phone: Optional[str] = None
    timezone: str = Field(default="America/Chicago")
    plan: str = Field(default="starter")


class TenantUpdateRequest(BaseModel):
    """Partial update for tenant configuration."""
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    business_phone: Optional[str] = None
    business_address: Optional[str] = None
    business_website: Optional[str] = None
    timezone: Optional[str] = None
    agent_name: Optional[str] = None
    greeting_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    vapi_api_key: Optional[str] = None
    vapi_assistant_id: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    vapi_webhook_secret: Optional[str] = None
    calcom_api_key: Optional[str] = None
    calcom_username: Optional[str] = None
    calcom_event_types: Optional[dict[str, str]] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    escalation_phone: Optional[str] = None
    escalation_transfer_number: Optional[str] = None
    appointment_types: Optional[list[dict[str, Any]]] = None
    business_hours: Optional[dict[str, Any]] = None
    knowledge_base: Optional[dict[str, Any]] = None
    emergency_guidance: Optional[str] = None
    demo_mode: Optional[bool] = None
    plan: Optional[str] = None


class TenantOut(BaseModel):
    """Response schema for a tenant."""
    id: str
    slug: str
    business_name: str
    business_type: Optional[str]
    owner_name: str
    owner_email: str
    owner_phone: Optional[str]
    timezone: str
    plan: Optional[str]
    status: str
    demo_mode: bool
    agent_name: Optional[str]
    greeting_message: Optional[str]
    # Integration status (show whether configured, don't expose keys)
    vapi_configured: bool
    calcom_configured: bool
    twilio_configured: bool
    google_calendar_connected: bool
    google_calendar_email: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


def _tenant_to_out(t: Tenant) -> TenantOut:
    """Convert a Tenant ORM object to a TenantOut response."""
    return TenantOut(
        id=str(t.id),
        slug=t.slug,
        business_name=t.business_name,
        business_type=t.business_type.value if t.business_type else None,
        owner_name=t.owner_name,
        owner_email=t.owner_email,
        owner_phone=t.owner_phone,
        timezone=t.timezone or "America/Chicago",
        plan=t.plan.value if t.plan else None,
        status=t.status.value if t.status else "PENDING",
        demo_mode=t.demo_mode if t.demo_mode is not None else True,
        agent_name=t.agent_name,
        greeting_message=t.greeting_message,
        vapi_configured=bool(t.vapi_api_key and t.vapi_assistant_id),
        calcom_configured=bool(t.calcom_api_key),
        twilio_configured=bool(t.twilio_account_sid and t.twilio_auth_token),
        google_calendar_connected=bool(t.google_calendar_connected),
        google_calendar_email=t.google_calendar_email or "",
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("", response_model=TenantOut, status_code=201)
async def onboard_tenant(req: TenantOnboardRequest):
    """
    Submit a new client onboarding request.
    Creates a tenant in PENDING status — requires admin approval.
    """
    logger.info("[Tenants] Onboarding request: slug=%s, business=%s, owner=%s",
                req.slug, req.business_name, req.owner_email)

    # Check for slug collision
    existing = await tenant_service.resolve_by_slug(req.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Slug '{req.slug}' is already taken.")

    tenant = await tenant_service.create_tenant(req.model_dump())
    logger.info("[Tenants] Created PENDING tenant: %s (%s)", tenant.slug, tenant.business_name)
    return _tenant_to_out(tenant)


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    status: Optional[str] = Query(None, description="Filter by status: PENDING, ACTIVE, SUSPENDED, etc."),
    admin: Tenant = Depends(auth_service.require_admin),
):
    """List all tenants, optionally filtered by status. (Admin only)"""
    logger.info("[Tenants] Listing tenants (status=%s)", status)
    status_filter = None
    if status:
        try:
            status_filter = TenantStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    tenants = await tenant_service.list_tenants(status=status_filter)
    return [_tenant_to_out(t) for t in tenants]


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: str,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Get a single tenant by ID. Tenants can only fetch their own; admins can fetch any."""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    if not current_user.is_admin and current_user.id != uid:
        raise HTTPException(status_code=403, detail="You can only access your own tenant.")

    tenant = await tenant_service.get_tenant(uid)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return _tenant_to_out(tenant)


@router.put("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: str,
    req: TenantUpdateRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Update tenant configuration fields.
    Tenants can update their own config; admins can update any.
    """
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    if not current_user.is_admin and current_user.id != uid:
        raise HTTPException(status_code=403, detail="You can only update your own tenant.")

    # Only include explicitly set fields
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    tenant = await tenant_service.update_tenant(uid, update_data)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    logger.info("[Tenants] Updated tenant %s: %s", tenant.slug, list(update_data.keys()))
    return _tenant_to_out(tenant)


@router.post("/{tenant_id}/approve", response_model=TenantOut)
async def approve_tenant(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """
    Admin approves a PENDING tenant → ACTIVE.
    Only works for PENDING tenants. (Admin only)
    """
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    tenant = await tenant_service.approve_tenant(uid)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve: tenant is in {tenant.status.value} state.",
        )

    logger.info("[Tenants] Approved tenant %s → ACTIVE", tenant.slug)
    return _tenant_to_out(tenant)


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
async def suspend_tenant(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """Suspend an active tenant (billing issue, abuse, etc.). (Admin only)"""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    tenant = await tenant_service.get_tenant(uid)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Can only suspend ACTIVE tenants (current: {tenant.status.value}).",
        )

    updated = await tenant_service.update_tenant(uid, {"status": "SUSPENDED"})
    # Manually set status since update_tenant doesn't handle status transitions
    from backend.database import async_session
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uid))
        t = result.scalar_one_or_none()
        if t:
            t.status = TenantStatus.SUSPENDED
            await session.commit()
            await session.refresh(t)
            tenant_service.invalidate_cache(str(uid))
            logger.info("[Tenants] Suspended tenant %s", t.slug)
            return _tenant_to_out(t)

    raise HTTPException(status_code=500, detail="Failed to suspend tenant.")


@router.post("/{tenant_id}/reactivate", response_model=TenantOut)
async def reactivate_tenant(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """Reactivate a suspended tenant. (Admin only)"""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    from backend.database import async_session
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        if tenant.status != TenantStatus.SUSPENDED:
            raise HTTPException(
                status_code=400,
                detail=f"Can only reactivate SUSPENDED tenants (current: {tenant.status.value}).",
            )

        tenant.status = TenantStatus.ACTIVE
        await session.commit()
        await session.refresh(tenant)
        tenant_service.invalidate_cache(str(uid))
        logger.info("[Tenants] Reactivated tenant %s → ACTIVE", tenant.slug)
        return _tenant_to_out(tenant)


@router.delete("/{tenant_id}", response_model=TenantOut)
async def deactivate_tenant(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """Soft-delete: set tenant status to DEACTIVATED. (Admin only)"""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    from backend.database import async_session
    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        tenant.status = TenantStatus.DEACTIVATED
        await session.commit()
        await session.refresh(tenant)
        tenant_service.invalidate_cache(str(uid))
        logger.info("[Tenants] Deactivated tenant %s", tenant.slug)
        return _tenant_to_out(tenant)
