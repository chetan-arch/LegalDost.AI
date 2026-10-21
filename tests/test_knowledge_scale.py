"""Scaled search indexes, the gap log and the judgment importer (all offline, fictional data)."""

import re

import httpx
from sqlalchemy import select, text

from legaldost.api.processing import process_text
from legaldost.db.models import AnswerGap, LegalSource, Passage
from legaldost.domain.registry import load_registry
from legaldost.ingestion import judgments as jmod
from legaldost.ingestion.judgments import JudgmentRecord, classify_domains, import_judgments
from legaldost.retrieval.index import LexicalIndex, reset_caches
from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters
from tests.conftest import _spec

JUDGMENT_TEXT = """IN THE EXAMPLE SUPREME COURT (FICTIONAL TEST FIXTURE)
1. The appellant was convicted for theft of a motor cycle and challenges the punishment.
2. Whoever commits theft shall be punished under the example code; the appeal is dismissed.
3. The vehicle owner may seek compensation in accordance with law.
"""


def test_fts_matches_stemmed_words(session, corpus) -> None:
    reset_caches()
    hits = LexicalIndex.search(session, ["fines"], 50)  # passage says "fine"
    texts = [session.get(Passage, pid).text for pid in hits]
    assert any("fine of 500 rupees" in t for t in texts)


def test_fts_stays_in_sync_after_reprocess(session, corpus, ingest) -> None:
    reset_caches()
    LexicalIndex.ensure(session)
    before = session.execute(text("SELECT count(*) FROM passages_fts")).scalar()
    source = session.scalar(select(LegalSource).where(LegalSource.source_key == "example-rules"))
    version = next(v for v in source.versions if v.is_current)
    ingest.reprocess(version.id)
    session.flush()
    after = session.execute(text("SELECT count(*) FROM passages_fts")).scalar()
    assert before == after == session.scalar(select(text("count(*)")).select_from(Passage.__table__))


class _MeaningEmbedder:
    """Fake 'semantic' model: everything about glass maps to one direction."""

    name = "st:fake-semantic"
    dim = 2

    def _vec(self, t: str) -> list[float]:
        return [1.0, 0.0] if re.search(r"glass|windscreen|windshield|film|window", t, re.I) else [0.0, 1.0]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text_value: str) -> list[float]:
        return self._vec(text_value)


def test_semantic_model_finds_passages_without_shared_words(session, settings, ingest, tmp_path) -> None:
    reset_caches()
    ingest.embedder = _MeaningEmbedder()
    src = ingest.register(_spec("glass-rules"))
    ingest.ingest_bytes(
        src,
        b"1. Title. Example rules for tests only.\n2. Windscreen. Safety glass in the windscreen must stay clear.\n"
        b"3. Other. Unrelated provision about parking areas.\n",
        "text/plain",
    )
    session.flush()
    retriever = HybridRetriever(
        session, _MeaningEmbedder(), cache_dir=tmp_path / "idx", min_semantic_similarity=0.9
    )
    results = retriever.search(QuerySpec("is my sunshade mesh on the rear windshield ok"), RetrievalFilters())
    texts = [session.get(Passage, r.passage_id).text for r in results]
    assert any("Safety glass in the windscreen" in t for t in texts)


def test_gap_log_keeps_keywords_not_text(make_services, corpus, session) -> None:
    services = make_services()
    process_text(services, "dev", "gap1", "My employer has not paid my salary in Bengaluru. What can I do?")
    gaps = session.scalars(select(AnswerGap)).all()
    assert len(gaps) == 1 and gaps[0].reason == "unsupported_domain" and gaps[0].domain == "employment"
    assert "salary" in gaps[0].terms
    assert all(" " not in t for t in gaps[0].terms)  # single keywords, never the sentence
    assert "bengaluru" not in gaps[0].terms  # place names are dropped


def test_classify_domains_from_judgment_text() -> None:
    domains = classify_domains(JUDGMENT_TEXT, load_registry())
    assert "criminal" in domains and domains[-1] == "general"


def test_import_judgments_end_to_end(factory, settings, ingest, monkeypatch) -> None:
    reset_caches()
    monkeypatch.setattr(
        jmod.httpx, "get", lambda url, timeout=120: httpx.Response(200, content=JUDGMENT_TEXT.encode())
    )
    rec = JudgmentRecord(
        source_key="sc-test-2099-1",
        title="EXAMPLE v. STATE (FICTIONAL)",
        court="Supreme Court of India",
        court_level="supreme_court",
        jurisdiction="IN",
        judgment_date=None,
        pdf_url="https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/data/pdf/year=2099/english/x_EN.pdf",
        identifiers={"citation": "test"},
        dataset_name="Indian Supreme Court Judgments",
        dataset_slug="indian-supreme-court-judgments",
    )

    def service_factory(session):
        ingest.session = session
        return ingest

    stats = import_judgments(factory, settings, service_factory, load_registry(), iter([rec, rec]), workers=1)
    assert stats.imported == 1  # the duplicate record is not re-imported
    with factory() as s:
        src = s.scalar(select(LegalSource).where(LegalSource.source_key == "sc-test-2099-1"))
        assert src.source_category == "secondary" and "CC-BY-4.0" in src.host_note
        assert "criminal" in src.legal_domains
    again = import_judgments(factory, settings, service_factory, load_registry(), iter([rec]), workers=1)
    assert again.imported == 0 and again.skipped_existing == 1


