import json
import re

from sqlalchemy import select

from legaldost.api.processing import process_text
from legaldost.db.models import AnswerLog, Conversation, Passage, UsageRecord
from legaldost.domain.schemas import DraftAnswer, DraftClaim, EvidenceStatus
from legaldost.llm.base import LLMUnavailable
from tests.conftest import FakeLLM

TINT_Q = "I have been stopped by traffic police in Karnataka because of my tinted windows. My glass has 50% VLT. Can they fine me?"


def ask(services, text, user="u1"):
    return process_text(services, "dev", user, text)


def evidence_ids(prompt: str) -> dict[str, str]:
    """Map evidence id -> text from the evidence JSON embedded in the generator prompt."""
    items = json.loads(re.search(r"<evidence>\n(.*)\n</evidence>", prompt, re.S).group(1))
    return {i["id"]: i["text"] for i in items}


def test_clarifies_before_answering_then_uses_follow_up(make_services, corpus, session) -> None:
    services = make_services()
    first = ask(services, TINT_Q)
    assert first.outcome == "clarification"
    assert first.answer.missing_facts == ["glazing_type"]
    assert "film" in first.text.lower() and "manufacturer" in first.text.lower()

    second = ask(services, "It is a film I had applied after buying the car")
    assert second.outcome == "answer"
    answer = second.answer
    assert answer.evidence_status == EvidenceStatus.PARTIAL  # extractive + unreviewed sources
    assert answer.supporting_sources
    for card in answer.supporting_sources:  # every displayed citation resolves to a stored passage
        passage = session.get(Passage, card.passage_id)
        assert passage is not None and passage.source.source_url == card.url
        assert " ".join(card.excerpt.split()).lower() in " ".join(passage.text.split()).lower()
    assert "example-old-circular" not in {c.source_key for c in answer.supporting_sources}


def test_no_evidence_means_abstention(make_services, corpus) -> None:
    services = make_services()
    reply = ask(services, "In Karnataka do I need to carry my PUC pollution certificate in DigiLocker?")
    assert reply.outcome == "abstain"
    assert "can't give you a verified answer" in reply.text


def test_unsupported_domain_is_not_answered(make_services, corpus) -> None:
    reply = ask(make_services(), "Can a shop refuse to refund a defective product?")
    assert reply.outcome == "unsupported_domain"


def test_emergency_and_prohibited(make_services, corpus) -> None:
    services = make_services()
    assert ask(services, "The officer is beating me right now").outcome == "emergency"
    assert "112" in ask(services, "someone is attacking me help").text
    declined = ask(services, "how much bribe should I pay the police to let me go")
    assert declined.outcome == "declined" and "can't help" in declined.text


def test_modes_and_commands(make_services, corpus, session) -> None:
    services = make_services()
    ask(services, "In Karnataka my car has a sun film pasted on the side windows. Can police fine me?", "m1")
    more = ask(services, "MORE", "m1")
    assert more.outcome == "mode_explain"
    sources = ask(services, "sources", "m1")
    assert sources.outcome == "mode_evidence" and "https://example.test/" in sources.text
    assert ask(services, "DELETE MY DATA", "m1").outcome == "deleted"
    assert session.scalars(select(Conversation)).all() == [] or all(
        c.user_key != "m1" for c in session.scalars(select(Conversation))
    )
    assert ask(services, "more", "m1").outcome == "no_previous"


def test_conversations_store_no_raw_user_id_and_logs_no_text(make_services, corpus, session) -> None:
    services = make_services()
    ask(services, TINT_Q, "+919999999999")
    convs = session.scalars(select(Conversation)).all()
    assert convs and all("9999999999" not in c.user_key for c in convs)
    for log in session.scalars(select(AnswerLog)):
        assert "VLT" not in json.dumps([log.outcome, log.validator_flags, log.topic, log.intent])


KANNADA_Q = "ಬೆಂಗಳೂರಿನಲ್ಲಿ ನನ್ನ ಕಾರಿನ ಗಾಜಿಗೆ ಕಪ್ಪು ಫಿಲ್ಮ್ ಅಂಟಿಸಿದ್ದೇನೆ. ಪೊಲೀಸರು ದಂಡ ಹಾಕಬಹುದೇ?"


def test_english_only_by_default(make_services, corpus) -> None:
    services = make_services()
    reply = ask(services, KANNADA_Q, "k1")
    assert reply.outcome == "language_unsupported" and "only reply in English" in reply.text
    assert ask(services, "KANNADA", "k1").outcome == "language_unsupported"
    assert ask(services, "explain this in Kannada please", "k1").outcome == "language_unsupported"
    assert "KANNADA" not in ask(services, "help", "k1").text


