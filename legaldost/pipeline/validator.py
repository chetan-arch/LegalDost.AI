"""Citation validator.

Mechanical checks only. Passing validation means: the cited records exist, the quotes are in
them, links are the registered links, and numbers/section references used in claims appear in the
cited text. It does **not** mean the interpretation is legally correct.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from sqlalchemy.orm import Session

from legaldost.db.models import Passage
from legaldost.domain.schemas import (
    DraftAnswer,
    EvidenceItem,
    EvidencePacket,
    SourceCard,
    ValidatedClaim,
    ValidationReport,
)
from legaldost.pipeline.generator import best_sentence
from legaldost.textutil import content_tokens, normalize, numbers_in, references_in, stem

MIN_SUPPORT_LAW_TEXT = 0.25
MIN_SUPPORT_OTHER = 0.12
MIN_SUMMARY_SUPPORT = 0.5
MIN_APPLICATION_SUPPORT = 0.35


def _overlap(claim: str, evidence: str) -> float:
    c = {stem(x) for x in content_tokens(claim)}
    if not c:
        return 0.0
    e = {stem(x) for x in content_tokens(evidence)}
    return len(c & e) / len(c)


def _fact_numbers(facts: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for k, v in facts.items():
        if k.startswith("_"):
            continue
        out |= numbers_in(str(v.get("value", "")))
        out |= numbers_in(str(v.get("raw", "")))
    return out


def _metadata(item: EvidenceItem) -> str:
    """Citation metadata that claims may legitimately repeat (title, locator, dates)."""
    dates = [d.isoformat() for d in (item.publication_date, item.commencement_date, item.judgment_date) if d]
    return " ".join([item.title, item.locator, *dates])


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote's words appear verbatim and in order in the passage. Punctuation, quote
    marks and spacing are ignored (PDF extraction varies); every word must still match exactly."""
    q, t = _words(quote), _words(text)
    if len(q) < 3:
        return False
    n = len(q)
    return any(t[i : i + n] == q for i in range(len(t) - n + 1))


