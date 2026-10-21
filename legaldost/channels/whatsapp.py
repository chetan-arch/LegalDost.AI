"""WhatsApp Business Platform (Cloud API) adapter.

Implements:
* webhook verification handshake (GET with ``hub.mode``, ``hub.verify_token``, ``hub.challenge``),
* payload authenticity via ``X-Hub-Signature-256: sha256=<HMAC-SHA256(app_secret, raw_body)>``,
* parsing of inbound message notifications,
* outbound text messages via ``POST {graph}/{version}/{phone_number_id}/messages``.

Only replies to user-initiated conversations are sent (inside the customer-service window).
Business-initiated messages require approved templates, which are not implemented.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value.removeprefix("sha256=").strip().lower())


def verify_subscription(
    mode: str | None, token: str | None, challenge: str | None, expected_token: str
) -> str | None:
    if (
        mode == "subscribe"
        and token is not None
        and challenge is not None
        and hmac.compare_digest(token.encode("utf-8"), expected_token.encode("utf-8"))
    ):
        return challenge
    return None


@dataclass
class InboundMessage:
    message_id: str
    wa_id: str
    phone_number_id: str | None
    timestamp: int | None
    kind: str  # text, image, audio, document, video, sticker, location, interactive, ...
    text: str | None


def parse_webhook(payload: dict[str, Any]) -> list[InboundMessage]:
    """Extract inbound user messages; status updates (sent/delivered/read) are ignored."""
    out: list[InboundMessage] = []
    if payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            for msg in value.get("messages") or []:
                kind = str(msg.get("type") or "unknown")
                text = None
                if kind == "text":
                    text = (msg.get("text") or {}).get("body")
                elif kind == "interactive":
                    inter = msg.get("interactive") or {}
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title")
                elif kind == "button":
                    text = (msg.get("button") or {}).get("text")
                if not msg.get("id") or not msg.get("from"):
                    continue
                ts = msg.get("timestamp")
                out.append(
                    InboundMessage(
                        message_id=str(msg["id"]),
                        wa_id=str(msg["from"]),
                        phone_number_id=phone_number_id,
                        timestamp=int(ts) if str(ts).isdigit() else None,
                        kind=kind,
                        text=text,
                    )
                )
    return out


class WhatsAppSendError(Exception):
    pass


class WhatsAppClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        api_version: str,
        base_url: str = "https://graph.facebook.com",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self._path = f"/{api_version}/{phone_number_id}/messages"
        self.max_retries = max_retries

    def send_text(self, to_wa_id: str, body: str) -> str | None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.post(self._path, json=payload)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise WhatsAppSendError(f"transport error: {type(exc).__name__}") from exc
                time.sleep(0.5 * 2**attempt)
                continue
            if resp.status_code == 200:
                messages = resp.json().get("messages") or [{}]
                return messages[0].get("id")
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < self.max_retries:
                time.sleep(0.5 * 2**attempt)
                continue
            # Never log the message body or recipient.
            code = (
                (resp.json().get("error") or {}).get("code")
                if resp.headers.get("content-type", "").startswith("application/json")
                else None
            )
            raise WhatsAppSendError(f"send failed: HTTP {resp.status_code}, error code {code}")
        raise WhatsAppSendError("retries exhausted")
