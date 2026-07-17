"""
Voice calling API routes.

Endpoints:
  POST /api/voice/outbound   — trigger an outbound AI call to a student via Exotel
  GET  /api/voice/token      — generate a LiveKit access token (for browser testing)
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.models.tenant import Tenant
from backend.services import auth_service
from backend.services.exotel_service import place_outbound_call
from backend.services.tenant_service import resolve_by_slug

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Voice"])


class OutboundCallRequest(BaseModel):
    phone: str                          # student's phone in E.164
    name: str = "Student"
    context: Optional[dict] = None      # optional appointment context (not used yet)
    tenant_slug: Optional[str] = None  # override; defaults to current user's tenant


@router.post("/api/voice/outbound")
async def trigger_outbound_call(
    body: OutboundCallRequest,
    current_user: Tenant = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    """
    Trigger an outbound call from Exotel to a student.

    The call flow:
      Exotel dials student → student answers → Exotel bridges to LiveKit SIP →
      LiveKit agent picks up → AI conversation begins.

    The `from_phone` is the tenant's assigned sip_phone_number. Make sure the tenant
    has one assigned in Platform Admin → Tenant → Integrations.
    """
    slug = body.tenant_slug or current_user.slug
    tenant_ctx = await resolve_by_slug(slug)
    if not tenant_ctx:
        raise Exception(f"Tenant '{slug}' not found.")

    from_phone = tenant_ctx.sip_phone_number
    if not from_phone:
        raise Exception(
            "No SIP phone number assigned to this tenant — "
            "admin must assign one in Platform Admin → Integrations."
        )

    logger.info("[Voice] Outbound call: tenant=%s from=%s to=%s",
                tenant_ctx.slug, from_phone, body.phone)

    result = await place_outbound_call(
        to_phone=body.phone,
        from_phone=from_phone,
        caller_id=from_phone,
    )

    return {
        "platform": "exotel",
        "status": result.get("Status", "initiated"),
        "call_sid": result.get("Sid", ""),
        "from": from_phone,
        "to": body.phone,
    }


@router.get("/api/voice/token")
async def get_livekit_token(
    room: str = "test-room",
    current_user: Tenant = Depends(auth_service.get_current_user),
) -> dict[str, str]:
    """
    Generate a LiveKit access token for browser-based testing
    (agents-playground.livekit.io or your own test page).

    The token grants publish+subscribe permissions so you can join the room
    and test the voice agent from your browser without a real phone call.

    Room metadata is set to "{sip_phone_number}|" so the voice agent resolves
    the correct tenant (same logic as a real SIP call via called_phone).
    Falls back to "tenant:{tenant_id}" if no SIP number is configured.
    """
    from backend.config import settings

    # Encode tenant identity in room metadata so the agent resolves correctly.
    # Format mirrors SIP dispatch rule metadata: "called_phone|caller_phone"
    # agent's _resolve_tenant reads this and resolves via sip_phone_number.
    sip_phone = getattr(current_user, "sip_phone_number", None) or ""
    if sip_phone:
        room_metadata = f"{sip_phone}|"        # called_phone=sip_phone, caller=""
    else:
        room_metadata = f"tenant:{current_user.id}|"  # fallback — agent handles below

    try:
        from livekit.api import AccessToken, VideoGrants, RoomServiceClient

        # Pre-create the room with metadata so the agent sees it on join.
        try:
            room_client = RoomServiceClient(
                settings.LIVEKIT_URL,
                settings.LIVEKIT_API_KEY,
                settings.LIVEKIT_API_SECRET,
            )
            from livekit.api import CreateRoomRequest
            await room_client.create_room(CreateRoomRequest(
                name=room,
                metadata=room_metadata,
            ))
        except Exception:
            pass  # Room may already exist; metadata will be set on next creation

        token = (
            AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
            .with_identity(f"test-{current_user.slug}")
            .with_name(current_user.owner_name or current_user.slug)
            .with_grants(VideoGrants(room_join=True, room=room))
            .to_jwt()
        )
        return {
            "token": token,
            "url": settings.LIVEKIT_URL,
            "room": room,
            "metadata": room_metadata,
        }
    except ImportError:
        return {
            "error": "livekit package not installed — run: pip install livekit-agents",
            "url": settings.LIVEKIT_URL,
            "room": room,
        }
