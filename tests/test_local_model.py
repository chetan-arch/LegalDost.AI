"""Ollama provider, quote-anchored validation and the TL;DR-first reply layout."""

import json

import httpx
import pytest

from legaldost.config import Settings
from legaldost.domain.schemas import (
    AnswerMode,
    DraftAnswer,
    DraftClaim,
    EvidenceStatus,
    LegalAnswer,
    ValidatedClaim,
)
from legaldost.llm.base import LLMBadOutput, LLMError, LLMUnavailable
from legaldost.llm.ollama_provider import OllamaProvider
from legaldost.pipeline.evidence import build_packet
from legaldost.pipeline.formatter import render
from legaldost.pipeline.validator import CitationValidator
from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters


def _provider(handler) -> tuple[OllamaProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    settings = Settings(_env_file=None, llm_provider="ollama", ollama_model="qwen3:8b")
    return OllamaProvider(settings, transport=httpx.MockTransport(wrapped)), seen


GOOD = DraftAnswer(summary="In short: no.", legal_position="p", proposed_status=EvidenceStatus.PARTIAL)


def test_ollama_request_shape_and_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": GOOD.model_dump_json()},
                "prompt_eval_count": 900,
                "eval_count": 120,
            },
        )

    provider, seen = _provider(handler)
    result = provider.structured(
        purpose="answer", tier="standard", system="sys", user="q", schema=DraftAnswer
    )
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/chat"
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["think"] is False
    assert body["format"]["title"] == "DraftAnswer"  # JSON schema sent for structured output
    assert body["options"]["temperature"] == 0 and body["options"]["num_ctx"] == 8192
    assert body["messages"][0]["role"] == "system"
    assert result.output.summary == "In short: no." and result.cost_usd == 0.0 and result.input_tokens == 900


@pytest.mark.parametrize(
    "response,error",
    [
        (httpx.Response(404, json={"error": "model not found"}), LLMError),
        (httpx.Response(500, json={}), LLMUnavailable),
        (httpx.Response(200, json={"done_reason": "length", "message": {"content": "{"}}), LLMBadOutput),
        (httpx.Response(200, json={"done_reason": "stop", "message": {"content": "not json"}}), LLMBadOutput),
    ],
)
def test_ollama_errors_map_to_fallback_errors(response, error) -> None:
    provider, _ = _provider(lambda r: response)
    with pytest.raises(error):
        provider.structured(purpose="answer", tier="standard", system="s", user="u", schema=DraftAnswer)


def test_ollama_unreachable_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider, _ = _provider(handler)
    with pytest.raises(LLMUnavailable):
        provider.structured(purpose="answer", tier="standard", system="s", user="u", schema=DraftAnswer)


def test_model_claims_without_quotes_are_dropped(session, embedder, corpus) -> None:
    results = HybridRetriever(session, embedder).search(
        QuerySpec("film pasted on side windows visual transmission"), RetrievalFilters(domains=["traffic"])
    )
    packet = build_packet(session, "film", results, "IN-KA", 1800)
    item = next(i for i in packet.items if "No film shall be pasted" in i.text)
    draft = DraftAnswer(
        summary="s",
        legal_position="p",
        claims=[
            DraftClaim(
                text="Film cannot be pasted on safety glass after manufacture.",
                evidence_ids=[item.evidence_id],
            ),
            DraftClaim(
                text="Film cannot be pasted on safety glass after manufacture.",
                evidence_ids=[item.evidence_id],
                quote="No film shall be pasted on the safety glass after manufacture",
            ),
        ],
    )
    claims, _, report = CitationValidator(session).validate(draft, packet, {}, "film", require_quotes=True)
    assert len(claims) == 1 and claims[0].quote and "missing_quote" in report.flags


def test_quick_reply_puts_tldr_first_and_labels_ai_summary() -> None:
    answer = LegalAnswer(
        summary="Film pasted after manufacture is not allowed under these rules.",
        claims=[
            ValidatedClaim(
                text="No film may be pasted on safety glass.",
                claim_type="law_text",
                evidence_ids=["E1"],
                quote="No film shall be pasted",
                support="quote_verified",
            )
        ],
        application_to_user_facts="If your film was added later, this rule may apply.",
        safe_next_steps=["Ask for a written challan."],
        evidence_status=EvidenceStatus.PARTIAL,
        generator="llm",
    )
    text = render(answer, AnswerMode.QUICK)
    assert text.startswith("📌 *In short:* Film pasted after manufacture")
    assert (
        "No film may be pasted" in text and '"No film shall be pasted"' not in text
    )  # quotes live in SOURCES
    assert "written automatically" in text
    assert text.index("In short") < text.index("What the law says") < text.index("Evidence")


def test_unsupported_tldr_is_replaced_by_a_verified_point(make_services, corpus) -> None:
    from legaldost.api.processing import process_text
    from tests.conftest import FakeLLM
    from tests.test_pipeline import evidence_ids

    def respond(prompt: str) -> DraftAnswer:
        eid = next(k for k, v in evidence_ids(prompt).items() if "No film shall be pasted" in v)
        return DraftAnswer(
            summary="Everyone is always entitled to compensation from the government in every situation.",
            legal_position="p",
            claims=[
                DraftClaim(
                    text="Film must not be pasted on safety glass after manufacture.",
                    evidence_ids=[eid],
                    quote="No film shall be pasted on the safety glass",
                )
            ],
            safe_next_steps=["Keep your documents."],
        )

    services = make_services(provider=FakeLLM(respond))
    reply = process_text(
        services, "dev", "t1", "In Karnataka my car windows have film pasted later. Can I be fined?"
    )
    assert "summary_unsupported" in reply.answer.validation.flags
    assert "compensation" not in reply.text
    assert "📌 *In short:* Film must not be pasted" in reply.text
