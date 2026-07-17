"""
Exotel telephony service — Indian carrier for inbound/outbound calls.

API docs: https://developer.exotel.com/api/
Auth: HTTP Basic (SID:Token)

For outbound calls: POST /Accounts/{sid}/Calls/connect
The call flow: Exotel dials the student → when answered, bridges to your SIP endpoint.
"""

import logging
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

EXOTEL_API_BASE = "https://api.exotel.com/v1"


async def _get_credentials() -> tuple[str, str]:
    """
    Return (sid, token). Tries platform_config DB first, falls back to .env.
    """
    sid = settings.EXOTEL_SID
    token = settings.EXOTEL_TOKEN

    try:
        from backend.database import async_session
        from backend.models.platform_config import PlatformConfig
        from sqlalchemy import select
        async with async_session() as session:
            rows = (await session.execute(
                select(PlatformConfig).where(
                    PlatformConfig.key.in_(["exotel_sid", "exotel_token"])
                )
            )).scalars().all()
            for row in rows:
                if row.key == "exotel_sid" and row.value:
                    sid = row.value
                elif row.key == "exotel_token" and row.value:
                    token = row.value
    except Exception as exc:
        logger.warning("[Exotel] Could not read platform_config: %s — using env fallback", exc)

    return sid, token


async def place_outbound_call(
    to_phone: str,
    from_phone: str,
    caller_id: str,
    *,
    sid: str = "",
    token: str = "",
) -> dict[str, Any]:
    """
    Initiate an outbound call from Exotel to a student's phone.

    The call flow:
      1. Exotel dials `to_phone` (student)
      2. When student picks up, Exotel connects to your SIP/LiveKit endpoint
         configured as an ExoPhone app in the Exotel dashboard.

    Args:
        to_phone:   Recipient's phone in E.164 (e.g. +919876543210)
        from_phone: Exotel number to display as caller ID (e.g. +918065481555)
        caller_id:  Same as from_phone — Exotel requires this separately
        sid/token:  Optional override; if empty, loaded from platform_config/env

    Returns dict with call SID and status.
    """
    if not sid or not token:
        sid, token = await _get_credentials()

    if not sid or not token:
        raise ValueError("Exotel credentials not configured — set in Platform Settings.")

    url = f"{EXOTEL_API_BASE}/Accounts/{sid}/Calls/connect.json"

    payload = {
        "From": to_phone,
        "To": from_phone,
        "CallerId": caller_id or from_phone,
        "StatusCallback": "",  # Optional: URL to receive call status updates
    }

    logger.info("[Exotel] Initiating outbound call: %s → %s", from_phone, to_phone)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            url,
            data=payload,
            auth=(sid, token),
        )

    if resp.status_code not in (200, 201):
        body = resp.text[:300] if resp.text else "(empty)"
        logger.error("[Exotel] Call failed HTTP %d: %s", resp.status_code, body)
        raise Exception(f"Exotel returned HTTP {resp.status_code}: {body}")

    data = resp.json()
    call_data = data.get("Call", data)
    logger.info("[Exotel] Call initiated: Sid=%s Status=%s",
                call_data.get("Sid"), call_data.get("Status"))
    return call_data


async def redirect_active_call(
    call_sid: str,
    redirect_url: str,
    *,
    sid: str = "",
    token: str = "",
    subdomain: str = "",
) -> dict:
    """
    Redirect an active Exotel call mid-conversation by pointing it at a new
    ExoML URL.  Exotel fetches the URL, parses the XML, and executes the
    applet (e.g. <Dial> to bridge the caller to a PSTN number).

    This is the programmatic equivalent of the App Bazaar "Transfer" applet
    and does NOT rely on SIP REFER — Exotel handles all PSTN bridging
    natively, which is why it works even on inbound-only SIP trunks.

    Args:
        call_sid:     Exotel call SID, e.g. "SCL_tebPGCYvKZQz" (from sip.callID
                      participant attribute).
        redirect_url: Public URL that returns ExoML for the new call flow.
        sid/token:    Optional credential override; loaded from platform_config
                      or .env if empty.
        subdomain:    Optional API subdomain override (default: EXOTEL_SUBDOMAIN
                      or "api.in.exotel.com" for India).

    Returns dict from Exotel's response body (may be empty on 204).
    Raises on non-2xx response.
    """
    if not sid or not token:
        sid, token = await _get_credentials()
    if not sid or not token:
        raise ValueError("Exotel credentials not configured.")

    # India endpoint — use api.in.exotel.com unless overridden
    if not subdomain:
        from backend.config import settings as _s
        subdomain = _s.EXOTEL_SUBDOMAIN or "api.in.exotel.com"
    # Ensure subdomain does not include https:// prefix
    subdomain = subdomain.removeprefix("https://").removeprefix("http://")

    url = f"https://{subdomain}/v1/Accounts/{sid}/Calls/{call_sid}"
    payload = {"Url": redirect_url, "Method": "GET"}

    logger.info(
        "[Exotel] Redirecting call %s -> %s", call_sid, redirect_url
    )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            data=payload,
            auth=(sid, token),
        )

    if resp.status_code not in (200, 201, 204):
        body = resp.text[:400] if resp.text else "(empty)"
        logger.error(
            "[Exotel] Redirect call failed HTTP %d: %s", resp.status_code, body
        )
        raise Exception(f"Exotel redirect returned HTTP {resp.status_code}: {body}")

    logger.info("[Exotel] Redirect accepted: HTTP %d", resp.status_code)
    try:
        return resp.json()
    except Exception:
        return {}  # 204 No Content is a valid success response
