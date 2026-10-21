"""Conversation state: pseudonymous user key, established facts, retention and deletion."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from legaldost.db.models import Conversation


def user_key(channel: str, channel_user_id: str, secret: str) -> str:
    """HMAC of the channel's user id (e.g. WhatsApp wa_id). The raw id is never stored."""
    return hmac.new(secret.encode(), f"{channel}:{channel_user_id}".encode(), hashlib.sha256).hexdigest()


class ConversationStore:
    def __init__(self, session: Session, retention_hours: int) -> None:
        self.session = session
        self.retention = timedelta(hours=retention_hours)

    def get_or_create(self, channel: str, key: str) -> Conversation:
        now = datetime.now(UTC)
        conv = self.session.scalar(
            select(Conversation).where(Conversation.channel == channel, Conversation.user_key == key)
        )
        if conv is not None and _aware(conv.expires_at) <= now:
            self.session.delete(conv)
            self.session.flush()
            conv = None
        if conv is None:
            conv = Conversation(
                channel=channel, user_key=key, facts={}, expires_at=now + self.retention, notice_shown=False
            )
            self.session.add(conv)
            self.session.flush()
        conv.last_inbound_at = now
        conv.expires_at = now + self.retention
        return conv

    def reset(self, conv: Conversation) -> None:
        conv.facts = {}
        conv.topic = None
        conv.pending_question = None
        conv.last_answer = None

    def delete(self, conv: Conversation) -> None:
        self.session.delete(conv)

    def purge_expired(self) -> int:
        result = self.session.execute(
            delete(Conversation).where(Conversation.expires_at <= datetime.now(UTC))
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
