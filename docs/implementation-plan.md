# LegalDost.AI — Implementation Plan

Status: initial plan, written 2026-10-17 after inspecting the repository.

## 0. What was inspected

| Item | Finding |
|---|---|
| Repository | `C:\LegalDost.AI` was **empty** — no code, no git repository, no README. Nothing to preserve or migrate. |
| Runtime | Python 3.13.5 (also 3.11), Node 22, pip. No `uv`. |
| Docker | Docker CLI 29.7 installed, **daemon not running** during development. PostgreSQL is therefore not available locally right now. |
| PostgreSQL / psql | Not installed on the host. |
| Network to legal sources | `egazette.gov.in`, `static.pib.gov.in`, `verdictum.in` reachable. `indiacode.nic.in` **times out**; `main.sci.gov.in` does not resolve; `morth.gov.in` file URLs return an HTML app shell instead of PDFs. |
| Credentials | No WhatsApp, Anthropic or Jev credentials available. |

Consequences:

* The code supports PostgreSQL + pgvector (Docker Compose provided) **and** SQLite, so the whole pipeline can run and be tested without Docker. SQLite uses a portable BM25 + in-Python cosine backend; PostgreSQL uses `tsvector` full-text search + pgvector.
* The legal corpus is **not committed**. A source manifest (`knowledge/sources/*.yaml`) lists official/hosted URLs; the ingestion CLI downloads, hashes, extracts and indexes them on the operator's machine. Sources that cannot be fetched are recorded as ingestion errors, not faked.

## 1. Architecture (modular monolith)

```
WhatsApp Cloud API ──► /webhooks/whatsapp ─┐
Dev simulator  ──────► /dev/chat ──────────┤
                                           ▼
                                  ConversationService  (state, facts, mode, retention)
                                           │
                                           ▼
            ┌─────────────────── AnswerPipeline (orchestrator) ───────────────────┐
            │ 1 safety triage (deterministic: emergency / prohibited / liberty)   │
            │ 2 DecisionEngine  (rules default │ Jev adapter │ LLM router)          │
            │ 3 fact extraction + missing-fact check (topic registry)             │
            │ 4 clarification question (≤2 facts per turn)                        │
            │ 5 HybridRetriever  (FTS/BM25 + vectors + metadata filters + RRF)     │
            │ 6 EvidencePacket   (identified passages E1..En, metadata)           │
            │ 7 Generator        (LLM structured output │ extractive, no-LLM)      │
            │ 8 CitationValidator (ids, quotes, URLs, numbers, section refs)      │
            │ 9 EvidenceStatus + escalation (deterministic caps)                   │
            │10 Formatter (Quick / Explain / Evidence; en / kn)                   │
            └─────────────────────────────────────────────────────────────────────┘
                                           │
           LLMProvider (Anthropic │ none)  │  Embedder (hashing │ sentence-transformers)
                                           ▼
                     PostgreSQL+pgvector  /  SQLite (dev & tests)
```

Package layout (`legaldost/`):

| Module | Responsibility |
|---|---|
| `config.py` | Typed settings from environment (`pydantic-settings`). |
| `db/` | SQLAlchemy models, engine/session, dialect-aware vector type. |
| `domain/` | Pydantic schemas (answers, evidence, statuses) and the topic / fact registry. |
| `safety/` | Deterministic triage: emergencies, prohibited assistance, liberty/escalation triggers. |
| `decision/` | `DecisionEngine` protocol; rules engine, Jev adapter, LLM router. |
| `retrieval/` | Embedders, BM25, hybrid retriever, fusion. |
| `llm/` | Provider protocol, Anthropic provider, usage/budget accounting. |
| `pipeline/` | Evidence packet, generators, validator, status logic, formatter, orchestrator, conversation state. |
| `ingestion/` | Safe fetch, PDF/text extraction with page locators, segmentation, versioning, dedupe, status changes. |
| `channels/` | WhatsApp signature, webhook parsing, outbound client; media interfaces. |
| `api/` | FastAPI app, dev chat, WhatsApp webhook, admin routes, rate limiting. |
| `eval/` | Legal evaluation runner and routing benchmark. |
| `cli.py` | `legaldost` command: db, sources, ingest, eval, purge. |

