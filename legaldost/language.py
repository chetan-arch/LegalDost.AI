"""Language detection. Kannada is detected by script; everything else defaults to English.

Adding a language: add its script range here, its strings in ``legaldost/strings.py`` and its
keywords/questions in ``knowledge/topics.yaml``.
"""

from __future__ import annotations

import re

KANNADA_RANGE = re.compile(r"[ಀ-೿]")
LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

SUPPORTED_LANGUAGES = ("en", "kn")


def detect_language(text: str) -> str:
    letters = LETTER.findall(text)
    if not letters:
        return "en"
    kannada = len(KANNADA_RANGE.findall(text))
    return "kn" if kannada / len(letters) >= 0.3 else "en"


def requested_language(text: str) -> str | None:
    """Explicit requests such as 'explain in Kannada' or 'ಕನ್ನಡದಲ್ಲಿ'."""
    lowered = text.lower()
    if re.search(r"\b(in|into)\s+(simple\s+|plain\s+)?kannada\b", lowered) or "ಕನ್ನಡದಲ್ಲಿ" in text:
        return "kn"
    if re.search(r"\b(in|into)\s+(simple\s+|plain\s+)?english\b", lowered) or "ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ" in text:
        return "en"
    return None