def test_vector_index_picks_up_new_passages_incrementally(session, settings, ingest, tmp_path) -> None:
    from legaldost.retrieval.index import VectorIndex

    reset_caches()
    ingest.embedder = _MeaningEmbedder()
    first = ingest.register(_spec("parking-rules"))
    ingest.ingest_bytes(
        first, b"1. Title. Example rules.\n2. Parking. No parking near a hospital gate.\n", "text/plain"
    )
    session.flush()
    index = VectorIndex(tmp_path / "idx")
    before = index.search(session, [1.0, 0.0], 100)
    second = ingest.register(_spec("glass-rules-2"))
    ingest.ingest_bytes(
        second, b"1. Title. Example rules.\n2. Glass. Safety glass must stay clear.\n", "text/plain"
    )
    session.flush()
    after = index.search(session, [1.0, 0.0], 100)
    new_ids = set(after) - set(before)
    assert new_ids and any("Safety glass" in session.get(Passage, pid).text for pid in new_ids)
    assert all(abs(after[pid] - before[pid]) < 1e-6 for pid in before)  # earlier rows reused unchanged


def test_case_key_groups_copies_of_one_judgment() -> None:
    from legaldost.retrieval.search import _case_key

    assert _case_key("AVISHEK GOENKA versus UNION OF INDIA AND ANR.") == _case_key(
        "AVISHEK GOENKA versus UNION OF INDIA & ANR."
    )
    assert _case_key("A versus STATE OF KERALA") != _case_key("B versus STATE OF KERALA")


def test_statute_passages_know_their_chapter(session, ingest) -> None:
    from legaldost.pipeline.evidence import chapter_of

    src = ingest.register(_spec("chaptered-code", document_type="statute"))
    ingest.ingest_bytes(
        src,
        b"CHAPTER I\nPRELIMINARY\n1. Title. Example code for tests only.\n"
        b"2. Notice. A worker shall be given one month's notice.\n"
        b"CHAPTER II\nSPECIAL PROVISIONS IN CERTAIN\nESTABLISHMENTS\n"
        b"3. Longer notice. A worker in such an establishment shall be given three months' notice.\n",
        "text/plain",
    )
    session.flush()
    passages = {
        p.section_label: p for p in session.scalars(select(Passage).where(Passage.source_id == src.id))
    }
    assert chapter_of(session, passages["3"]) == "CHAPTER II — SPECIAL PROVISIONS IN CERTAIN ESTABLISHMENTS"
    # The heading at the end of section 2's passage opens the next chapter, not section 2's own.
    assert not (chapter_of(session, passages["2"]) or "").startswith("CHAPTER II")


def test_special_scope_provision_dropped_when_general_one_present() -> None:
    from legaldost.domain.schemas import EvidenceItem
    from legaldost.pipeline.evidence import prefer_general_provisions

    def item(eid: str, source: str, part_of: str | None) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=eid,
            passage_id=eid,
            source_id=source,
            source_key=source,
            title="t",
            issuing_authority="a",
            document_type="statute",
            source_category="primary_official",
            jurisdiction="IN",
            court_level=None,
            locator="s. 1",
            page_start=None,
            page_end=None,
            url="https://example.test",
            text="x",
            language="en",
            publication_date=None,
            commencement_date=None,
            judgment_date=None,
            legal_status="unknown",
            verification_status="unverified",
            host_note=None,
            part_of=part_of,
        )

    items = [
        item(
            "E1", "code", "CHAPTER X — SPECIAL PROVISIONS RELATING TO RETRENCHMENT IN CERTAIN ESTABLISHMENTS"
        ),
        item("E2", "code", "CHAPTER IX — LAY-OFF, RETRENCHMENT AND CLOSURE"),
        item("E3", "other", "CHAPTER II — SPECIAL PROVISIONS IN CERTAIN AREAS"),
    ]
    kept = prefer_general_provisions(items)
    assert [i.passage_id for i in kept] == ["E2", "E3"]  # E3 has no general sibling, so it stays
    assert [i.evidence_id for i in kept] == ["E1", "E2"]  # renumbered


def test_judgment_needs_a_question_specific_anchor(session, ingest, tmp_path) -> None:
    def judgment(key: str, body: bytes) -> None:
        src = ingest.register(_spec(key, document_type="judgment", legal_domains=["employment"]))
        ingest.ingest_bytes(src, body, "text/plain")

    reset_caches()
    judgment(
        "jdg-accident-salary",
        b"1. The deceased helper was receiving a salary of Rs 2400 per month from his employer.\n"
        b"2. The insurer must pay compensation for the accident with interest.\n",
    )
    judgment(
        "jdg-wages-withheld",
        b"1. The employer withheld payment of wages beyond the time permitted.\n"
        b"2. The employee's salary for those months must be paid with interest.\n",
    )
    session.flush()
    question = "My employer has not paid my salary for two months. What can I do?"
    spec = QuerySpec(
        question,
        expansion_terms=["employer", "employee", "wages", "payment of wages"],
        anchor_terms=["wages", "payment of wages"],
    )
    retriever = HybridRetriever(session, ingest.embedder, cache_dir=tmp_path / "idx")
    found = {
        session.get(LegalSource, r.source_id).source_key
        for r in retriever.search(spec, RetrievalFilters(domains=["employment"]), limit=10)
    }
    assert "jdg-wages-withheld" in found
    assert "jdg-accident-salary" not in found  # mentions salary and employer, not this question
