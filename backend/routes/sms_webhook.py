"""
Twilio inbound SMS webhook route.

POST /webhook/sms  -> receive inbound SMS from Twilio and respond with TwiML
"""

import logging

from fastapi import APIRouter, Request, Response

from backend.services import sms_inbound_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SMS Webhook"])


@router.post("/webhook/sms")
async def sms_webhook(request: Request):
    """
    Twilio inbound SMS webhook. Receives form-encoded data from Twilio,
    processes the message through sms_inbound_service, and returns a TwiML
    response.
    """
    try:
        form_data = await request.form()
        from_number = form_data.get("From", "")
        to_number = form_data.get("To", "")
        body = form_data.get("Body", "")
        twilio_sid = form_data.get("MessageSid", "")

        logger.info("[SMS Webhook] Inbound SMS from=%s to=%s sid=%s body_len=%d",
                     from_number, to_number, twilio_sid, len(body))

        reply_text = await sms_inbound_service.handle_inbound_sms(
            from_number=from_number,
            to_number=to_number,
            body=body,
            twilio_sid=twilio_sid,
        )

        if reply_text:
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Message>{reply_text}</Message></Response>"
            )
        else:
            twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

        return Response(content=twiml, media_type="application/xml")

    except Exception as exc:
        logger.error("[SMS Webhook] Error processing inbound SMS: %s", exc)
        # Return empty TwiML so Twilio does not retry
        empty_twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=empty_twiml, media_type="application/xml")
