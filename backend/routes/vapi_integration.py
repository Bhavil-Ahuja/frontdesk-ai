"""
Vapi integration routes — admin provisioning and tenant status.

Under Option A (centralised SaaS), all Vapi/Twilio credentials belong to the
platform. Individual tenants don't manage API keys. Instead, the admin:

  1. Creates a Vapi assistant (via the Vapi dashboard or API) using the
     platform's global API key.
  2. Buys a Twilio phone number in the platform's Twilio Console.
  3. Uses the /assign endpoint to bind these to a tenant.

The /status endpoint still works for tenants to check their own provisioning.

Routes:
  POST /api/integrations/vapi/assign           → admin assigns Vapi/Twilio IDs to a tenant
  GET  /api/integrations/vapi/admin/{tenant_id} → admin fetches a tenant's integration details
  GET  /api/integrations/vapi/admin/{tenant_id}/usage → admin fetches a tenant's usage stats
  POST /api/integrations/vapi/provision        → admin auto-provisions a Vapi assistant for a tenant
  POST /api/integrations/vapi/sync             → re-sync existing assistant config
  POST /api/integrations/vapi/disconnect       → clear stored integration IDs
  GET  /api/integrations/vapi/status           → tenant checks own connection
"""

import logging
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.tenant import Tenant
from backend.services import auth_service, tenant_service, vapi_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/vapi", tags=["Vapi"])


# ── Request / Response schemas ──────────────────────────────────────────────


class VapiAssignRequest(BaseModel):
    """Admin assigns Vapi + Twilio identifiers to a tenant."""
    tenant_id: str = Field(..., description="UUID of the tenant to provision")
    vapi_assistant_id: Optional[str] = Field(None, max_length=255)
    vapi_phone_number_id: Optional[str] = Field(None, max_length=255)
    twilio_phone_number: Optional[str] = Field(None, max_length=20)
    feature_vapi_enabled: Optional[bool] = Field(None, description="Per-tenant Vapi feature toggle")
    feature_twilio_enabled: Optional[bool] = Field(None, description="Per-tenant Twilio feature toggle")


class VapiProvisionRequest(BaseModel):
    """Admin triggers auto-provisioning of a Vapi assistant for a tenant."""
    tenant_id: str = Field(..., description="UUID of the tenant")
    phone_number_id: Optional[str] = Field(None, max_length=255,
        description="Optional: bind to an existing Vapi phone number")


# ── Admin routes ────────────────────────────────────────────────────────────


