"""
Platform-level admin routes — global configuration and rich tenant management.

All routes require admin authentication.

Endpoints:
  GET  /api/admin/platform/config              — read global platform settings
  PUT  /api/admin/platform/config              — update global platform settings
  GET  /api/admin/tenants/{id}                 — rich tenant integration + status detail
  GET  /api/admin/tenants/{id}/usage           — tenant usage summary
  POST /api/admin/tenants/{id}/integrations    — update tenant phone numbers, agent flags
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import async_session
from backend.models.platform_config import PlatformConfig
from backend.models.tenant import Tenant
from backend.services import auth_service, tenant_service
from backend.services.usage_service import get_usage_summary
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mask_secret(secret: str | None) -> str:
    """Show only the last 4 chars of a secret for display confirmation."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "•" * len(secret)
    return "•" * (len(secret) - 4) + secret[-4:]


async def _get_platform_config() -> dict[str, str]:
    """Return all platform_config rows as a dict."""
    async with async_session() as session:
        rows = (await session.execute(select(PlatformConfig))).scalars().all()
        return {row.key: (row.value or "") for row in rows}


async def _set_platform_config(key: str, value: str) -> None:
    """Upsert a single platform_config key."""
    async with async_session() as session:
        existing = (
            await session.execute(select(PlatformConfig).where(PlatformConfig.key == key))
        ).scalar_one_or_none()

        if existing:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            session.add(PlatformConfig(key=key, value=value))

        await session.commit()


# ── Platform config endpoints ─────────────────────────────────────────────────


@router.get("/platform/config")
async def get_platform_config(
    admin: Tenant = Depends(auth_service.require_admin),
) -> dict:
    """Return global platform settings (LiveKit / Exotel credentials, masked)."""
    cfg = await _get_platform_config()
    livekit_api_key = cfg.get("livekit_api_key", "")
    livekit_api_secret = cfg.get("livekit_api_secret", "")
    livekit_url = cfg.get("livekit_url", "")
    exotel_sid = cfg.get("exotel_sid", "")
    exotel_token = cfg.get("exotel_token", "")

    return {
        "livekit_url": livekit_url,
        "livekit_api_key": livekit_api_key,
        "livekit_api_secret_masked": _mask_secret(livekit_api_secret),
        "livekit_configured": bool(livekit_url and livekit_api_key and livekit_api_secret),
        "exotel_sid": exotel_sid,
        "exotel_token_masked": _mask_secret(exotel_token),
        "exotel_configured": bool(exotel_sid and exotel_token),
    }


class PlatformConfigUpdate(BaseModel):
    livekit_url: Optional[str] = None         # wss://your-livekit-server
    livekit_api_key: Optional[str] = None
    livekit_api_secret: Optional[str] = None  # omit or send masked value to preserve
    exotel_sid: Optional[str] = None
    exotel_token: Optional[str] = None        # omit or send masked value to preserve


@router.put("/platform/config")
async def update_platform_config(
    body: PlatformConfigUpdate,
    admin: Tenant = Depends(auth_service.require_admin),
) -> dict:
    """Update global platform settings. Skip any masked (•-containing) values."""
    updated = []

    if body.livekit_url is not None:
        await _set_platform_config("livekit_url", body.livekit_url.strip())
        updated.append("livekit_url")

    if body.livekit_api_key is not None:
        await _set_platform_config("livekit_api_key", body.livekit_api_key.strip())
        updated.append("livekit_api_key")

    if body.livekit_api_secret is not None:
        if "•" not in body.livekit_api_secret:
            await _set_platform_config("livekit_api_secret", body.livekit_api_secret.strip())
            updated.append("livekit_api_secret")

    if body.exotel_sid is not None:
        await _set_platform_config("exotel_sid", body.exotel_sid.strip())
        updated.append("exotel_sid")

    if body.exotel_token is not None:
        if "•" not in body.exotel_token:
            await _set_platform_config("exotel_token", body.exotel_token.strip())
            updated.append("exotel_token")

    logger.info("[PlatformAdmin] %s updated platform config: %s", admin.slug, updated)

    cfg = await _get_platform_config()
    return {
        "status": "saved",
        "updated_fields": updated,
        "livekit_url": cfg.get("livekit_url", ""),
        "livekit_api_key": cfg.get("livekit_api_key", ""),
        "livekit_api_secret_masked": _mask_secret(cfg.get("livekit_api_secret", "")),
        "livekit_configured": bool(
            cfg.get("livekit_url") and cfg.get("livekit_api_key") and cfg.get("livekit_api_secret")
        ),
        "exotel_sid": cfg.get("exotel_sid", ""),
        "exotel_token_masked": _mask_secret(cfg.get("exotel_token", "")),
        "exotel_configured": bool(cfg.get("exotel_sid") and cfg.get("exotel_token")),
    }


