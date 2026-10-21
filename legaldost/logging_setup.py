"""Privacy-conscious structured logging. Message text is never logged by application code; this
filter is a second line of defence that redacts phone numbers and credentials."""

from __future__ import annotations

import json
import logging
import re

_REDACTIONS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)(access_token|api_key|app_secret|verify_token|authorization)(['\"=:\s]+)[^\s'\",]+"),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "[REDACTED]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"), "[ID-NUMBER]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | None] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=False)


class AccessLogQueryFilter(logging.Filter):
    """Drop query strings from uvicorn access-log lines.

    Meta's webhook handshake carries the verify token in the query string
    (``?hub.verify_token=...``); query strings must never reach the logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access records: (client_addr, method, full_path, http_version, status_code)
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = (*args[:2], args[2].split("?", 1)[0] + "?[query removed]", *args[3:])
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogQueryFilter) for f in access.filters):
        access.addFilter(AccessLogQueryFilter())
