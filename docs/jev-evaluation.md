# Jev (TypeSafe) as an optional decision layer

## What was verified (2026-10-17)

From TypeSafe's own documentation (<https://docs.typesafe.ai>, API reference at
<https://docs.typesafe.ai/api.md>):

* Jev is a "System One" model that returns **typed decisions** (choice, score, yes/no "noul",
  box) with probabilities, not free text.
* HTTP API: `POST https://api.typesafe.ai/v1/systemone`, header `Authorization: Bearer <API_KEY>`,
  body `{"state": ..., "model": "jev-latest", "questions": {id: {...}}}`.
* Question types used here: `choice` (`instructions`, `criteria` map, ≤255 options) and `noul`
  (`instructions`). Answers come back under the same ids: choice → `choice`, `probabilities`,
  `confidence`; noul → `noul` (0–1). `usage.input_tokens/output_tokens` is returned.
* Errors: 400, 401, 413, 415, 422, 429, 529 (retry 429/529 with backoff).
* Discrepancy: the Choice page example uses `selectedModels: ["jev-latest"]`; the API reference
  uses `model`. The adapter follows the API reference. Confirm with a live call.

**Not verified:** pricing (third-party listings disagree), rate limits, data retention / data
processing terms, availability from India, and real latency. Vendor-reported latency
(~70–500 ms) is not a benchmark.

## How it is integrated

* `legaldost/decision/base.py` – `DecisionEngine` protocol: `route()` (intent, topic, domain,
  complexity, deep-review flag) and `prioritise_evidence()` (reorder evidence ids only).
* `legaldost/decision/rules.py` – deterministic default and the fallback.
* `legaldost/decision/jev.py` – Jev adapter. Any transport error, non-200, missing answer,
  confidence below `JEV_MIN_CONFIDENCE` or a topic that is not in `knowledge/topics.yaml` falls
  back to the rules result for that field. The adapter can only reorder evidence ids it was given.
* `legaldost/decision/llm_router.py` – an LLM router for comparison.

Hard limits that Jev (or any router) cannot change: safety triage, required-fact checks,
retrieval eligibility, citation validation and evidence-status caps are deterministic code.

## Enabling it

```bash
DECISION_ENGINE=jev
JEV_API_KEY=<key from TypeSafe>
# optional: JEV_BASE_URL, JEV_MODEL=jev-latest, JEV_TIMEOUT_SECONDS=5, JEV_MIN_CONFIDENCE=0.6
```

Privacy note: with Jev enabled, the user's message text is sent to TypeSafe. That makes TypeSafe
a data processor; a data-processing agreement and a privacy-notice update are needed first.

## Benchmark

```bash
legaldost eval routing --engines rules,jev,llm --out data/routing_report.json
```

Measures topic/intent accuracy on `eval/routing_eval.yaml`, p50/p95 latency measured from this
process, fallback and error counts, and token usage. Engines without credentials are reported as
skipped, never simulated.

Results so far (25 labelled messages, local machine, 2026-10-17):

| Engine | Topic acc. | Intent acc. | p50 latency | Errors | Cost |
|---|---|---|---|---|---|
| rules | 0.96 | 0.96 | ~0.2 ms | 0 | none |
| jev | not run: no API key | | | | |
| llm | not run: no API key | | | | |

25 cases is far too few to choose a router; the set must grow (especially Kannada and
code-mixed messages) before comparing. The rules engine's accuracy is partly a product of having
been written against these same examples.