# ── Tenant management endpoints ───────────────────────────────────────────────


@router.get("/tenants/{tenant_id}")
async def admin_get_tenant(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
) -> dict:
    """
    Rich tenant integration + status detail for the admin panel.

    Returns integration status, feature flags, plan info, and contact details.
    """
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID.")

    tenant = await tenant_service.get_tenant(uid)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {
        "tenant_id": str(tenant.id),
        "slug": tenant.slug,
        "business_name": tenant.business_name,
        "business_type": tenant.business_type.value if tenant.business_type else None,
        "owner_name": tenant.owner_name,
        "owner_email": tenant.owner_email,
        "owner_phone": tenant.owner_phone or "",
        "business_phone": tenant.business_phone or "",
        "business_address": tenant.business_address or "",
        "business_website": tenant.business_website or "",
        "google_maps_url": tenant.google_maps_url or "",
        "timezone": tenant.timezone or "America/Chicago",
        "plan": tenant.plan.value if tenant.plan else "starter",
        "status": tenant.status.value if tenant.status else "PENDING",
        "demo_mode": bool(tenant.demo_mode),
        # Integration status
        "sms_configured": bool(tenant.sip_phone_number),
        "sip_phone_number": tenant.sip_phone_number or "",
        "google_calendar_connected": bool(tenant.google_calendar_connected),
        "google_calendar_email": tenant.google_calendar_email or "",
        # Agent / feature flags
        "agent_active": bool(tenant.agent_active) if tenant.agent_active is not None else True,
        "feature_sms_enabled": bool(tenant.feature_sms_enabled) if tenant.feature_sms_enabled is not None else False,
        # Timestamps
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
        "last_login_at": tenant.last_login_at.isoformat() if tenant.last_login_at else None,
    }


@router.get("/tenants/{tenant_id}/usage")
async def admin_get_tenant_usage(
    tenant_id: str,
    admin: Tenant = Depends(auth_service.require_admin),
) -> dict:
    """Return the current billing-period usage summary for a tenant."""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID.")

    summary = await get_usage_summary(uid)
    if not summary:
        raise HTTPException(status_code=404, detail="Tenant not found or no usage data.")

    return summary


class TenantIntegrationsUpdate(BaseModel):
    feature_sms_enabled: Optional[bool] = None
    agent_active: Optional[bool] = None
    sip_phone_number: Optional[str] = None  # Exotel phone number (voice + SMS)


@router.post("/tenants/{tenant_id}/integrations")
async def admin_update_tenant_integrations(
    tenant_id: str,
    body: TenantIntegrationsUpdate,
    admin: Tenant = Depends(auth_service.require_admin),
) -> dict:
    """Update a tenant's phone numbers, feature flags, and agent status."""
    try:
        uid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID.")

    update_fields: dict = {}
    if body.feature_sms_enabled is not None:
        update_fields["feature_sms_enabled"] = body.feature_sms_enabled
    if body.agent_active is not None:
        update_fields["agent_active"] = body.agent_active
    if body.sip_phone_number is not None:
        raw = body.sip_phone_number.strip()
        if raw:
            # Normalise to E.164 to prevent ambiguous routing
            from backend.services.caller_service import _normalise_phone
            normalised: str | None = _normalise_phone(raw) or raw
        else:
            normalised = None
        # Validate uniqueness before saving
        if normalised:
            from sqlalchemy import func as sa_func, and_
            async with async_session() as session:
                conflict = (await session.execute(
                    select(Tenant).where(
                        and_(
                            sa_func.regexp_replace(Tenant.sip_phone_number, "[^0-9+]", "", "g")
                            == sa_func.regexp_replace(normalised, "[^0-9+]", "", "g"),
                            Tenant.id != uid,
                            Tenant.sip_phone_number.is_not(None),
                        )
                    ).limit(1)
                )).scalar_one_or_none()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail=f"SIP phone {normalised} is already assigned to tenant '{conflict.slug}'."
                )
        update_fields["sip_phone_number"] = normalised

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    tenant = await tenant_service.update_tenant(uid, update_fields)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    logger.info("[PlatformAdmin] %s updated integrations for %s: %s",
                admin.slug, tenant.slug, list(update_fields.keys()))

    return {
        "status": "saved",
        "tenant_slug": tenant.slug,
        "feature_sms_enabled": bool(tenant.feature_sms_enabled),
        "agent_active": bool(tenant.agent_active),
        "sip_phone_number": tenant.sip_phone_number or "",
    }