def test_kannada_still_works_when_enabled(make_services, corpus) -> None:
    reply = ask(make_services(supported_languages=["en", "kn"]), KANNADA_Q, "k2")
    assert reply.outcome == "answer"
    assert reply.answer.language == "kn"
    assert "ಸಾಕ್ಷ್ಯ" in reply.text


def test_capability_questions_get_help(make_services, corpus) -> None:
    services = make_services()
    for text in ["What can you help me with?", "hi, what can you do", "How does this work?", "I need help"]:
        reply = ask(services, text, "cap")
        assert reply.outcome == "help", text
        assert "Try asking" in reply.text and "Traffic and vehicles" in reply.text
    # A real question that happens to start with "can you help me" is still a legal question.
    assert (
        ask(services, "Can you help me with tinted film on my car windows in Karnataka?", "cap2").outcome
        != "help"
    )


def _good_llm() -> FakeLLM:
    def respond(prompt: str) -> DraftAnswer:
        ev = evidence_ids(prompt)
        eid = next(k for k, v in ev.items() if "No film shall be pasted" in v)
        return DraftAnswer(
            summary="Under the example rules, film pasted on safety glass after manufacture is not allowed.",
            legal_position="The example rules prohibit pasting film after manufacture.",
            claims=[
                DraftClaim(
                    text="No film shall be pasted on the safety glass after manufacture.",
                    evidence_ids=[eid],
                    quote="No film shall be pasted on the safety glass after manufacture",
                )
            ],
            application_to_user_facts="You said the film was added later, so this rule is relevant to you.",
            safe_next_steps=["Ask the officer for a written challan."],
            proposed_status=EvidenceStatus.SUFFICIENT,
        )

    return FakeLLM(respond)


def test_llm_answer_is_capped_until_sources_are_reviewed(make_services, corpus, session, ingest) -> None:
    llm = _good_llm()
    services = make_services(provider=llm)
    q = "In Karnataka my car has a film pasted on the windows after purchase. Can I be fined?"
    reply = ask(services, q, "l1")
    assert reply.answer.generator == "llm"
    assert reply.answer.evidence_status == EvidenceStatus.PARTIAL  # model said sufficient; cap applies
    assert session.scalars(select(UsageRecord)).first().cost_usd > 0

    ingest.mark_reviewed("example-rules", "Adv. Test Reviewer")
    ingest.set_status("example-rules", "in_force", note="fixture")
    session.commit()
    reply = ask(services, q, "l2")
    assert reply.answer.evidence_status == EvidenceStatus.SUFFICIENT


def test_llm_fabricated_citation_is_blocked(make_services, corpus) -> None:
    def respond(prompt: str) -> DraftAnswer:
        return DraftAnswer(
            summary="Section 4321 of the Motor Vehicles Act makes this a crime with a 10000 rupee fine.",
            legal_position="Definitely illegal.",
            claims=[
                DraftClaim(
                    text="Section 4321 imposes a 10000 rupee fine.",
                    evidence_ids=["E1"],
                    quote="Section 4321 imposes a fine",
                )
            ],
            proposed_status=EvidenceStatus.SUFFICIENT,
        )

    services = make_services(provider=FakeLLM(respond))
    reply = ask(services, "In Karnataka my car windows have film pasted later. Can I be fined?", "f1")
    assert reply.answer.generator == "extractive"  # fell back to verifiable quotes
    assert "llm_draft_blocked" in reply.answer.validation.flags
    assert "4321" not in reply.text and "10000" not in reply.text


def test_llm_outage_falls_back(make_services, corpus) -> None:
    services = make_services(provider=FakeLLM(error=LLMUnavailable("down")))
    reply = ask(services, "In Karnataka my car windows have film pasted later. Can I be fined?", "o1")
    assert reply.outcome == "answer" and reply.answer.generator == "extractive"
    assert any(f.startswith("llm_unavailable") for f in reply.answer.validation.flags)


def test_monthly_budget_stops_model_calls(make_services, corpus) -> None:
    llm = _good_llm()
    services = make_services(provider=llm, llm_monthly_budget_usd=0.0005)
    ask(services, "In Karnataka my car windows have film pasted later. Can I be fined?", "b1")
    ask(services, "In Karnataka my car windows have film pasted later. Can I be fined?", "b2")
    assert len(llm.calls) == 1  # second question: budget exhausted -> extractive


def test_injected_passage_never_reaches_model(make_services, corpus) -> None:
    llm = _good_llm()
    ask(
        make_services(provider=llm), "In Karnataka is window film notice about film legal? it is a film", "i1"
    )
    assert llm.calls and all("ignore all previous instructions" not in c["user"].lower() for c in llm.calls)


def test_rate_limit(make_services, corpus) -> None:
    services = make_services()
    services.limiter.max_events = 2
    ask(services, "hello", "r1")
    ask(services, "hello", "r1")
    assert ask(services, "hello", "r1").outcome == "rate_limited"