## 2. Database schema

* `legal_sources` — one row per authoritative document identity: `source_key` (unique slug), official title, issuing authority/court, `document_type` (statute, rules, notification, judgment, official_summary, secondary_commentary), `source_category` (primary_official / official_secondary / secondary), jurisdiction (`IN`, `IN-KA`, `IN-KL` …), court level, legal domain, identifiers (JSON: act number, GSR number, case number, neutral citation), registered source URL, host note, languages, **separate** `publication_date`, `commencement_date`, `judgment_date`, `legal_status` (default `unknown`), `verification_status` (`unverified` → `fetched_unreviewed` → `reviewer_verified`), licensing note, supersession link.
* `document_versions` — every fetched/uploaded file: content SHA-256 (unique per source → duplicate ingestion is a no-op), retrieved timestamp, fetched URL, stored file name (server-generated), MIME, size, extraction status/error, page count, `is_current`.
* `passages` — citation units: version, ordinal, `page_start/page_end`, section/paragraph label, locator string, text, text hash, language, embedding, flags (e.g. `suspected_instructions`). PostgreSQL adds a generated `tsvector` column + GIN index and a pgvector column.
* `ingestion_events` — append-only log of ingestion attempts, errors, status changes.
* `conversations` — keyed by an HMAC of the channel user id (raw phone numbers are never stored), language, mode, established facts (JSON), active topic, last validated answer (for “more detail” / “show evidence”), `expires_at` for retention.
* `processed_events` — WhatsApp message ids already handled (duplicate/retry protection).
* `usage_records` — provider, model, purpose, tokens, cost estimate, latency, success (budget enforcement).
* `answer_logs` — privacy-preserving diagnostics: intent, domain, evidence status, counts, validator flags, latency. **No message text.**

## 3. Retrieval and verification strategy

1. **Query building**: user text + established facts + topic expansion terms from `knowledge/topics.yaml` (e.g. tint → “visual transmission of light”, “safety glass”, “safety glazing”). Kannada queries are mapped through a reviewed glossary or (if an LLM is configured) normalised to English for retrieval only.
2. **Metadata filters**: jurisdiction (`IN` + the user’s state; other states’ material kept but labelled persuasive), legal domain, document status (superseded/unavailable excluded by default), current version only.
3. **Lexical**: PostgreSQL `websearch_to_tsquery` + `ts_rank_cd`; SQLite BM25. Exact identifiers (“rule 100”, “section 190”) get a deterministic boost.
4. **Vector**: cosine similarity on embeddings (pgvector `<=>` on PostgreSQL).
5. **Fusion**: reciprocal-rank fusion; a passage needs **some lexical match** to be eligible as evidence (vector-only hits are too weak for legal claims with the default embedder).
6. **Evidence packet**: top-N passages, each with stable id `E1..En`, source metadata, locator and URL.
7. **Generation**: the LLM receives only the packet and returns a typed `DraftAnswer` whose claims reference evidence ids and verbatim quotes. Without an LLM, an extractive generator quotes the most relevant sentences and **does not interpret**.
8. **Validation** (`pipeline/validator.py`): evidence id exists in packet and DB; passage belongs to cited source; URL equals registered URL; quote is a normalised substring of the stored passage; every number, section and rule reference in a claim appears in the cited passage; summary/position text may not mention section/rule numbers absent from the evidence. Failing claims are removed and flagged.
9. **Status** (`pipeline/status.py`): deterministic caps — the model may lower but never raise the status. `sufficient` requires validated claims, at least one primary official source, no missing required facts, and known legal status for the primary source. Otherwise `partially_supported`, `conflicting`, `no_reliable_evidence` or `human_review_recommended`.

Mechanical validation ≠ legal review. The README and every answer card say so.

## 4. External integrations

