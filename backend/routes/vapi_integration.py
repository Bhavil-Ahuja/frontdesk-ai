"""
Vapi integration routes — connect, provision/sync assistant, disconnect, status.

Replaces the "just save credentials" flow with a real provisioning step. When
the clinic owner clicks "Connect with Vapi" in the UI, we:

  1. Accept their Vapi API key (only — no need to ask for cryptic IDs).
  2. Call Vapi's /assistant endpoint to create a new assistant pre-configured
     with the tenant's greeting, voice, and our custom-LLM webhook URL.
  3. Save the returned assistant_id back to the tenant.
  4. Return success so the UI can flip to "Connected".

Routes:
  POST /api/integrations/vapi/connect      → provision an assistant on Vapi
  POST /api/integrations/vapi/sync         → re-sync existing assistant config
  POST /api/integrations/vapi/disconnect   → clear stored credentials
  GET  /api/integrations/vapi/status       → check connection
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.models.tenant import Tenant
from backend.services import auth_service, tenant_service, vapi_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/vapi", tags=["Vapi"])


class VapiConnectRequest(BaseModel):
    """User-supplied Vapi credentials for the Connect flow."""
    api_key: str = Field(..., min_length=10, max_length=255)
    # Optional: bind to an existing Vapi phone number the user already owns.
    phone_number_id: Optional[str] = Field(None, max_length=255)


@router.post("/connect")
async def vapi_connect(
    req: VapiConnectRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """
    Provision a Vapi assistant for this tenant.

    Saves the API key, then calls Vapi to create a new assistant configured
    with this tenant's greeting, voice, agent name, and our LLM webhook.
    The assistant_id is stored back to the tenant on success.
    """
    logger.info("[VapiConnect] %s connecting to Vapi", current_user.slug)

    # Step 1 — persist the API key so register_assistant can read it.
    update_fields = {"vapi_api_key": req.api_key.strip()}
    if req.phone_number_id:
        update_fields["vapi_phone_number_id"] = req.phone_number_id.strip()
    await tenant_service.update_tenant(current_user.id, update_fields)

    # Step 2 — resolve refreshed context (so voice_config, greeting, etc. flow
    # into the Vapi assistant payload).
    tenant_ctx = await tenant_service.resolve_by_id(current_user.id)
    if not tenant_ctx:
        raise HTTPException(status_code=404, detail="Tenant not found after update.")
    if not tenant_ctx.vapi_api_key:
        raise HTTPException(status_code=400, detail="Vapi API key was not stored correctly.")

    # Step 3 — call Vapi. register_assistant() handles create-vs-update based
    # on whether vapi_assistant_id is already set.
    try:
        assistant_id = await vapi_service.register_assistant(tenant_ctx=tenant_ctx)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "[VapiConnect] HTTP %s from Vapi: %s",
            exc.response.status_code, exc.response.text[:300],
        )
        # Try to surface Vapi's own error message — much more helpful than 500.
        try:
            body = exc.response.json()
            detail = body.get("message") or body.get("error") or exc.response.text
        except Exception:
            detail = exc.response.text or "Vapi returned an error."
        raise HTTPException(status_code=400, detail=f"Vapi rejected the request: {detail}")
    except Exception as exc:
        logger.error("[VapiConnect] Unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Could not reach Vapi: {exc}")

    if not assistant_id:
        raise HTTPException(
            status_code=502,
            detail="Vapi did not return an assistant ID. Double-check your API key.",
        )

    # Step 4 — persist the returned assistant_id.
    await tenant_service.update_tenant(
        current_user.id,
        {"vapi_assistant_id": assistant_id},
    )
    logger.info("[VapiConnect] %s now provisioned with assistant %s",
                current_user.slug, assistant_id)

    return {
        "status": "connected",
        "assistant_id": assistant_id,
        "message": "Your AI agent is now provisioned on Vapi. Test it by calling your Vapi phone number.",
    }


@router.post("/sync")
async def vapi_sync(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Re-sync the existing Vapi assistant with the tenant's current config."""
    tenant_ctx = await tenant_service.resolve_by_id(current_user.id)
    if not tenant_ctx or not tenant_ctx.vapi_api_key:
        raise HTTPException(status_code=400, detail="Vapi is not connected for this tenant.")

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
    """Clear stored Vapi credentials. Does NOT delete the assistant on Vapi."""
    await tenant_service.update_tenant(
        current_user.id,
        {
            "vapi_api_key": "",
            "vapi_assistant_id": "",
            "vapi_phone_number_id": "",
        },
    )
    logger.info("[VapiDisconnect] %s disconnected from Vapi", current_user.slug)
    return {"status": "disconnected"}


@router.get("/status")
async def vapi_status(
    current_user: Tenant = Depends(auth_service.get_current_user),
):
    """Connection status — used by the UI to show Connected/Not connected."""
    return {
        "connected": bool(current_user.vapi_api_key and current_user.vapi_assistant_id),
        "assistant_id": current_user.vapi_assistant_id or None,
        "phone_number_id": current_user.vapi_phone_number_id or None,
    }
