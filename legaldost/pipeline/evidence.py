"""Build the evidence packet from retrieval results. Every item comes from database records."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from legaldost.db.models import LegalSource, Passage
from legaldost.domain.facts import JURISDICTION_NAMES
from legaldost.domain.schemas import EvidenceItem, EvidencePacket, RetrievedPassage, SourceCategory
from legaldost.textutil import content_tokens, stem


def relevant_window(text: str, query: str, max_chars: int) -> str:
    """Return the part of a long passage that best matches the question, cut at sentence boundaries.

    Long statutory sections often put the key clause (e.g. the punishment) at the end; always taking
    the first ``max_chars`` characters would hide it from the model."""
    if len(text) <= max_chars:
        return text
    terms = {stem(t) for t in content_tokens(query)}
    sentences = re.split(r"(?<=[.;:])\s+", text)
    best, best_score = text[:max_chars], -1.0
    for start in range(len(sentences)):
        window: list[str] = []
        length = 0
        for sentence in sentences[start:]:
            if length + len(sentence) + 1 > max_chars and window:
                break
            window.append(sentence)
            length += len(sentence) + 1
        chunk = " ".join(window)[:max_chars]
        score = len(terms & {stem(t) for t in content_tokens(chunk)}) + 0.001 * (start == 0)
        if score > best_score:
            best, best_score = chunk, score
    return best


def binding_note(source: LegalSource, user_jurisdiction: str | None) -> str | None:
    if source.document_type != "judgment" or not user_jurisdiction:
        return None
    if source.court_level == "high_court" and source.jurisdiction != user_jurisdiction:
        return (
            f"High Court of another state ({JURISDICTION_NAMES.get(source.jurisdiction, source.jurisdiction)}): "
            f"not binding in {JURISDICTION_NAMES.get(user_jurisdiction, user_jurisdiction)}; may be persuasive."
        )
    return None


CHAPTER_HEADING = re.compile(
    r"\b(CHAPTER|PART)\s+([IVXLC]+[A-Z]?)\s*\n+\s*([^\n]{3,120}(?:\n[A-Z][A-Z ,'-]{3,80}\b)?)"
)


def chapter_of(session: Session, passage: Passage) -> str | None:
    """The chapter (or part) heading a statute passage falls under, from earlier passages.

    Headings sit inside passage text where the chapter starts; a heading inside this passage
    usually opens the *next* chapter, so only earlier passages are searched.
    """
    earlier = session.scalars(
        select(Passage.text)
        .where(Passage.version_id == passage.version_id, Passage.ordinal < passage.ordinal)
        .where(Passage.text.contains("CHAPTER") | Passage.text.contains("PART "))
        .order_by(Passage.ordinal.desc())
        .limit(80)  # page headers ("[PART II— SEC. 1]") also contain PART: skip past them
    )
    for text_value in earlier:
        matches = list(CHAPTER_HEADING.finditer(text_value))
        if matches:
            kind, number, title = matches[-1].groups()
            return f"{kind} {number} — {' '.join(title.split())}"
    return None


def build_packet(
    session: Session,
    query: str,
    results: list[RetrievedPassage],
    user_jurisdiction: str | None,
    max_chars: int,
) -> EvidencePacket:
    items: list[EvidenceItem] = []
    for i, r in enumerate(results, start=1):
        passage = session.get(Passage, r.passage_id)
        if passage is None:
            continue
        source = passage.source
        items.append(
            EvidenceItem(
                evidence_id=f"E{i}",
                passage_id=passage.id,
                source_id=source.id,
                source_key=source.source_key,
                title=source.title,
                issuing_authority=source.issuing_authority,
                document_type=source.document_type,
                source_category=SourceCategory(source.source_category),
                jurisdiction=source.jurisdiction,
                court_level=source.court_level,
                locator=passage.locator,
                page_start=passage.page_start,
                page_end=passage.page_end,
                url=source.source_url,
                text=relevant_window(passage.text, query, max_chars),
                language=passage.language,
                publication_date=source.publication_date,
                commencement_date=source.commencement_date,
                judgment_date=source.judgment_date,
                legal_status=source.legal_status,
                verification_status=source.verification_status,
                host_note=source.host_note,
                flags=list(passage.flags or []),
                binding_note=binding_note(source, user_jurisdiction),
                part_of=chapter_of(session, passage)
                if source.document_type in ("statute", "rules")
                else None,
            )
        )
    items = prefer_general_provisions(items)
    return EvidencePacket(query=query, jurisdiction=user_jurisdiction, items=items)


LIMITED_SCOPE = re.compile(r"\bIN CERTAIN\b|\bSPECIAL PROVISIONS\b", re.IGNORECASE)


def prefer_general_provisions(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Drop a special-scope provision when the same Act's general provision is also present.

    E.g. the Industrial Relations Code's Chapter X ("... in certain establishments": three months'
    notice) next to Chapter IX (one month's notice). We rarely know whether the user's employer is
    covered, and small local models apply the stricter rule to everyone, so keep the general one.
    """
    general_sources = {i.source_id for i in items if i.part_of and not LIMITED_SCOPE.search(i.part_of)}
    kept = [
        i
        for i in items
        if not (i.part_of and LIMITED_SCOPE.search(i.part_of) and i.source_id in general_sources)
    ]
    if len(kept) == len(items):
        return items
    return [i.model_copy(update={"evidence_id": f"E{n}"}) for n, i in enumerate(kept, start=1)]


def reorder(packet: EvidencePacket, order: list[str]) -> EvidencePacket:
    """Apply a decision engine's priority order; unknown ids are ignored, missing ids keep their place."""
    by_id = {i.evidence_id: i for i in packet.items}
    seen = [eid for eid in dict.fromkeys(order) if eid in by_id]
    rest = [i.evidence_id for i in packet.items if i.evidence_id not in seen]
    return packet.model_copy(update={"items": [by_id[e] for e in [*seen, *rest]]})
