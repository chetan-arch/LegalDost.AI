"""Compare local (Ollama) models on real questions answered from the loaded corpus.

For each model and question it records latency, whether the model's draft survived validation
(or was blocked and replaced by quotes), how many statements were kept or dropped, and the full
reply, so a person can judge readability and faithfulness. Mechanical numbers cannot tell whether
a plain-language explanation is legally right; read the replies.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from legaldost.api.processing import process_text
from legaldost.api.services import build_services
from legaldost.config import get_settings
from legaldost.db.models import Conversation
from legaldost.db.session import get_sessionmaker
from legaldost.llm.ollama_provider import OllamaProvider

# Multi-turn scenarios whose answers exist in the corpus loaded by the two manifests.
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "tint-film",
        "turns": [
            "I have been stopped by traffic police in Karnataka because of my tinted windows. Can they fine me?",
            "It's a film I got applied after buying the car.",
        ],
    },
    {"id": "consumer-refund", "turns": ["Can a shop refuse to refund a defective product?", "Karnataka"]},
    {
        "id": "unfair-trade",
        "turns": ["What is an unfair trade practice and who can file a complaint about it?", "Karnataka"],
    },
    {
        "id": "fitness-cert",
        "turns": [
            "I'm in Karnataka. How often must the fitness certificate of a transport vehicle be renewed?"
        ],
    },
    {"id": "kannada-tint", "turns": ["ಬೆಂಗಳೂರಿನಲ್ಲಿ ನನ್ನ ಕಾರಿನ ಗಾಜಿಗೆ ಕಪ್ಪು ಫಿಲ್ಮ್ ಅಂಟಿಸಿದ್ದೇನೆ. ಪೊಲೀಸರು ದಂಡ ಹಾಕಬಹುದೇ?"]},
]


def run_model_comparison(models: list[str], out: Path) -> int:
    base = get_settings()
    rows: list[dict[str, Any]] = []
    transcript: list[str] = []
    for model in models:
        settings = base.model_copy(update={"llm_provider": "ollama", "ollama_model": model})
        services = build_services(settings, get_sessionmaker())
        services.provider = OllamaProvider(settings)
        services.limiter.max_events = 0
        for sc in SCENARIOS:
            session_id = f"cmp-{sc['id']}-{uuid.uuid4().hex[:6]}"
            reply = None
            started = time.monotonic()
            for turn in sc["turns"]:
                reply = process_text(services, "eval", session_id, turn)
            seconds = time.monotonic() - started
            assert reply is not None
            ans = reply.answer
            flags = list(ans.validation.flags) if ans else []
            rows.append(
                {
                    "model": model,
                    "scenario": sc["id"],
                    "outcome": reply.outcome,
                    "seconds": round(seconds, 1),
                    "generator": ans.generator if ans else None,
                    "kept": ans.validation.kept_claims if ans else 0,
                    "dropped": ans.validation.dropped_claims if ans else 0,
                    "blocked": any(f.startswith("llm_draft") for f in flags),
                    "llm_error": next((f for f in flags if f.startswith("llm_unavailable")), None),
                    "status": ans.evidence_status.value if ans and ans.kind == "answer" else None,
                }
            )
            transcript += [
                f"\n{'=' * 90}\nMODEL {model} | SCENARIO {sc['id']} | {seconds:.1f}s | flags {flags}",
                reply.text,
            ]
            print(
                f"{model:<22} {sc['id']:<16} {seconds:6.1f}s  generator={rows[-1]['generator']} "
                f"kept={rows[-1]['kept']} dropped={rows[-1]['dropped']} blocked={rows[-1]['blocked']}",
                flush=True,
            )
    session = get_sessionmaker()()
    session.execute(delete(Conversation).where(Conversation.channel == "eval"))
    session.commit()
    session.close()
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    out.with_suffix(".txt").write_text("\n".join(transcript), encoding="utf-8")
    print(f"wrote {out} and {out.with_suffix('.txt')}")
    return 0
