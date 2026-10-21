"""WhatsApp Cloud API webhook endpoints."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError

from legaldost.api.processing import process_text
from legaldost.api.services import Services
from legaldost.channels.whatsapp import (
    InboundMessage,
    WhatsAppSendError,
    parse_webhook,
    verify_signature,
    verify_subscription,
)
from legaldost.db.models import ProcessedEvent
from legaldost.pipeline.formatter import split_for_whatsapp
from legaldost.strings import t

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
MAX_BODY_BYTES = 3 * 1024 * 1024
MEDIA_NAMES = {
    "image": "image",
    "audio": "voice",
    "document": "document",
    "video": "video",
    "sticker": "sticker",
}


@router.get("", response_class=PlainTextResponse)
def verify(request: Request) -> str:
    services: Services = request.app.state.services
    token = services.settings.whatsapp_verify_token
    if not services.settings.whatsapp_enabled or token is None:
        raise HTTPException(status_code=503, detail="WhatsApp is not configured")
    q = request.query_params
    challenge = verify_subscription(
        q.get("hub.mode"), q.get("hub.verify_token"), q.get("hub.challenge"), token.get_secret_value()
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="verification failed")
    return challenge


def _claim_event(services: Services, message_id: str) -> bool:
    """Record the message id; False if it was already processed (webhook retry/duplicate)."""
    session = services.sessionmaker()
    try:
        session.add(ProcessedEvent(event_id=message_id, channel="whatsapp"))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    finally:
        session.close()


def handle_inbound(services: Services, msg: InboundMessage) -> None:
    if msg.kind in ("text", "interactive", "button") and msg.text:
        reply_text = process_text(services, "whatsapp", msg.wa_id, msg.text).text
    else:
        kind = MEDIA_NAMES.get(msg.kind, msg.kind)
        reply_text = t("media_unsupported", "en", kind=kind)
    if services.whatsapp is None:
        log.warning(
            "outbound WhatsApp client not configured; reply for message %s not sent", msg.message_id[-8:]
        )
        return
    for part in split_for_whatsapp(reply_text):
        try:
            services.whatsapp.send_text(msg.wa_id, part)
        except WhatsAppSendError as exc:
            log.error("WhatsApp send failed: %s", exc)
            return


@router.post("")
async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
    services: Services = request.app.state.services
    settings = services.settings
    if not settings.whatsapp_enabled:
        raise HTTPException(status_code=503, detail="WhatsApp is not configured")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413)
    unsigned_ok = settings.environment == "development" and settings.whatsapp_allow_unsigned_dev
    if settings.whatsapp_app_secret is None:
        if not unsigned_ok:
            raise HTTPException(status_code=503, detail="WHATSAPP_APP_SECRET is not configured")
    elif not verify_signature(
        raw, request.headers.get("x-hub-signature-256"), settings.whatsapp_app_secret.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    for msg in parse_webhook(payload if isinstance(payload, dict) else {}):
        if _claim_event(services, msg.message_id):
            background.add_task(handle_inbound, services, msg)
    # Acknowledge quickly so Meta does not retry; processing continues in the background.
    return {"status": "ok"}