class CitationValidator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _db_check(self, item_passage_id: str, item_source_id: str, item_url: str) -> str | None:
        passage = self.session.get(Passage, item_passage_id)
        if passage is None:
            return "passage_missing"
        if passage.source_id != item_source_id:
            return "passage_source_mismatch"
        if passage.source.source_url != item_url:
            return "url_not_registered"
        if not passage.version.is_current or not passage.source.is_available:
            return "passage_not_current"
        if passage.source.legal_status in ("superseded", "repealed", "withdrawn"):
            return "source_superseded"
        return None

    def validate(
        self,
        draft: DraftAnswer,
        packet: EvidencePacket,
        facts: dict[str, Any],
        user_text: str,
        require_quotes: bool = False,
    ) -> tuple[list[ValidatedClaim], list[SourceCard], ValidationReport]:
        """Check a draft. With ``require_quotes``, every statement of what the law says must carry
        a quote that is found verbatim in the cited passage (used for model-written answers)."""
        report = ValidationReport()
        db_status: dict[str, str | None] = {}
        allowed_numbers = _fact_numbers(facts) | numbers_in(user_text)
        kept: list[ValidatedClaim] = []

        for claim in draft.claims:
            ids = list(dict.fromkeys(claim.evidence_ids))
            items = [packet.get(e) for e in ids]
            if not ids or any(i is None for i in items):
                report.flags.append("unknown_evidence_id")
                report.dropped_claims += 1
                continue
            valid_items = []
            for item in items:
                assert item is not None
                if item.evidence_id not in db_status:
                    db_status[item.evidence_id] = self._db_check(item.passage_id, item.source_id, item.url)
                if db_status[item.evidence_id] is None and "suspected_instructions" not in item.flags:
                    valid_items.append(item)
                elif db_status[item.evidence_id]:
                    report.flags.append(str(db_status[item.evidence_id]))
            if len(valid_items) != len(items):
                report.dropped_claims += 1
                continue
            evidence_text = " ".join(i.text for i in valid_items)
            metadata_text = " ".join(_metadata(i) for i in valid_items)
            norm_evidence = normalize(f"{evidence_text} {metadata_text}")

            quote = claim.quote.strip() if claim.quote else None
            quote_ok = False
            if quote:
                if quote_in_text(quote, valid_items[0].text):
                    quote_ok = True
                else:
                    report.flags.append("quote_mismatch")
                    report.dropped_claims += 1
                    continue
            elif require_quotes and claim.claim_type != "application":
                report.flags.append("missing_quote")
                report.dropped_claims += 1
                continue

            unsupported = (
                numbers_in(claim.text) - numbers_in(f"{evidence_text} {metadata_text}") - allowed_numbers
            )
            if unsupported:
                report.flags.append("unsupported_number")
                report.unsupported_references += sorted(unsupported)
                report.dropped_claims += 1
                continue
            claim_refs = references_in(claim.text)
            missing_refs = {
                r for r in claim_refs if r not in norm_evidence and r.split()[1] not in norm_evidence
            }
            if missing_refs:
                report.flags.append("unsupported_reference")
                report.unsupported_references += sorted(missing_refs)
                report.dropped_claims += 1
                continue

            overlap = _overlap(claim.text, evidence_text)
            support: Literal["quote_verified", "lexical", "weak"]
            threshold = MIN_SUPPORT_LAW_TEXT if claim.claim_type == "law_text" else MIN_SUPPORT_OTHER
            if quote_ok:
                support = "quote_verified"
            elif overlap >= threshold:
                support = "lexical"
            elif claim.claim_type == "application" and overlap >= MIN_SUPPORT_OTHER / 2:
                support = "weak"
            else:
                report.flags.append("weak_support")
                report.dropped_claims += 1
                continue
            kept.append(
                ValidatedClaim(
                    text=claim.text,
                    claim_type=claim.claim_type,
                    evidence_ids=ids,
                    quote=quote if quote_ok else None,
                    support=support,
                )
            )

        # Free-text fields may not introduce references or numbers absent from all evidence.
        all_evidence = " ".join(f"{i.text} {_metadata(i)}" for i in packet.items)
        all_numbers = numbers_in(all_evidence) | allowed_numbers
        norm_all = normalize(all_evidence)
        for field_name in ("summary", "legal_position", "application_to_user_facts"):
            value = getattr(draft, field_name) or ""
            bad_refs = {r for r in references_in(value) if r not in norm_all}
            bad_nums = numbers_in(value) - all_numbers
            if bad_refs or bad_nums:
                report.blocked = True
                report.flags.append(f"unsupported_in_{field_name}")
                report.unsupported_references += sorted(bad_refs | bad_nums)
        for lst_name in ("important_exceptions", "safe_next_steps"):
            for value in getattr(draft, lst_name):
                if {r for r in references_in(value) if r not in norm_all} or numbers_in(value) - all_numbers:
                    report.flags.append(f"unsupported_in_{lst_name}")
                    report.removed_items.append(value)

        report.kept_claims = len(kept)
        # The TL;DR and "how it applies" must restate verified points, not add new conclusions.
        if require_quotes and kept:
            cited_titles = " ".join(
                item.title for e in {e for c in kept for e in c.evidence_ids} if (item := packet.get(e))
            )
            verified = " ".join(f"{c.text} {c.quote or ''}" for c in kept) + " " + cited_titles
            if _overlap(draft.summary, verified) < MIN_SUMMARY_SUPPORT:
                report.summary_unsupported = True
                report.flags.append("summary_unsupported")
            facts_text = " ".join(str(v.get("value", "")) for k, v in facts.items() if not k.startswith("_"))
            if (
                draft.application_to_user_facts
                and _overlap(draft.application_to_user_facts, f"{verified} {user_text} {facts_text}")
                < MIN_APPLICATION_SUPPORT
            ):
                report.application_unsupported = True
                report.flags.append("application_unsupported")
        cards = self._cards(kept, packet, user_text)
        report.flags = list(dict.fromkeys(report.flags))
        return kept, cards, report

    @staticmethod
    def _cards(claims: list[ValidatedClaim], packet: EvidencePacket, query: str) -> list[SourceCard]:
        order = list(dict.fromkeys(e for c in claims for e in c.evidence_ids))
        cards = []
        for eid in order:
            item = packet.get(eid)
            if item is None:
                continue
            quote = next((c.quote for c in claims if c.quote and c.evidence_ids[0] == eid), None)
            cards.append(
                SourceCard(
                    evidence_id=eid,
                    passage_id=item.passage_id,
                    source_key=item.source_key,
                    title=item.title,
                    reference=item.locator,
                    source_category=item.source_category,
                    document_type=item.document_type,
                    jurisdiction=item.jurisdiction,
                    url=item.url,
                    excerpt=quote or best_sentence(item.text, query),
                    publication_date=item.publication_date,
                    commencement_date=item.commencement_date,
                    judgment_date=item.judgment_date,
                    legal_status=item.legal_status,
                    verification_status=item.verification_status,
                    host_note=item.host_note,
                    binding_note=item.binding_note,
                )
            )
        return cards
