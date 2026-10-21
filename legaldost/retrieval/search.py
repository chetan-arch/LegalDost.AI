"""Hybrid legal retrieval: lexical (BM25 / PostgreSQL FTS) + vectors + metadata filters + RRF.

Results are identified passages (``RetrievedPassage``), never anonymous chunks. A passage must
have a lexical or exact-identifier match to be eligible: vector similarity alone is not enough
evidence for a legal claim.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from legaldost.db.models import DocumentVersion, LegalSource, Passage
from legaldost.domain.schemas import RetrievedPassage
from legaldost.retrieval.embeddings import Embedder
from legaldost.retrieval.index import LexicalIndex, VectorIndex
from legaldost.textutil import content_tokens, normalize, references_in, stem

EXCLUDED_STATUSES = ("superseded", "repealed", "withdrawn")


@dataclass
class RetrievalFilters:
    jurisdictions: list[str] | None = None  # applies to statutes/rules/notifications
    domains: list[str] | None = None
    include_superseded: bool = False
    document_types: list[str] | None = None
    as_of: date | None = None


# Words that appear in almost every legal text or question and so say nothing about relevance.
GENERIC_TERMS = frozenset(
    stem(w)
    for w in (
        "law laws legal illegal legally lawful unlawful act acts section sections rule rules person persons "
        "people right rights allowed allow permitted permit court courts case cases india indian state states "
        "government shall provided under whether someone something anyone get got want know tell please "
        "help need can could matter thing things way day days time year years"
    ).split()
)


@dataclass
class QuerySpec:
    text: str
    expansion_terms: list[str] = field(default_factory=list)
    # Share of the user's distinctive words a passage must contain to count as relevant.
    min_coverage: float = 0.2
    # Also require one adjacent word pair from the question (e.g. "phone call") in the passage.
    # Used for the catch-all topic, which has no curated search terms to anchor relevance.
    require_phrase: bool = False

    def phrases(self) -> set[tuple[str, str]]:
        tokens = [stem(t) for t in content_tokens(self.text) if not t.isdigit()]
        return {
            (a, b)
            for a, b in zip(tokens, tokens[1:], strict=False)
            if a not in GENERIC_TERMS or b not in GENERIC_TERMS
        }

    def distinctive_terms(self) -> set[str]:
        from legaldost.domain.facts import STATE_CODES

        places = {stem(t) for name in STATE_CODES for t in content_tokens(name)}
        return {
            stem(t)
            for t in content_tokens(self.text)
            if not t.isdigit() and stem(t) not in GENERIC_TERMS and stem(t) not in places
        }

    def weighted_terms(self) -> dict[str, float]:
        weights: dict[str, float] = {}
        for tok in content_tokens(self.text):
            weights[stem(tok)] = max(weights.get(stem(tok), 0.0), 1.0)
        for term in self.expansion_terms:
            for tok in content_tokens(term):
                weights.setdefault(stem(tok), 0.5)
        return weights

    def identifiers(self) -> set[str]:
        return references_in(" ".join([self.text, *self.expansion_terms]))


@dataclass
class _Candidate:
    passage_id: str
    source_id: str
    version_id: str
    text: str
    section_label: str | None
    embedding: list[float] | None
    case_key: str = ""  # copies of one judgment (several reporters, re-uploads) share this


_CASE_FILLER = {"and", "anr", "ors", "others", "another", "the", "versus", "vs", "v", "of", "m", "s"}


def _phrase_matches(terms: list[str], seq: list[str]) -> int:
    """How many distinct multi-word terms occur as consecutive (stemmed) words in ``seq``."""
    text = " " + " ".join(seq) + " "
    found = set()
    for term in terms:
        words = [stem(t) for t in content_tokens(term)]
        if len(words) >= 2 and f" {' '.join(words)} " in text:
            found.add(tuple(words))
    return len(found)


def _case_key(title: str) -> str:
    """'AVISHEK GOENKA versus UNION OF INDIA & ANR.' and '... AND ANR.' name the same case."""
    words = [w for w in re.findall(r"[a-z]+", title.lower()) if w not in _CASE_FILLER]
    return "case:" + " ".join(words[:6])


def _identifier_matches(identifiers: set[str], passage_text: str, section_label: str | None) -> list[str]:
    hits = []
    norm = normalize(passage_text)
    label = (section_label or "").lower()
    for ident in identifiers:
        kind, number = ident.split(" ", 1)
        if ident in norm or re.search(rf"(^|\s){re.escape(number)}\.\s", norm[:12]) or label == number:
            hits.append(f"{kind} {number}")
    return hits


class HybridRetriever:
    """Keyword index + vector index -> candidate set -> eligibility filters -> relevance gate -> RRF."""

    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        k_rrf: int = 60,
        cache_dir: Path | None = None,
        lexical_pool: int = 400,
        vector_pool: int = 200,
        min_semantic_similarity: float | None = None,
    ) -> None:
        from legaldost.config import get_settings

        settings = get_settings()
        self.session = session
        self.embedder = embedder
        self.k_rrf = k_rrf
        self.lexical_pool = lexical_pool
        self.vector_pool = vector_pool
        self.vectors = VectorIndex(cache_dir or settings.data_dir / "index")
        # The hashing embedder matches surface patterns, not meaning: it only re-ranks keyword hits.
        # A real semantic model gets an equal say and may also contribute passages on its own when
        # the similarity is high (this is what links "windshield" to "windscreen").
        self.semantic = not embedder.name.startswith("hashing")
        self.vector_weight = 1.0 if self.semantic else 0.3
        self.min_semantic_similarity = (
            settings.semantic_min_similarity if min_semantic_similarity is None else min_semantic_similarity
        )

    # -- eligibility ------------------------------------------------------------------------
    def _eligible(self, filters: RetrievalFilters, ids: set[str]) -> dict[str, _Candidate]:
        out: dict[str, _Candidate] = {}
        id_list = list(ids)
        for i in range(0, len(id_list), 500):
            stmt = (
                select(Passage, LegalSource)
                .join(DocumentVersion, Passage.version_id == DocumentVersion.id)
                .join(LegalSource, Passage.source_id == LegalSource.id)
                .where(Passage.id.in_(id_list[i : i + 500]))
                .where(DocumentVersion.is_current.is_(True))
                .where(DocumentVersion.extraction_status.in_(("succeeded", "partial")))
                .where(LegalSource.is_available.is_(True))
            )
            if not filters.include_superseded:
                stmt = stmt.where(LegalSource.legal_status.not_in(EXCLUDED_STATUSES))
            if filters.document_types:
                stmt = stmt.where(LegalSource.document_type.in_(filters.document_types))
            for passage, source in self.session.execute(stmt):
                if "suspected_instructions" in (passage.flags or []):
                    continue
                if (
                    filters.jurisdictions
                    and source.document_type != "judgment"
                    and source.jurisdiction not in filters.jurisdictions
                ):
                    continue
                if filters.domains and not set(filters.domains) & set(source.legal_domains or []):
                    continue
                if filters.as_of and source.commencement_date and source.commencement_date > filters.as_of:
                    continue
                case_key = _case_key(source.title) if source.document_type == "judgment" else source.id
                out[passage.id] = _Candidate(
                    passage.id,
                    source.id,
                    passage.version_id,
                    passage.text,
                    passage.section_label,
                    None,
                    case_key,
                )
        return out

    @staticmethod
    def _relevant(spec: QuerySpec, cand: _Candidate) -> bool:
        """Relevance gate applied to every keyword hit (both backends).

        A passage must contain enough of the user's distinctive words (not generic legal words
        like "law" or "person"), and at least two query terms overall including expansion terms.
        """
        doc = {stem(t) for t in content_tokens(f"{cand.section_label or ''} {cand.text}")}
        distinctive = spec.distinctive_terms()
        expansion = {stem(t) for term in spec.expansion_terms for t in content_tokens(term)} - GENERIC_TERMS
        # Non-English questions (e.g. Kannada) cannot match English statute words directly; for
        # them relevance rests on the topic's English search terms instead.
        distinctive = {t for t in distinctive if re.match(r"[a-z0-9]", t)}
        matched_extra = len((expansion - distinctive) & doc)
        seq = [stem(t) for t in content_tokens(cand.text)]
        # Statutes rarely use the user's own words ("sun shade", "windshield"). Two different
        # curated multi-word legal phrases ("safety glazing", "visual transmission of light")
        # appearing verbatim are strong evidence on their own.
        if _phrase_matches(spec.expansion_terms, seq) >= 2:
            return True
        if not distinctive:
            return matched_extra >= 2
        matched_user = len(distinctive & doc)
        needed = max(1, math.ceil(spec.min_coverage * len(distinctive)))
        if not (matched_user >= needed and matched_user + matched_extra >= 2):
            return False
        phrase_hit = bool(spec.phrases() & set(zip(seq, seq[1:], strict=False)))
        if spec.require_phrase:
            return phrase_hit
        # Anchor: a curated topic search term, or a two-word phrase from the question. Scattered
        # common words ("police" ... "fine") are not enough on their own.
        return phrase_hit or matched_extra >= 1

    def _query_words(self, spec: QuerySpec) -> list[str]:
        words = content_tokens(" ".join([spec.text, *spec.expansion_terms]))
        useful = [w for w in words if stem(w) not in GENERIC_TERMS]
        return useful or words

    # -- search -------------------------------------------------------------------------------
    def search(
        self,
        spec: QuerySpec,
        filters: RetrievalFilters,
        limit: int = 6,
        pool: int = 40,
        max_per_source: int = 3,
        max_per_case: int = 1,
        reserve_law: int = 3,
    ) -> list[RetrievedPassage]:
        lex_raw = LexicalIndex.search(self.session, self._query_words(spec), self.lexical_pool)
        qvec = self.embedder.embed_query(" ".join([spec.text, *spec.expansion_terms]))
        vec_raw = self.vectors.search(self.session, qvec, self.vector_pool)
        cands = self._eligible(filters, set(lex_raw) | set(vec_raw))
        if not cands:
            return []
        lexical = {pid: s for pid, s in lex_raw.items() if pid in cands and self._relevant(spec, cands[pid])}
        vector = {pid: s for pid, s in vec_raw.items() if pid in cands}
        semantic_only = (
            {pid for pid, s in vector.items() if s >= self.min_semantic_similarity and pid not in lexical}
            if self.semantic
            else set()
        )
        identifiers = spec.identifiers()
        ident_hits = {
            pid: hits
            for pid, c in cands.items()
            if (hits := _identifier_matches(identifiers, c.text, c.section_label))
        }
        lex_rank = {
            pid: i for i, pid in enumerate(sorted(lexical, key=lexical.__getitem__, reverse=True)[:pool])
        }
        vec_rank = {
            pid: i for i, pid in enumerate(sorted(vector, key=vector.__getitem__, reverse=True)[:pool])
        }
        fused: list[RetrievedPassage] = []
        for pid in set(lex_rank) | set(ident_hits) | semantic_only:
            score = 1.0 / (self.k_rrf + lex_rank.get(pid, pool))
            if pid in vec_rank:
                score += self.vector_weight / (self.k_rrf + vec_rank[pid])
            if pid in ident_hits:
                score += 0.02
            c = cands[pid]
            fused.append(
                RetrievedPassage(
                    passage_id=pid,
                    source_id=c.source_id,
                    version_id=c.version_id,
                    score=score,
                    lexical_score=lexical.get(pid, 0.0),
                    vector_score=vector.get(pid, 0.0),
                    matched_identifiers=ident_hits.get(pid, []),
                )
            )
        fused.sort(key=lambda r: r.score, reverse=True)
        per_source: Counter[str] = Counter()
        per_case: Counter[str] = Counter()

        def is_judgment(r: RetrievedPassage) -> bool:
            return cands[r.passage_id].case_key.startswith("case:")

        # The law itself comes first: keep up to `reserve_law` slots for Acts, rules and
        # notifications, so a large judgment collection cannot crowd out the statute it interprets.
        law_first = [r for r in fused if not is_judgment(r)][:reserve_law]
        ordered = law_first + [r for r in fused if r not in law_first]
        results = []
        for r in ordered:
            case = cands[r.passage_id].case_key
            if per_source[r.source_id] >= max_per_source or (
                is_judgment(r) and per_case[case] >= max_per_case
            ):
                continue
            per_source[r.source_id] += 1
            per_case[case] += 1
            results.append(r)
            if len(results) >= limit:
                break
        results.sort(key=lambda r: r.score, reverse=True)
        return results
