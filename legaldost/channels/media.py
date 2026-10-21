"""Interfaces for non-text inbound media (images, PDFs, voice).

Not implemented in milestone 1. The planned flow is: download media via the Cloud API media
endpoint -> scan/validate type and size -> OCR or speech-to-text -> show the extracted text to
the user for confirmation (OCR errors must stay visible and must never silently alter legal
identifiers) -> run the normal pipeline. Uploaded media must be deleted after processing.
"""

from __future__ import annotations

from typing import Protocol


class MediaProcessor(Protocol):
    def supports(self, kind: str) -> bool: ...

    def extract_text(self, media_id: str) -> str: ...


class UnsupportedMedia:
    """Default processor: declines every media type so the user gets a clear message."""

    def supports(self, kind: str) -> bool:
        return False

    def extract_text(self, media_id: str) -> str:
        raise NotImplementedError("media processing is not enabled")
