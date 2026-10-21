"""Safe text extraction that preserves page numbers.

Only PDF (with a text layer) and UTF-8 plain text are accepted. Scanned PDFs are rejected with a
clear error rather than silently producing garbage: OCR is a separate, future feature because OCR
errors must stay visible and must never silently alter legal identifiers.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field

ALLOWED_MIME = {"application/pdf", "text/plain"}


class ExtractionError(Exception):
    pass


@dataclass
class ExtractedDocument:
    pages: list[str]  # index 0 = page 1; plain text has a single "page"
    paginated: bool
    notes: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.pages)


def sniff_mime(data: bytes, declared: str | None = None) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if declared and declared.split(";")[0].strip() == "text/plain":
        return "text/plain"
    try:
        sample = data[:4096].decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the sample boundary; retry slightly shorter.
        try:
            sample = data[: exc.start].decode("utf-8") if exc.start > 0 else ""
        except UnicodeDecodeError:
            sample = ""
        if not sample:
            raise ExtractionError("unsupported file type (expected PDF or UTF-8 text)") from None
    if "<html" in sample.lower() or "<!doctype" in sample.lower():
        raise ExtractionError(
            "received an HTML page, not a document (the URL may be an app shell or login page)"
        )
    return "text/plain"


def _strip_repeated_lines(pages: list[str], notes: list[str]) -> list[str]:
    """Remove running headers/footers/watermarks that repeat on most pages."""
    if len(pages) < 3:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({key(line) for line in page.splitlines() if line.strip()})
    threshold = max(3, int(len(pages) * 0.6))
    repeated = {k for k, c in counts.items() if c >= threshold and len(k) < 120}
    if not repeated:
        return pages
    notes.append(f"removed {len(repeated)} repeated header/footer/watermark line pattern(s)")
    return ["\n".join(line for line in page.splitlines() if key(line) not in repeated) for page in pages]


def extract(data: bytes, mime: str) -> ExtractedDocument:
    if mime not in ALLOWED_MIME:
        raise ExtractionError(f"unsupported MIME type {mime}")
    notes: list[str] = []
    if mime == "text/plain":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractionError("text file is not valid UTF-8") from exc
        return ExtractedDocument(pages=[text.replace("\r\n", "\n")], paginated=False, notes=notes)

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("encrypted PDFs are not accepted")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError(f"could not parse PDF: {exc}") from exc
    if not pages:
        raise ExtractionError("PDF has no pages")
    text_pages = sum(1 for p in pages if len(p.strip()) > 50)
    if text_pages == 0:
        raise ExtractionError("PDF has no text layer (scanned image); OCR is not enabled")
    if text_pages < len(pages):
        notes.append(f"{len(pages) - text_pages} page(s) had little or no extractable text")
    pages = _strip_repeated_lines(pages, notes)
    return ExtractedDocument(pages=pages, paginated=True, notes=notes)
