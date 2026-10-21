from legaldost.db.models import LegalSource, Passage
from legaldost.domain.schemas import DraftAnswer, DraftClaim, EvidenceStatus
from legaldost.pipeline.evidence import build_packet
from legaldost.pipeline.validator import CitationValidator
from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters


def _search(session, embedder, text, jurisdictions=("IN", "IN-KA"), terms=()):
    return HybridRetriever(session, embedder).search(
        QuerySpec(text, list(terms)),
        RetrievalFilters(jurisdictions=list(jurisdictions), domains=["traffic"]),
        limit=6,
    )


def _sources(session, results):
    return [session.get(Passage, r.passage_id).source.source_key for r in results]


def test_retrieves_relevant_rule_with_identifier_boost(session, embedder, corpus) -> None:
    results = _search(session, embedder, "what does rule 4 say about the fine")
    top = session.get(Passage, results[0].passage_id)
    assert top.source.source_key == "example-rules" and top.section_label == "4"
    assert "rule 4" in results[0].matched_identifiers


def test_filters_superseded_other_state_and_injection(session, embedder, corpus) -> None:
    results = _search(session, embedder, "tinted film on side windows visual transmission of light")
    keys = _sources(session, results)
    texts = [session.get(Passage, r.passage_id).text.lower() for r in results]
    assert "example-rules" in keys
    assert "example-old-circular" not in keys  # superseded
    assert "example-tn-rules" not in keys  # other state's rules
    assert not any("ignore all previous instructions" in t for t in texts)  # flagged passage
    assert "example-kl-judgment" in keys  # judgments stay eligible (labelled persuasive later)


def test_no_lexical_match_returns_nothing(session, embedder, corpus) -> None:
    assert _search(session, embedder, "gratuity payment employer") == []


def _packet(session, embedder):
    results = _search(session, embedder, "film pasted on side windows visual transmission")
    return build_packet(session, "film", results, "IN-KA", 1800)


def test_binding_note_for_other_state_high_court(session, embedder, corpus) -> None:
    packet = _packet(session, embedder)
    judgment = next(i for i in packet.items if i.source_key == "example-kl-judgment")
    assert judgment.binding_note and "not binding in Karnataka" in judgment.binding_note


def _rules_item(packet):
    return next(i for i in packet.items if i.source_key == "example-rules" and "pasted" in i.text)


def test_validator_keeps_supported_and_drops_fabricated(session, embedder, corpus) -> None:
    packet = _packet(session, embedder)
    item = _rules_item(packet)
    draft = DraftAnswer(
        summary="The example rules restrict film on safety glass.",
        legal_position="Film pasted after manufacture is not allowed under the example rules.",
        claims=[
            DraftClaim(
                text="No film shall be pasted on the safety glass after manufacture.",
                evidence_ids=[item.evidence_id],
                quote="No film shall be pasted on the safety glass",
            ),
            DraftClaim(text="Made-up claim", evidence_ids=["E99"]),
            DraftClaim(
                text="Quote not in source",
                evidence_ids=[item.evidence_id],
                quote="Film is always allowed in every state",
            ),
            DraftClaim(text="The fine is 5000 rupees.", evidence_ids=[item.evidence_id]),
            DraftClaim(
                text="Section 999 also prohibits film pasted on glass.", evidence_ids=[item.evidence_id]
            ),
        ],
        proposed_status=EvidenceStatus.SUFFICIENT,
    )
    claims, cards, report = CitationValidator(session).validate(draft, packet, {}, "film")
    assert len(claims) == 1 and claims[0].support == "quote_verified"
    assert {"unknown_evidence_id", "quote_mismatch", "unsupported_number"} <= set(report.flags)
    assert report.dropped_claims == 4
    assert cards[0].url == "https://example.test/example-rules.txt"
    assert cards[0].passage_id == item.passage_id
    assert not report.blocked


def test_validator_blocks_unsupported_reference_in_summary(session, embedder, corpus) -> None:
    packet = _packet(session, embedder)
    item = _rules_item(packet)
    draft = DraftAnswer(
        summary="Under Section 777 of the Act you will be fined.",
        legal_position="x",
        claims=[
            DraftClaim(
                text="No film shall be pasted on the safety glass after manufacture.",
                evidence_ids=[item.evidence_id],
            )
        ],
    )
    _, _, report = CitationValidator(session).validate(draft, packet, {}, "film")
    assert report.blocked and "section 777" in report.unsupported_references


def test_validator_rejects_url_not_matching_registered_source(session, embedder, corpus) -> None:
    packet = _packet(session, embedder)
    item = _rules_item(packet)
    source = session.get(LegalSource, item.source_id)
    source.source_url = "https://example.test/moved.txt"  # registry changed after packet was built
    session.flush()
    draft = DraftAnswer(
        summary="s",
        legal_position="p",
        claims=[
            DraftClaim(
                text="No film shall be pasted on the safety glass after manufacture.",
                evidence_ids=[item.evidence_id],
            )
        ],
    )
    claims, _, report = CitationValidator(session).validate(draft, packet, {}, "film")
    assert not claims and "url_not_registered" in report.flags


def test_user_stated_numbers_are_allowed(session, embedder, corpus) -> None:
    packet = _packet(session, embedder)
    item = _rules_item(packet)
    draft = DraftAnswer(
        summary="s",
        legal_position="p",
        claims=[
            DraftClaim(
                text="Your 35 percent glass is below the 50 percent side window figure in the example rules.",
                evidence_ids=[e.evidence_id for e in packet.items if "50 percent" in e.text][:1]
                or [item.evidence_id],
                claim_type="application",
            )
        ],
    )
    facts = {"vlt_percent": {"value": 35.0, "source": "user"}}
    claims, _, report = CitationValidator(session).validate(draft, packet, facts, "my glass is 35% vlt")
    assert claims, report.flags