| Integration | Approach | State at end of milestone 1 |
|---|---|---|
| WhatsApp Cloud API | Official webhook (`hub.*` verification, `X-Hub-Signature-256` HMAC-SHA256 over raw body), Graph API `/{phone-number-id}/messages` text sends. | Implemented, tested with signed fixtures and mocked HTTP. **Not tested against Meta** (no credentials). |
| Anthropic (LLM) | `anthropic` SDK, `messages.parse` structured output, timeouts, bounded retries, usage → cost, refusal handling. | Implemented, unit-tested with a fake provider. **Not called live** (no key). |
| Jev (TypeSafe) | Adapter for the documented `POST https://api.typesafe.ai/v1/systemone` (`state`, `model`, `questions` with `choice`/`noul`). | Implemented behind `DECISION_ENGINE=jev`, tested with mocked HTTP. **Not called live** (no key). Rules engine is the default. |
| Embeddings | `HashingEmbedder` (deterministic, no network) by default; optional `sentence-transformers`. | Hashing embedder tested; sentence-transformers adapter untested (optional extra). |

## 5. Security and privacy risks

| Risk | Mitigation |
|---|---|
| Forged webhooks | HMAC-SHA256 signature check with constant-time compare; unsigned requests rejected unless explicitly allowed in development. |
| Duplicate / retried events | `processed_events` unique key on message id. |
| Phone numbers in DB/logs | Stored only as HMAC(user id); logs contain no message text; redaction filter for tokens/phone-like strings. |
| Admin abuse | Admin API disabled unless `ADMIN_API_TOKEN` set; constant-time token compare; CLI requires shell access. |
| Unsafe uploads / fetches | Size limits, MIME + magic-byte checks, server-generated file names, HTTPS-only domain allowlist for fetches. |
| Prompt injection via documents | Evidence is passed as quoted data; passages with instruction-like text are flagged; citations can only reference packet ids; validator re-checks everything. |
| Over-retention | Conversation TTL (`CONVERSATION_RETENTION_HOURS`), `purge-expired` command, user command `DELETE MY DATA`. |
| Cost runaway | Per-question call cap, monthly budget check from `usage_records`, per-user rate limit. |
| Legal harm | Abstention when evidence is missing, emergency short-circuit, refusal of evasion/bribery help, escalation for liberty matters. |

## 6. Milestones

1. **M1 – vertical slice (this milestone)**: schema + migrations, ingestion CLI, hybrid retrieval, pipeline, validator, dev chat, WhatsApp adapter, Jev adapter, evaluation format, tests, docs.
2. **M2 – corpus and review**: operator ingests official CMVR (consolidated), MV Act 1988 (India Code), Karnataka MV Rules, relevant SC judgments; advocate review sets `reviewer_verified` and legal status; expand eval set with advocate annotations.
3. **M3 – production hardening**: PostgreSQL deployment, managed secrets, Redis-backed rate limiting/queue, monitoring, DPDP review by counsel, Meta business verification and live number.
4. **M4 – differentiators**: challan/notice scanner (OCR with visible uncertainty), Kannada voice, Live Legal Mode, Legal Action Kit, change tracking between versions.

## 7. Acceptance criteria for M1

* `legaldost db init` + `uvicorn` start the app locally with documented commands.
* A question can be asked at `/dev/chat` with no WhatsApp credentials.
* Real ingested passages (from the manifest) are retrieved and shown with registered URLs.
* Every displayed citation maps to a `passages` row; fabricated ids/quotes are removed by the validator (tested).
* With no adequate evidence the assistant says it cannot verify (tested).
* Missing material facts trigger a targeted question, and follow-up answers fill them (tested).
* `pytest`, `ruff`, `mypy` pass.
* `.env.example` contains placeholders only.

## 8. Decisions requiring later confirmation

* Hosting region / provider and whether PostgreSQL is managed.
* Which embedding model to use in production (Kannada support required).
* Production LLM tiering and monthly budget.
* Whether secondary hosts (e.g. verdictum.in for High Court judgments) are acceptable, or only court websites.
* Retention period for conversations (default 72 h) — counsel to confirm against DPDP obligations.
* Whether Jev is adopted after benchmarking with real credentials.
* Exact wording of the Kannada strings (needs native-speaker and legal review).
