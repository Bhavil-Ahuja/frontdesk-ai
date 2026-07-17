"""
Exotel inbound SMS webhook route.

POST /webhook/sms  — receive inbound SMS from Exotel

Exotel webhook payload (form-encoded POST):
  SmsSid    — Exotel message SID
  From      — sender's phone number
  To        — your ExoPhone (the tenant's Exotel number)
  Body      — message text

Unlike Twilio, Exotel does NOT support TwiML auto-reply.
Replies must be sent as a separate outbound SMS API call —
sms_inbound_service handles that via sms_service.send_custom_sms().
"""

import logging

from fastapi import APIRouter, Request, Response

from backend.services import sms_inbound_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SMS Webhook"])


@router.post("/webhook/sms")
async def sms_webhook(request: Request):
    """
    Exotel inbound SMS webhook.
    Receives form-encoded data, processes through sms_inbound_service,
    and returns HTTP 200 (Exotel only needs a 200 ACK — no body required).
    Any reply is sent as a separate outbound SMS by sms_inbound_service.
    """
    try:
        form_data = await request.form()

        # Exotel field names — fall back to Twilio names for backwards compat
        from_number = form_data.get("From", "")
        to_number   = form_data.get("To", "")
        body        = form_data.get("Body", "")
        sms_sid     = form_data.get("SmsSid", "") or form_data.get("MessageSid", "")

        logger.info("[SMS Webhook] Inbound SMS from=%s to=%s sid=%s body_len=%d",
                    from_number, to_number, sms_sid, len(body))

        if not body.strip():
            logger.info("[SMS Webhook] Empty body — ignoring")
            return Response(status_code=200)

        # Process and reply (reply is sent as a separate outbound SMS inside)
        await sms_inbound_service.handle_inbound_sms(
            from_number=from_number,
            to_number=to_number,
            body=body,
            sms_sid=sms_sid,
        )

        # Exotel just needs a 200 ACK — no body
        return Response(status_code=200)

    except Exception as exc:
        logger.error("[SMS Webhook] Error processing inbound SMS: %s", exc, exc_info=True)
        return Response(status_code=200)  # Always 200 so Exotel doesn't retry
