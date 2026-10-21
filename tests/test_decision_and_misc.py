import json
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from legaldost.config import PROJECT_ROOT
from legaldost.decision.base import EvidenceCandidate
from legaldost.decision.jev import JevClient, JevDecisionEngine
from legaldost.decision.rules import RulesDecisionEngine
from legaldost.domain.registry import load_registry
from legaldost.eval.dataset import load_dataset
from legaldost.eval.routing import benchmark, load_routing
from legaldost.logging_setup import redact
from legaldost.pipeline.formatter import split_for_whatsapp

REG = load_registry()


def test_rules_routing() -> None:
    engine = RulesDecisionEngine(REG)
    assert engine.route("Can police fine me for tinted windows?", "en").topic == "traffic.tinted_glass"
    assert engine.route("hello", "en").intent == "greeting"
    assert engine.route("my landlord kept my deposit", "en").domain == "tenancy"
    assert engine.route("officer cited the wrong section on my challan", "en").needs_deep_review


def _jev(handler) -> tuple[JevDecisionEngine, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = JevClient(
        "jev-key",
        "https://api.typesafe.ai",
        "jev-latest",
        2.0,
        transport=httpx.MockTransport(wrapped),
        max_retries=1,
    )
    return JevDecisionEngine(REG, client, 0.6), seen


def test_jev_request_shape_and_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 300, "output_tokens": 20},
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "legal_question",
                        "confidence": 0.95,
                        "probabilities": {},
                    },
                    "topic": {
                        "type": "choice",
                        "choice": "traffic.challan",
                        "confidence": 0.9,
                        "probabilities": {},
                    },
                    "complex": {"type": "noul", "noul": 0.8},
                },
            },
        )

    engine, seen = _jev(handler)
    decision = engine.route("Can I challenge this challan?", "en")
    req = seen[0]
    assert req.url.path == "/v1/systemone" and req.headers["authorization"] == "Bearer jev-key"
    body = json.loads(req.content)
    assert body["model"] == "jev-latest"
    assert body["questions"]["topic"]["type"] == "choice"
    assert body["questions"]["complex"]["type"] == "noul"
    assert "traffic.tinted_glass" in body["questions"]["topic"]["criteria"]
    assert (
        decision.topic == "traffic.challan" and decision.complexity == "complex" and decision.engine == "jev"
    )


def test_jev_failures_fall_back_to_rules() -> None:
    engine, _ = _jev(lambda r: httpx.Response(500))
    d = engine.route("Can police fine me for tinted windows?", "en")
    assert d.fallback_used and d.topic == "traffic.tinted_glass" and d.engine == "jev->rules"

    def low_conf(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {"choice": "legal_question", "confidence": 0.9},
                    "topic": {"choice": "made.up.topic", "confidence": 0.99},
                    "complex": {"noul": 0.1},
                }
            },
        )

    engine, _ = _jev(low_conf)
    d = engine.route("Can police fine me for tinted windows?", "en")
    assert d.topic == "traffic.tinted_glass" and d.fallback_used  # out-of-registry value rejected


def test_jev_evidence_priority_only_reorders_given_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"answers": {"E1": {"score": 0.2}, "E2": {"score": 3.0}, "E9": {"score": 9.0}}}
        )

    engine, _ = _jev(handler)
    cands = [EvidenceCandidate(evidence_id=e, title="t", locator="l", text="x") for e in ("E1", "E2")]
    assert engine.prioritise_evidence("q", cands) == ["E2", "E1"]


def test_routing_benchmark_regression() -> None:
    cases = load_routing(PROJECT_ROOT / "eval" / "routing_eval.yaml")
    result = benchmark(RulesDecisionEngine(REG), cases)
    assert result["topic_accuracy"] >= 0.9 and result["errors"] == 0


def test_eval_dataset_parses() -> None:
    ds = load_dataset(PROJECT_ROOT / "eval" / "legal_eval.yaml")
    categories = {c.category for c in ds.cases}
    assert {"missing_facts", "language", "safety", "unsupported_domain", "outdated_reference"} <= categories


def test_alembic_migration_on_sqlite(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"legal_sources", "document_versions", "passages", "conversations", "processed_events"} <= tables


def test_access_log_query_strings_are_removed() -> None:
    import logging

    from legaldost.logging_setup import AccessLogQueryFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:0", "GET", "/webhooks/whatsapp?hub.verify_token=SECRET&hub.challenge=1", "1.1", 200),
        None,
    )
    AccessLogQueryFilter().filter(record)
    assert "SECRET" not in record.getMessage() and "/webhooks/whatsapp" in record.getMessage()


def test_number_words_and_legal_terms() -> None:
    from legaldost.domain.registry import legal_term_hints, load_legal_terms
    from legaldost.textutil import numbers_in

    assert {"1000", "3"} <= numbers_in("a fine of one thousand rupees and three months")
    assert "200000" in numbers_in("two lakh rupees") and "1000" in numbers_in("Rs. 1,000")
    hints = legal_term_hints("What is the fine for not wearing a helmet?", load_legal_terms())
    assert "protective headgear" in hints
    assert legal_term_hints("helmeted lizard", load_legal_terms()) == []  # whole words only


def test_redaction() -> None:
    assert "[PHONE]" in redact("user 9876543210 wrote")
    assert "abc123" not in redact("Authorization: Bearer abc123")


def test_whatsapp_split() -> None:
    parts = split_for_whatsapp("a" * 5000 + "\n\n" + "b" * 10, limit=4096)
    assert all(len(p) <= 4096 for p in parts) and "".join(parts).count("b") == 10