@router.post("/assign")
async def vapi_assign(
    req: VapiAssignRequest,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """
    Admin assigns Vapi assistant ID, Vapi phone number ID, and/or Twilio
    phone number to a tenant. This is the primary provisioning action under
    the platform-managed (Option A) model.
    """
    if not settings.FEATURE_VAPI_ENABLED:
        raise HTTPException(status_code=403, detail="Voice AI (Vapi) is not enabled on this platform.")
    try:
        uid = uuid.UUID(req.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    update_fields = {}
    if req.vapi_assistant_id is not None:
        update_fields["vapi_assistant_id"] = req.vapi_assistant_id.strip() or ""
    if req.vapi_phone_number_id is not None:
        update_fields["vapi_phone_number_id"] = req.vapi_phone_number_id.strip() or ""
    if req.twilio_phone_number is not None:
        update_fields["twilio_phone_number"] = req.twilio_phone_number.strip() or ""
    if req.feature_vapi_enabled is not None:
        update_fields["feature_vapi_enabled"] = req.feature_vapi_enabled
    if req.feature_twilio_enabled is not None:
        update_fields["feature_twilio_enabled"] = req.feature_twilio_enabled

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    tenant = await tenant_service.update_tenant(uid, update_fields)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    logger.info("[VapiAssign] Admin %s assigned integrations for tenant %s: %s",
                admin.slug, tenant.slug, list(update_fields.keys()))

    return {
        "status": "assigned",
        "tenant_slug": tenant.slug,
        "vapi_assistant_id": tenant.vapi_assistant_id or None,
        "vapi_phone_number_id": tenant.vapi_phone_number_id or None,
        "twilio_phone_number": tenant.twilio_phone_number or None,
        "feature_vapi_enabled": tenant.feature_vapi_enabled,
        "feature_twilio_enabled": tenant.feature_twilio_enabled,
    }


@router.get("/admin/{tenant_id}")
async def admin_get_tenant_integrations(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """Admin fetches the current Vapi/Twilio integration details for a tenant."""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    tenant = await tenant_service.get_tenant(uid)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {
        "tenant_id": str(tenant.id),
        "slug": tenant.slug,
        "vapi_assistant_id": tenant.vapi_assistant_id or "",
        "vapi_phone_number_id": tenant.vapi_phone_number_id or "",
        "twilio_phone_number": tenant.twilio_phone_number or "",
        "vapi_configured": bool(tenant.vapi_assistant_id),
        "twilio_configured": bool(tenant.twilio_phone_number),
        "agent_active": bool(tenant.agent_active) if tenant.agent_active is not None else True,
        "feature_vapi_enabled": tenant.feature_vapi_enabled,
        "feature_twilio_enabled": tenant.feature_twilio_enabled,
    }


@router.get("/admin/{tenant_id}/usage")
async def admin_get_tenant_usage(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """Admin fetches the current usage stats for a tenant."""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    from backend.services.usage_service import get_usage_summary
    summary = await get_usage_summary(uid)
    if not summary:
        raise HTTPException(status_code=404, detail="Tenant not found or no usage data.")

    return summary


@router.post("/provision")
async def vapi_provision(
    req: VapiProvisionRequest,
    admin: Tenant = Depends(auth_service.require_admin),
):
    """
    Admin auto-provisions a Vapi assistant for a tenant using the platform's
    global API key. Creates the assistant on Vapi with the tenant's greeting,
    voice config, and LLM webhook, then saves the assistant_id back.
    """
    if not settings.FEATURE_VAPI_ENABLED:
        raise HTTPException(status_code=403, detail="Voice AI (Vapi) is not enabled on this platform.")
    try:
        uid = uuid.UUID(req.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format.")

    # Optionally save phone_number_id first
    if req.phone_number_id:
        await tenant_service.update_tenant(uid, {
            "vapi_phone_number_id": req.phone_number_id.strip(),
        })

    tenant_ctx = await tenant_service.resolve_by_id(uid)
    if not tenant_ctx:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if not (tenant_ctx.vapi_api_key or settings.VAPI_API_KEY):
        raise HTTPException(
            status_code=400,
            detail="No Vapi API key configured (neither tenant nor platform global).",
        )

    try:
        assistant_id = await vapi_service.register_assistant(tenant_ctx=tenant_ctx)
    except httpx.HTTPStatusError as exc:
        logger.error("[VapiProvision] HTTP %s from Vapi: %s",
                     exc.response.status_code, exc.response.text[:300])
        try:
            body = exc.response.json()
            detail = body.get("message") or body.get("error") or exc.response.text
        except Exception:
            detail = exc.response.text or "Vapi returned an error."
        raise HTTPException(status_code=400, detail=f"Vapi rejected the request: {detail}")
    except Exception as exc:
        logger.error("[VapiProvision] Unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Could not reach Vapi: {exc}")

    if not assistant_id:
        raise HTTPException(
            status_code=502,
            detail="Vapi did not return an assistant ID.",
        )

    # Persist the returned assistant_id
    await tenant_service.update_tenant(uid, {"vapi_assistant_id": assistant_id})
    logger.info("[VapiProvision] Admin %s provisioned assistant %s for tenant %s",
                admin.slug, assistant_id, tenant_ctx.slug)

    return {
        "status": "provisioned",
        "assistant_id": assistant_id,
        "tenant_slug": tenant_ctx.slug,
        "message": f"Vapi assistant provisioned for {tenant_ctx.business_name}.",
    }


# ── Tenant self-service routes ──────────────────────────────────────────────


@router.post("/sync")
async def vapi_sync(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Re-sync the existing Vapi assistant with the tenant's current config."""
    if not settings.FEATURE_VAPI_ENABLED:
        raise HTTPException(status_code=403, detail="Voice AI (Vapi) is not enabled on this platform.")
    tenant_ctx = await tenant_service.resolve_by_id(current_user.id)
    if not tenant_ctx or not tenant_ctx.vapi_assistant_id:
        raise HTTPException(status_code=400, detail="No Vapi assistant configured for this tenant.")

    try:
        assistant_id = await vapi_service.register_assistant(tenant_ctx=tenant_ctx)
    except Exception as exc:
        logger.error("[VapiSync] Sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Vapi sync failed: {exc}")

    if not assistant_id:
        raise HTTPException(status_code=502, detail="Vapi did not return an assistant ID.")

    # If create-on-sync (i.e. assistant_id was previously missing), persist.
    if assistant_id != tenant_ctx.vapi_assistant_id:
        await tenant_service.update_tenant(
            current_user.id,
            {"vapi_assistant_id": assistant_id},
        )

    return {"status": "synced", "assistant_id": assistant_id}


@router.post("/disconnect")
async def vapi_disconnect(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Clear stored Vapi/Twilio identifiers. Does NOT delete the assistant on Vapi."""
    await tenant_service.update_tenant(
        current_user.id,
        {
            "vapi_assistant_id": "",
            "vapi_phone_number_id": "",
            "twilio_phone_number": "",
        },
    )
    logger.info("[VapiDisconnect] %s disconnected integrations", current_user.slug)
    return {"status": "disconnected"}


@router.get("/status")
async def vapi_status(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Connection status — used by the tenant UI to show provisioning state.
    Under Option A, we check for assistant_id (assigned by admin), not API key.
    """
    return {
        "connected": bool(current_user.vapi_assistant_id),
        "assistant_id": current_user.vapi_assistant_id or None,
        "phone_number_id": current_user.vapi_phone_number_id or None,
        "twilio_phone_number": current_user.twilio_phone_number or None,
    }
