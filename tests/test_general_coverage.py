"""Coverage beyond traffic: corpus-driven domains, the catch-all topic and high-risk escalation."""

from pathlib import Path

from legaldost.api.processing import process_text
from legaldost.domain.schemas import Escalation
from legaldost.ingestion.extract import ExtractedDocument
from legaldost.ingestion.manifest import load_manifest
from legaldost.ingestion.segment import MAX_CHARS, segment
from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters
from tests.conftest import _spec

CONSUMER_TEXT = """EXAMPLE CONSUMER CODE (FICTIONAL TEST FIXTURE)
1. Short title. This code exists only for automated tests.
2. Refund. A seller shall refund the price of a defective product returned within thirty days of purchase.
3. Complaint. A consumer may file a complaint about a defective product before the example consumer board.
"""

PROPERTY_TEXT = """EXAMPLE NEIGHBOURS CODE (FICTIONAL TEST FIXTURE)
1. Short title. This code exists only for automated tests.
2. Boundary wall. A boundary wall between neighbours may be repaired by either owner after written notice.
3. Costs. The cost of repairing a shared boundary wall is shared equally between neighbours.
"""

CRIMINAL_TEXT = """EXAMPLE OFFENCES CODE (FICTIONAL TEST FIXTURE)
1. Short title. This code exists only for automated tests.
2. Theft. Whoever commits theft of a mobile phone shall be punished with a fine under this example code.
3. Complaint. A victim of theft may give information to the example police.
"""


def ask(services, text, user):
    return process_text(services, "dev", user, text)


def _load(ingest, session, key, text, domains, **kw):
    source = ingest.register(_spec(key, legal_domains=domains, **kw))
    assert ingest.ingest_bytes(source, text.encode(), "text/plain").status == "created"
    session.commit()


def test_domain_switches_on_when_sources_are_loaded(make_services, corpus, ingest, session) -> None:
    services = make_services()
    q = "In Karnataka, can a shop refuse to refund a defective product?"
    assert ask(services, q, "c1").outcome == "unsupported_domain"
    _load(ingest, session, "example-consumer", CONSUMER_TEXT, ["consumer"])
    reply = ask(services, q, "c2")
    assert reply.outcome == "answer"
    assert {c.source_key for c in reply.answer.supporting_sources} == {"example-consumer"}
    assert "Consumer complaints" in ask(services, "help", "c3").text  # coverage list is data-driven


def test_disabled_domain_stays_off(make_services, corpus, ingest, session) -> None:
    _load(ingest, session, "example-consumer", CONSUMER_TEXT, ["consumer"])
    services = make_services()
    services.registry.domains["consumer"].enabled = False
    try:
        reply = ask(services, "In Karnataka, can a shop refuse to refund a defective product?", "d1")
        assert reply.outcome == "unsupported_domain"
    finally:
        services.registry.domains["consumer"].enabled = True


def test_catch_all_answers_from_any_loaded_domain(make_services, corpus, ingest, session) -> None:
    _load(ingest, session, "example-neighbours", PROPERTY_TEXT, ["property"])
    services = make_services()
    first = ask(services, "What does the law say about repairing a boundary wall with my neighbours?", "g1")
    assert first.outcome == "clarification" and first.answer.missing_facts == ["jurisdiction"]
    assert first.answer.topic == "general.legal"
    second = ask(services, "Karnataka", "g1")
    assert second.outcome == "answer"
    assert {c.source_key for c in second.answer.supporting_sources} == {"example-neighbours"}


def test_catch_all_abstains_instead_of_matching_generic_words(make_services, corpus) -> None:
    services = make_services()
    ask(services, "Is it legal to record a phone call without telling the other person?", "g2")
    reply = ask(services, "Karnataka", "g2")
    assert reply.outcome == "abstain"


def test_non_legal_chatter_is_not_treated_as_a_question(make_services, corpus) -> None:
    assert ask(make_services(), "what's the weather like tomorrow", "w1").outcome == "unknown_topic"


def test_high_risk_topics_recommend_a_lawyer(make_services, corpus, ingest, session) -> None:
    services = make_services()
    unsupported = ask(
        services, "Someone committed theft of my phone in Mysuru on 2026-10-01, what punishment?", "h1"
    )
    assert unsupported.outcome == "unsupported_domain" and "lawyer" in unsupported.text
    _load(ingest, session, "example-offences", CRIMINAL_TEXT, ["criminal"])
    reply = ask(
        services, "Someone committed theft of my mobile phone in Mysuru on 2026-10-01, what punishment?", "h2"
    )
    assert reply.outcome == "answer"
    assert reply.answer.recommended_escalation == Escalation.SERIOUS_MATTER
    assert "lawyer" in reply.text


def test_relevance_gate_ignores_generic_legal_words(session, embedder, corpus) -> None:
    spec = QuerySpec(
        "Is it legal for a person under the law to do this?", min_coverage=0.5, require_phrase=True
    )
    assert HybridRetriever(session, embedder).search(spec, RetrievalFilters()) == []


def test_split_passages_get_their_own_page_range() -> None:
    long_page = " ".join(f"Sentence number {i} about refunds." for i in range(120))
    doc = ExtractedDocument(
        pages=[
            "1. Title. Short title text.\n2. Refunds. Begins here.",
            long_page,
            long_page + "\n3. End. Final words.",
        ],
        paginated=True,
    )
    segments, strategy = segment(doc, "statute")
    assert strategy == "numbered"
    parts = [s for s in segments if s.label == "2"]
    assert len(parts) > 2 and all(len(s.text) <= MAX_CHARS for s in parts)
    assert parts[-1].page_start == 3 and parts[1].page_start == 2  # not the whole block's 1-3 range


def test_manifest_skips_disabled_template_entries(tmp_path: Path) -> None:
    manifest = tmp_path / "m.yaml"
    manifest.write_text(
        "name: t\nsources:\n  - source_key: todo-act\n    enabled: false\n    source_url: REPLACE_ME\n",
        encoding="utf-8",
    )
    loaded = load_manifest(manifest)
    assert loaded.entries == [] and loaded.skipped == ["todo-act"]
