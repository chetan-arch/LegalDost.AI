"""Split extracted text into citable passages with page and paragraph/section locators.

Strategy:
1. Try numbered blocks ("24. ...", "100. ...") that appear at line starts in broadly increasing
   order. These become paragraph (judgments/notifications) or section/rule labels.
2. Otherwise fall back to page-bounded windows.

Labels derived from numbering are heuristic and are recorded as such in the version notes; page
numbers come straight from the PDF and are reliable.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from legaldost.ingestion.extract import ExtractedDocument

MAX_CHARS = 1500
MIN_CHARS = 80
BLOCK_START = re.compile(r"(?m)^[ \t]*(\d{1,4}[A-Z]{0,2})\.[ \t]+(?=\S)")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
KANNADA = re.compile(r"[ಀ-೿]")
LETTER = re.compile(r"[^\W\d_]")

LABEL_KIND = {"judgment": "para", "statute": "s.", "rules": "r.", "notification": "para"}


@dataclass
class Segment:
    text: str
    page_start: int | None
    page_end: int | None
    label: str | None
    locator: str
    language: str


def detect_script_language(text: str) -> str:
    letters = len(LETTER.findall(text)) or 1
    if len(DEVANAGARI.findall(text)) / letters > 0.3:
        return "hi"
    if len(KANNADA.findall(text)) / letters > 0.3:
        return "kn"
    return "en"


def _page_locator(start: int | None, end: int | None) -> str:
    if start is None:
        return ""
    return f"p. {start}" if start == end or end is None else f"pp. {start}-{end}"


def _split_spans(text: str) -> list[tuple[int, int]]:
    """Split text into (start, end) spans of at most MAX_CHARS, preferring sentence boundaries.

    Working on offsets (not copies) lets each piece keep its own page range."""
    if len(text) <= MAX_CHARS:
        return [(0, len(text))]
    bounds = [m.end() for m in re.finditer(r"[.;:]\s+", text)] + [len(text)]
    spans: list[tuple[int, int]] = []
    start = prev = 0
    for b in bounds:
        if b - start > MAX_CHARS and prev > start:
            spans.append((start, prev))
            start = prev
        prev = b
    spans.append((start, len(text)))
    # Hard-wrap anything still too long (e.g. text without punctuation).
    out: list[tuple[int, int]] = []
    for a, b in spans:
        out.extend((i, min(i + MAX_CHARS, b)) for i in range(a, b, MAX_CHARS))
    return out


def _numeric(label: str) -> int:
    return int(re.match(r"\d+", label).group(0))  # type: ignore[union-attr]


def segment(doc: ExtractedDocument, document_type: str) -> tuple[list[Segment], str]:
    """Return segments and the strategy used ("numbered" or "pages")."""
    page_offsets: list[int] = []
    full = ""
    for page in doc.pages:
        page_offsets.append(len(full))
        full += page.strip() + "\n"

    def page_of(offset: int) -> int | None:
        return bisect_right(page_offsets, offset) if doc.paginated else None

    matches = list(BLOCK_START.finditer(full))
    accepted = []
    last = 0
    for m in matches:
        n = _numeric(m.group(1))
        if last < n <= last + 3 or (n == 1 and last > 3):
            accepted.append(m)
            last = n
    kind = LABEL_KIND.get(document_type, "para")
    segments: list[Segment] = []

    def emit(raw: str, start: int, end: int, label: str | None) -> None:
        spans = [(a, b) for a, b in _split_spans(raw) if raw[a:b].strip()]
        pieces = [re.sub(r"[ \t]+", " ", raw[a:b]).strip() for a, b in spans]
        for i, (piece, (a, b)) in enumerate(zip(pieces, spans, strict=True)):
            # Page range of this piece only, not of the whole numbered block.
            ps, pe = page_of(start + a), page_of(max(start + a, start + b - 1))
            loc_parts = []
            if label:
                loc_parts.append(f"{kind} {label}" + (f" (part {i + 1})" if len(pieces) > 1 else ""))
            if pl := _page_locator(ps, pe):
                loc_parts.append(pl)
            segments.append(
                Segment(
                    piece,
                    ps,
                    pe,
                    label,
                    ", ".join(loc_parts) or "whole document",
                    detect_script_language(piece),
                )
            )

    if len(accepted) >= 3:
        if accepted[0].start() > MIN_CHARS:
            emit(full[: accepted[0].start()], 0, accepted[0].start(), None)
        for i, m in enumerate(accepted):
            end = accepted[i + 1].start() if i + 1 < len(accepted) else len(full)
            emit(full[m.start() : end], m.start(), end, m.group(1))
        strategy = "numbered"
    else:
        for idx, page in enumerate(doc.pages):
            start = page_offsets[idx]
            emit(page, start, start + len(page), None)
        strategy = "pages"

    merged: list[Segment] = []
    for seg in segments:
        if merged and len(seg.text) < MIN_CHARS and merged[-1].label == seg.label:
            prev = merged[-1]
            locator = prev.locator
            if prev.page_end != seg.page_end and (old := _page_locator(prev.page_start, prev.page_end)):
                locator = locator.replace(old, _page_locator(prev.page_start, seg.page_end))
            merged[-1] = Segment(
                f"{prev.text} {seg.text}", prev.page_start, seg.page_end, prev.label, locator, prev.language
            )
        else:
            merged.append(seg)
    return merged, strategy
