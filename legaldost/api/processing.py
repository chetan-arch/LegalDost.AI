"""Channel-independent message handling (one DB transaction per inbound message)."""

from __future__ import annotations

import logging

from legaldost.api.services import Services
from legaldost.language import detect_language
from legaldost.pipeline.conversation import user_key
from legaldost.pipeline.orchestrator import Reply
from legaldost.strings import t

log = logging.getLogger(__name__)


def process_text(services: Services, channel: str, channel_user_id: str, text: str) -> Reply:
    key = user_key(channel, channel_user_id, services.settings.user_id_hash_secret.get_secret_value())
    if not services.limiter.allow(key):
        return Reply(t("rate_limited", detect_language(text)), "rate_limited")
    session = services.sessionmaker()
    try:
        conv = services.conversation(session, channel, key)
        reply = services.pipeline(session, channel).handle(conv, text)
        session.commit()
        return reply
    except Exception:
        session.rollback()
        log.exception("pipeline failure on channel %s", channel)
        return Reply(t("error", detect_language(text)), "error")
    finally:
        session.close()
