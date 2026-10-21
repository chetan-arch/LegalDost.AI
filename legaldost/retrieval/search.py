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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from legaldost.db.models import DocumentVersion, LegalSource, Passage
from legaldost.domain.schemas import RetrievedPassage
from legaldost.retrieval.embeddings import Embedder, cosine
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
    def __init__(self, session: Session, embedder: Embedder, k_rrf: int = 60) -> None:
        self.session = session
        self.embedder = embedder
        self.k_rrf = k_rrf
        # The default hashing embedder matches surface patterns, not meaning, so it gets a smaller
        # say in the fused ranking than keyword search. Real semantic models get equal weight.
        self.vector_weight = 0.3 if embedder.name.startswith("hashing") else 1.0

    # -- eligibility ------------------------------------------------------------------------
    def _eligible(self, filters: RetrievalFilters) -> list[_Candidate]:
        stmt = (
            select(Passage, LegalSource)
            .join(DocumentVersion, Passage.version_id == DocumentVersion.id)
            .join(LegalSource, Passage.source_id == LegalSource.id)
            .where(DocumentVersion.is_current.is_(True))
            .where(DocumentVersion.extraction_status.in_(("succeeded", "partial")))
            .where(LegalSource.is_available.is_(True))
        )
        if not filters.include_superseded:
            stmt = stmt.where(LegalSource.legal_status.not_in(EXCLUDED_STATUSES))
        if filters.document_types:
            stmt = stmt.where(LegalSource.document_type.in_(filters.document_types))
        out: list[_Candidate] = []
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
            out.append(
                _Candidate(
                    passage.id,
                    source.id,
                    passage.version_id,
                    passage.text,
                    passage.section_label,
                    passage.embedding,
                )
            )
        return out

    # -- lexical ------------------------------------------------------------------------------
    @staticmethod
    def _bm25(
        query: dict[str, float], docs: list[list[str]], k1: float = 1.2, b: float = 0.75
    ) -> list[float]:
        n = len(docs)
        if n == 0:
            return []
        avgdl = sum(len(d) for d in docs) / n or 1.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        scores = []
        for d in docs:
            tf = Counter(d)
            s = 0.0
            for term, weight in query.items():
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                f = tf[term]
                s += weight * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl))
            scores.append(s)
        return scores

    def _lexical_portable(self, spec: QuerySpec, cands: list[_Candidate]) -> dict[str, float]:
        weights = spec.weighted_terms()
        docs = [[stem(t) for t in content_tokens(f"{c.section_label or ''} {c.text}")] for c in cands]
        scores = self._bm25(weights, docs)
        primary = {stem(t) for t in content_tokens(spec.text)}
        result = {}
        for cand, doc, score in zip(cands, docs, scores, strict=True):
            matched = set(doc) & set(weights)
            # Require at least two distinct query terms, or one term from the user's own words
            # plus one expansion term, to reduce single-word coincidences.
            if score > 0 and (len(matched) >= 2 or (matched & primary and len(primary) == 1)):
                result[cand.passage_id] = score
        return result

    @staticmethod
    def _relevant(spec: QuerySpec, cand: _Candidate) -> bool:
        """Relevance gate applied to every lexical hit (both backends).

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
        if not distinctive:
            return matched_extra >= 2
        matched_user = len(distinctive & doc)
        needed = max(1, math.ceil(spec.min_coverage * len(distinctive)))
        if not (matched_user >= needed and matched_user + matched_extra >= 2):
            return False
        seq = [stem(t) for t in content_tokens(cand.text)]
        phrase_hit = bool(spec.phrases() & set(zip(seq, seq[1:], strict=False)))
        if spec.require_phrase:
            return phrase_hit
        # Anchor: a curated topic search term, or a two-word phrase from the question. Scattered
        # common words ("police" ... "fine") are not enough on their own.
        return phrase_hit or matched_extra >= 1

    def _lexical_postgres(self, spec: QuerySpec, cands: list[_Candidate]) -> dict[str, float]:
        terms = sorted({t for t in spec.weighted_terms() if re.fullmatch(r"[a-z0-9]+", t)})
        if not terms:
            return {}
        rows = self.session.execute(
            text(
                "SELECT id, ts_rank_cd(tsv, to_tsquery('english', :q)) AS r FROM passages "
                "WHERE tsv @@ to_tsquery('english', :q) AND id = ANY(:ids)"
            ),
            {"q": " | ".join(terms), "ids": [c.passage_id for c in cands]},
        )
        return {row.id: float(row.r) for row in rows}

    # -- search -------------------------------------------------------------------------------
    def search(
        self,
        spec: QuerySpec,
        filters: RetrievalFilters,
        limit: int = 6,
        pool: int = 40,
        max_per_source: int = 3,
    ) -> list[RetrievedPassage]:
        cands = self._eligible(filters)
        if not cands:
            return []
        dialect = self.session.get_bind().dialect.name
        lexical = (
            self._lexical_postgres(spec, cands)
            if dialect == "postgresql"
            else self._lexical_portable(spec, cands)
        )
        by_id_all = {c.passage_id: c for c in cands}
        lexical = {pid: s for pid, s in lexical.items() if self._relevant(spec, by_id_all[pid])}
        identifiers = spec.identifiers()
        ident_hits = {
            c.passage_id: hits
            for c in cands
            if (hits := _identifier_matches(identifiers, c.text, c.section_label))
        }
        qvec = self.embedder.embed([" ".join([spec.text, *spec.expansion_terms])])[0]
        vector = {c.passage_id: cosine(qvec, c.embedding) for c in cands if c.embedding}

        lex_rank = {
            pid: i for i, pid in enumerate(sorted(lexical, key=lexical.__getitem__, reverse=True)[:pool])
        }
        vec_rank = {
            pid: i for i, pid in enumerate(sorted(vector, key=vector.__getitem__, reverse=True)[:pool])
        }
        by_id = {c.passage_id: c for c in cands}
        fused: list[RetrievedPassage] = []
        for pid in set(lex_rank) | set(ident_hits):
            score = 1.0 / (self.k_rrf + lex_rank.get(pid, pool))
            if pid in vec_rank:
                score += self.vector_weight / (self.k_rrf + vec_rank[pid])
            if pid in ident_hits:
                score += 0.02
            c = by_id[pid]
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
        results = []
        for r in fused:
            if per_source[r.source_id] >= max_per_source:
                continue
            per_source[r.source_id] += 1
            results.append(r)
            if len(results) >= limit:
                break
        return results
