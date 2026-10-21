"""Run the legal evaluation set through the real pipeline against the loaded corpus.

Mechanical metrics only (behaviour, citations, quotes, expected sources, text checks). Legal
correctness requires the advocate ``review`` annotations; no accuracy claim should be made from
these numbers alone.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from legaldost.api.processing import process_text
from legaldost.api.services import Services, build_services
from legaldost.config import get_settings
from legaldost.db.models import Conversation, Passage
from legaldost.db.session import get_sessionmaker
from legaldost.eval.dataset import EvalCase, TurnExpectation, load_dataset
from legaldost.pipeline.orchestrator import Reply
from legaldost.pipeline.validator import quote_in_text


def check_turn(services: Services, reply: Reply, exp: TurnExpectation) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    answer = reply.answer
    text = reply.text.lower()
    if exp.outcome:
        checks["outcome"] = reply.outcome in exp.outcome
    if exp.asks_for:
        checks["asks_for"] = bool(answer) and set(exp.asks_for) <= set(answer.missing_facts if answer else [])
    cards = answer.supporting_sources if answer else []
    if exp.allowed_status:
        checks["status_allowed"] = bool(answer) and answer.evidence_status.value in exp.allowed_status  # type: ignore[union-attr]
    cited = {c.source_key for c in cards}
    if exp.expected_sources:
        checks["expected_sources"] = set(exp.expected_sources) <= cited
    if exp.forbidden_sources:
        checks["no_forbidden_sources"] = not (set(exp.forbidden_sources) & cited)
    if exp.min_citations:
        checks["min_citations"] = len(cards) >= exp.min_citations
    if exp.binding_note_required:
        checks["binding_note"] = any(c.binding_note for c in cards)
    for s in exp.must_contain:
        checks[f"contains:{s}"] = s.lower() in text
    for s in exp.must_not_contain:
        checks[f"not_contains:{s}"] = s.lower() not in text
    # Always: every displayed citation resolves and its excerpt is in the stored passage.
    session = services.sessionmaker()
    try:
        resolves = quotes = True
        for c in cards:
            p = session.get(Passage, c.passage_id)
            if p is None or p.source.source_url != c.url:
                resolves = False
            elif not quote_in_text(c.excerpt, p.text):  # same word-exact rule as the validator
                quotes = False
        checks["citations_resolve"] = resolves
        checks["quotes_match"] = quotes
    finally:
        session.close()
    return {
        "outcome": reply.outcome,
        "status": answer.evidence_status.value if answer else None,
        "cited": sorted(cited),
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_case(services: Services, case: EvalCase) -> dict[str, Any]:
    session_id = f"eval-{case.id}-{uuid.uuid4().hex[:6]}"
    turns = []
    for turn in case.turns:
        reply = process_text(services, "eval", session_id, turn.user)
        turns.append(check_turn(services, reply, turn.expect))
    return {
        "id": case.id,
        "category": case.category,
        "language": case.language,
        "review_status": case.review.status,
        "passed": all(t["passed"] for t in turns),
        "turns": turns,
    }


def run_legal_eval(dataset_path: Path, out: Path | None = None) -> int:
    dataset = load_dataset(dataset_path)
    settings = get_settings()
    services = build_services(settings, get_sessionmaker())
    services.limiter.max_events = 0  # no rate limiting during evaluation
    results = [run_case(services, c) for c in dataset.cases]
    session = services.sessionmaker()
    session.execute(delete(Conversation).where(Conversation.channel == "eval"))
    session.commit()
    session.close()

    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["passed"])
    summary = {
        "dataset": dataset.name,
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "reviewed_cases": sum(1 for c in dataset.cases if c.review.status == "approved"),
        "llm_provider": settings.llm_provider,
        "by_category": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_cat.items())},
        "note": "Mechanical behaviour/citation checks only; legal correctness requires advocate review.",
    }
    report = {"summary": summary, "results": results}
    if out:
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for r in results:
        if not r["passed"]:
            failed = [k for t in r["turns"] for k, v in t["checks"].items() if not v]
            print(f"FAIL {r['id']}: {', '.join(failed)}")
    return 0 if summary["passed"] == summary["cases"] else 1
