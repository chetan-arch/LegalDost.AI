# LegalDost.AI

**Know your rights. Understand the law. Take a safer next step.**

A WhatsApp-first Indian legal *information* assistant. A user describes a situation; the system
asks for missing material facts, retrieves registered legal sources, drafts an answer only from
those sources, mechanically validates every citation, and states how well the evidence supports
the answer. When it can't find adequate evidence, it says so.

Scope: **any everyday legal question in India**, central law plus Karnataka state law first.
The assistant recognises 13 legal areas (traffic, criminal, police procedure, constitutional
rights, consumer, tenancy, property, family, employment, cyber, government/RTI, banking, and a
catch-all for anything else). It answers in an area only when real sources for that area are
loaded; otherwise it says so. Coverage grows by loading documents, not by changing code.
English and Kannada.

> Legal information, not legal advice. Passing citation validation means a quote exists in a
> stored source at the cited location; it does not mean an interpretation is legally correct.

---

## Status (milestone 1, 2026-10-17)

| Area | State |
|---|---|
| Dev chat simulator (`/dev`, `/dev/chat`) and CLI (`legaldost ask`) | **Implemented, tested** |
| Pipeline: triage → routing → fact check/clarification → hybrid retrieval → generation → citation validation → evidence status → formatting | **Implemented, tested** (SQLite) |
| Extractive mode (no LLM: quotes registered passages, no interpretation) | **Implemented, tested**; this is the default |
| Anthropic LLM generation (`LLM_PROVIDER=anthropic`) | **Implemented, mocked in tests only**. Never called live (no key here) |
| WhatsApp Cloud API webhook + outbound adapter | **Implemented, tested with signed fixtures and a mocked Graph API**. Not tested against Meta (no credentials) |
| Jev decision engine adapter | **Implemented to TypeSafe's documented API, mocked in tests**. Not called live (no key) |
| Rules decision engine (default) | **Implemented, tested**, benchmarked on 37 labelled messages across all areas |
| General-law coverage: 13 areas, 19 topics, catch-all topic, corpus-driven area switching, high-risk escalation | **Implemented, tested** (SQLite; not yet re-run on PostgreSQL) |
| Ingestion CLI + admin API (register, fetch, upload, version, dedupe, reprocess, status, review, provenance, error log) | **Implemented, tested** |
| PostgreSQL + pgvector backend, Docker Compose | Implemented and verified locally on 2026-10-17 (`pgvector/pgvector:pg16`): migrations, full test suite, manifest ingest and legal eval all pass. The `app` container image was not built or run. |
| English | Implemented |
| Kannada | **Switched off for now** (`SUPPORTED_LANGUAGES=["en"]`): Kannada messages get a polite "English only for now" reply. The Kannada code and strings remain, and can be re-enabled with `SUPPORTED_LANGUAGES=["en","kn"]` (they need native-speaker review). |
| "What can you do?" questions | Recognised (whole-message patterns) and answered with coverage plus example questions |
| Everyday words → legal terms | `knowledge/legal_terms.yaml` maps e.g. "helmet" → "protective headgear", "minor" → "juvenile" (search hints only, unreviewed) |
| Images, PDFs and voice from users | Interface only (`channels/media.py`); users get a "can't read this yet" reply |
| Live Legal Mode, notice scanner, voice, action kit, change engine, official portal links | Future work (architecture leaves room; not built) |

### Legal corpus actually loaded

The repository contains **no legal text**. `knowledge/sources/traffic_initial.yaml` lists real
documents; `legaldost ingest manifest` downloads them on your machine. On 2026-10-17 from the
development machine:

| Source | Result |
|---|---|
| Central Motor Vehicles (Fifth Amendment) Rules, 2023, G.S.R. 663(E) (eGazette) | ingested |
| Kerala High Court, *George & Sons v. Union of India*, 2024:KER:68346 (copy hosted by verdictum.in) | ingested |
| PIB-hosted summary table of MV (Amendment) Act 2019 sections in force from 1 Sept 2019 | ingested |
| Motor Vehicles Act, 1988 (India Code) | **failed**: host timed out |
| *Avishek Goenka v. Union of India* (Supreme Court) | **failed**: host did not resolve |
| CMVR Seventh Amendment 2020, G.S.R. 457(E) (MoRTH) | **failed**: URL returns an HTML app shell |
| Consumer Protection Act, 2019 as published in the Gazette, 9 Aug 2019 (`core_laws.yaml`, 2026-10-20) | ingested (157 passages) |
| Motor Vehicles (Amendment) Act, 2019, No. 32 of 2019, Gazette 9 Aug 2019 (eGazette 210413) | ingested (155 passages): helmet, seat belt, drunk driving, speeding, mobile phone, triple riding, juvenile-driving penalties |
| Hindu Marriage Act 1955 (P&H High Court copy) | ingested: divorce, mutual consent, maintenance, permanent alimony |
| Hindu Adoptions and Maintenance Act 1956, No. 78 (AP High Court copy) | ingested: maintenance of wife, children, aged parents |
| Protection of Women from Domestic Violence Act 2005 (National Commission for Women copy) | ingested |
| Hindu Succession Act 1956, No. 30 (SC Legal Services Committee copy, **pre-2005 text, marked amended**) | ingested |
| Hindu Succession (Amendment) Act 2005, No. 39 (Govt of Tamil Nadu copy) | ingested: daughters as coparceners |
| Bharatiya Nyaya Sanhita 2023, No. 45 (Gazette text via PRS) | ingested: offences and punishments |
| Bharatiya Nagarik Suraksha Sanhita 2023, No. 46 (Gazette text via PRS) | ingested: police procedure, FIR, bail, maintenance (s.144) |

Areas live right now: **traffic, consumer, family, property/succession, criminal and police
procedure** (manifest `knowledge/sources/general_law_initial.yaml`). Not yet loaded: employment
(Code on Wages, POSH), tenancy (Karnataka Rent Act), cyber (IT Act), RTI, the Constitution,
Transfer of Property Act, Negotiable Instruments Act (cheque bounce), Bharatiya Sakshya Adhiniyam,
the IPC (for incidents before 1 July 2024) and *Vineeta Sharma* (SC, 2020). India Code and several
ministry sites were unreachable from the development machine; the templates are in `core_laws.yaml`.

Areas live right now: **traffic** and **consumer**. Every other area answers "no sources loaded
yet" (plus a lawyer/legal-aid note for high-risk areas) until its Acts are loaded from
`knowledge/sources/core_laws.yaml`. That template lists 22 core central and Karnataka laws
(BNS, BNSS, BSA, IPC, Constitution, Rent Act, Land Revenue Act, Hindu Marriage and Succession
Acts, DV Act, POSH Act, IT Act, RTI Act, NI Act, Code on Wages and more). India Code's PDF server
returned gateway timeouts from the development machine, so those need downloading by hand.

So today the assistant **cannot give a "sufficient" answer on tinted glass**. The current
Rule 100 text (official copy) and the Supreme Court judgment are missing, and no source has been
reviewed by an advocate. The flagship query is handled honestly instead: it asks whether the tint
is factory glass or added film, quotes the Kerala High Court passages, flags them as not binding
in Karnataka, and reports "partly supported" with the reasons.

---

## Quick start (no credentials needed)

Requires Python 3.12+.

```bash
python -m venv .venv
```

Windows: `.venv\Scripts\activate` · macOS/Linux: `source .venv/bin/activate`

```bash
pip install -e ".[dev]"
```

```bash
cp .env.example .env
```

```bash
legaldost db upgrade
```

```bash
legaldost ingest manifest knowledge/sources/traffic_initial.yaml
```

```bash
legaldost ingest manifest knowledge/sources/core_laws.yaml
```

```bash
uvicorn --factory legaldost.api.app:app_factory --port 8000
```

Open <http://localhost:8000/dev> and ask, for example:
*"I have been stopped by traffic police in Karnataka because of my tinted windows. My glass has
50% VLT. Can they fine me?"* Then reply *MORE* or *SOURCES*.

Or from the shell:

```bash
legaldost ask "In Karnataka, my car has a sun film pasted on the windows. Is that allowed?"
```

Health check: `GET /healthz` reports the LLM provider, decision engine and whether WhatsApp
outbound is configured.

---

## How an answer is produced

1. **Commands**: `MORE`, `SOURCES`, `HELP`, `KANNADA`/`ENGLISH`, `RESET`, `DELETE MY DATA`.
2. **Safety triage** (deterministic, `legaldost/safety.py`): imminent danger → emergency number
   first; bribery/evasion/evidence destruction → declined with lawful alternatives;
   arrest/custody/deadlines → escalation to a lawyer / free legal aid.
3. **Routing** (`DecisionEngine`): rules by default; Jev or an LLM optional.
4. **Facts** (`knowledge/topics.yaml` + `domain/facts.py`): per-topic required facts (e.g.
   state, factory glass vs. aftermarket film). Only facts the user stated are recorded, and at
   most two questions are asked per turn. Contradictory statements leave the fact unknown.
5. **Coverage check**: an area is offered only if it is `enabled` in `knowledge/topics.yaml` **and**
   at least one current source tagged with it is loaded (`retrieval/coverage.py`). Otherwise the
   bot says no verified sources are loaded. Questions that match no topic but look legal go to the
   **catch-all** (`general.legal`), which searches every loaded area with a stricter relevance gate
   (generic words like "law" or "person" don't count; a two-word phrase from the question must
   appear in the passage). High-risk areas (criminal, police, property, family, harassment, cheque
   bounce) always add a "please see a lawyer" note with free legal aid contacts.
6. **Hybrid retrieval** (`retrieval/search.py`): BM25 (SQLite) or `tsvector` (PostgreSQL) plus
   embeddings, metadata filters (jurisdiction, domain, current version, not superseded),
   exact-identifier boost ("rule 100"), reciprocal-rank fusion. A passage needs a lexical match
   to qualify; vector similarity alone is not evidence.
7. **Evidence packet**: passages labelled E1…En with source metadata, locator, URL and a
   "not binding in your state" note for other High Courts.
8. **Generation**: LLM structured output (`DraftAnswer`) citing evidence ids with verbatim
   quotes, or the extractive generator.
9. **Citation validation** (`pipeline/validator.py`): the evidence id exists, the passage is in
   the DB, current, and belongs to the source; the URL is the registered URL; the quote is in the
   passage; every number and section/rule number in a claim appears in the cited text (or was
   stated by the user). Failing claims are dropped. A summary that mentions provisions or figures
   absent from the evidence blocks the draft, and only verifiable quotes are shown.
10. **Evidence status** (`pipeline/status.py`): `sufficient`, `partially_supported`,
    `conflicting`, `no_reliable_evidence`, `human_review_recommended`. Deterministic caps apply.
    `sufficient` needs validated claims, an official primary source with verified legal status,
    advocate-reviewed sources, all required facts, and model interpretation. The model can lower
    the status but never raise it. No confidence percentages are shown.
11. **Formatting**: Quick Answer (default), Explain the Law (`MORE`), Show the Evidence
    (`SOURCES`), with source cards (title, locator, category, dates, legal status, review state,
    URL, excerpt).
12. **Diagnostics**: `answer_logs` stores outcome, status, counts, flags and latency. It never
    stores message text or user ids.

---

## Growing the knowledge base

**Court judgments in bulk (free, CC-BY-4.0).** Two open datasets on AWS Open Data, maintained by
Dattam Labs and sourced from the courts' and eCourts websites, are importable directly (no AWS
account needed):
[Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/) (1950 onwards) and
[Indian High Court Judgments](https://registry.opendata.aws/indian-high-court-judgments/) (25 High Courts;
Karnataka is court code `29_3`). Each judgment is registered as a `secondary` source with an
attribution note (they are convenient copies, not certified copies), tagged with legal areas from its
own text, and indexed. Imports are resumable.

```bash
legaldost import-judgments sc --years 2018-2025
legaldost import-judgments sc --years 2012 --title "goenka"          # pick specific cases by title
legaldost import-judgments hc --years 2024-2025 --limit-per-year 500  # Karnataka High Court
```

High Court imports skip procedural one-liners (withdrawn, non-prosecution, adjourned and so on) and
rows without a PDF. Each import holds the database write lock only briefly (the PDF is read and
embedded first), so the live server keeps answering while an import runs.

How judgments are used:

* Judgments never make an area "supported" on their own. An area such as employment stays
  unsupported until its Act or rules are loaded, so the bot does not answer an unpaid-salary question
  from whichever rulings happen to mention salary.
* The law comes first: up to two evidence slots are kept for Acts, rules and notifications whenever
  they match, and judgments fill the rest.
* Each case counts once: copies of the same judgment (different reporters, re-uploads) share at most
  two evidence slots.
* In the catch-all area, when the model's summary cannot be verified against the quotes, the bot
  says it has no reliable source instead of showing loosely related quotes.

**Semantic search on the GPU.** `EMBEDDING_BACKEND=sentence-transformers` with
`EMBEDDING_MODEL=intfloat/multilingual-e5-small` (`EMBEDDING_DIM=384`) runs on CUDA when
available. Install the CUDA build of PyTorch first, then the extra:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[local-embeddings]"
```

The model (about 470 MB) downloads on first use; re-embedding about 2,000 passages takes under two
minutes on a laptop RTX 4070. Similarity scores from this model sit in a narrow band (unrelated
text still scores about 0.81), so keep `SEMANTIC_MIN_SIMILARITY` near 0.86. It links
different words with the same meaning ("windshield"/"windscreen", "mesh"/"other material"). Passages
found by meaning alone must exceed `SEMANTIC_MIN_SIMILARITY`. After changing the model run
`legaldost reindex-embeddings`.

**Scaled indexes.** Keyword search uses an SQLite FTS5 table (Porter stemming, BM25) and vector
search uses an in-memory matrix cached under `data/index/`, so retrieval cost no longer grows with a
full scan of every passage. `legaldost index-rebuild` rebuilds the keyword index.

**Gap log.** Questions the bot could not answer are recorded as keywords only (no message text,
no user id, expire after `GAP_LOG_RETENTION_DAYS`, default 30). `legaldost gaps` shows which areas
and words come up most, i.e. what to load next.

## Managing legal sources

Sources go through `unverified` → `fetched_unreviewed` → `reviewer_verified`. Legal status
defaults to `unknown`; nothing is inferred from file names. History is never deleted: superseded
or unavailable sources stay for provenance and are excluded from retrieval.

```bash
legaldost ingest manifest knowledge/sources/traffic_initial.yaml   # register + fetch all
legaldost ingest manifest knowledge/sources/core_laws.yaml         # core Acts; disabled entries are skipped
legaldost ingest reprocess --all-current                           # re-extract after segmentation changes
legaldost ingest file in-indiacode-motor-vehicles-act-1988 ./mva1988.pdf   # upload a copy you downloaded
legaldost ingest fetch sc-2012-avishek-goenka-v-uoi                # retry one source
legaldost ingest reprocess <version_id>                            # re-extract a stored version
legaldost sources list
legaldost sources events                                           # ingestion log and errors
legaldost sources status <key> in_force --note "checked against Gazette on ..."
legaldost sources status <old_key> superseded --superseded-by <new_key>
legaldost sources review <key> --reviewer "Adv. Name"
legaldost provenance <passage_id>
legaldost search "visual transmission of light side windows"
```

Admin HTTP API (disabled unless `ADMIN_API_TOKEN` is set; send `X-Admin-Token`):
`GET/POST /admin/sources`, `POST /admin/sources/{key}/upload|fetch|status|review`,
`POST /admin/versions/{id}/reprocess`, `GET /admin/passages/{id}/provenance`,
`GET /admin/ingestion-events`, `GET /admin/usage`.

Ingestion safety: HTTPS-only domain allowlist (re-checked on each redirect), size limits, PDF or
UTF-8 text only (HTML app shells and scanned PDFs are rejected with a clear error), server-generated
file names, content-hash dedupe, OS trust store for TLS (verification is never disabled), and
passages with instruction-like text are flagged and never sent to a model.

To add a source, add an entry to a manifest with metadata taken **from the document itself**,
and leave unknown dates `null`.

---

## Configuration

All settings come from environment variables; see [.env.example](.env.example) (placeholders only).
Important ones: `DATABASE_URL`, `USER_ID_HASH_SECRET`, `LLM_PROVIDER`, `ANTHROPIC_API_KEY`,
`DECISION_ENGINE`, `JEV_API_KEY`, `WHATSAPP_*`, `ADMIN_API_TOKEN`,
`CONVERSATION_RETENTION_HOURS`, `LLM_MONTHLY_BUDGET_USD`, `LLM_MAX_CALLS_PER_QUESTION`.

### LLM (optional)

**Free, local option (recommended for personal use): Ollama.** Install [Ollama](https://ollama.com),
run `ollama pull qwen3:8b`, then set `LLM_PROVIDER=ollama` and `OLLAMA_MODEL=qwen3:8b`. Nothing
leaves the machine and there is no per-question cost. Measured on an RTX 4070 laptop GPU (8 GB):
qwen3:8b runs fully on the GPU at about 7–15 s per answer. qwen2.5-coder:14b spilled onto the CPU and
took 28–106 s, and misread a judgment. Replies start with a TL;DR, explain the law in plain words,
and are labelled as written automatically. Every point must carry a verbatim quote, and an
unsupported TL;DR is replaced by a verified point. Known limits: small models sometimes overstate a rule
or confuse a party's argument in a judgment with the court's decision. The validator cannot catch
those, so answers stay "partly supported" until sources are advocate-reviewed. Kannada drafts from
8B models often fail validation and fall back to quotes. Compare models with
`legaldost eval models --models qwen3:8b,<other>`.

`LLM_PROVIDER=anthropic` uses the official `anthropic` SDK (`messages.parse` with a Pydantic
schema), with timeouts, bounded retries, refusal handling, token/cost recording in
`usage_records`, a per-question call cap and a monthly budget. Complex questions use the "deep"
tier (`LLM_MODEL_DEEP`/`LLM_EFFORT_DEEP`); others use the "standard" tier. With
`LLM_REFUSAL_FALLBACK=true`, requests to models that support it use Anthropic's server-side
refusal fallback (`fallbacks: "default"`). Any provider error, refusal or budget stop falls back
to extractive mode. The provider sits behind `LLMProvider` (`legaldost/llm/base.py`), so another
vendor can be added without touching the pipeline. Prices in `PRICES_PER_MTOK` are copied from
Anthropic's model table (cached 2026-10-06); verify them before relying on cost figures.

### Embeddings

The default `HashingEmbedder` is deterministic and offline but **not truly semantic**. For
production set `EMBEDDING_BACKEND=sentence-transformers` with a multilingual model,
`pip install -e ".[local-embeddings]"`, set `EMBEDDING_DIM` to match, and run
`legaldost reindex-embeddings` (on PostgreSQL also recreate the vector column at the new size).
This adapter is untested here.

### WhatsApp

See [docs/whatsapp-setup.md](docs/whatsapp-setup.md).

### Jev

See [docs/jev-evaluation.md](docs/jev-evaluation.md).

---

## Evaluation

```bash
legaldost eval legal --out data/eval_report.json
```

```bash
legaldost eval routing --engines rules,jev,llm
```

* `eval/legal_eval.yaml`: 21 cases (missing facts, ambiguity, outdated references, incorrect
  assumptions, unsupported conclusions, prompt injection, unanswerable, unsupported domains,
  safety, Kannada, answer modes). Each case has a `review` block for advocates
  (`acceptable_conclusions`, `unacceptable_conclusions`, `expected_evidence`, status). Checks are
  mechanical: outcome, questions asked, allowed evidence status, expected/forbidden sources,
  citations resolve to stored passages, quotes match, text constraints.
* Current result (extractive mode, corpus above): 21/21 mechanical checks pass; **0 cases are
  advocate-reviewed**, so no legal-accuracy claim can be made.
* `eval/routing_eval.yaml`: 37 labelled routing messages for comparing decision engines. The
  rules engine scores 37/37, but its keywords were tuned on these same messages, so this says
  little about unseen questions; a held-out set is needed.

## Tests and checks

```bash
pytest
```

```bash
ruff check legaldost tests migrations
```

```bash
mypy legaldost
```

70 tests. By default they use a temporary SQLite database (set `TEST_DATABASE_URL` to run them
on PostgreSQL; see below), a **fictional** fixture corpus (clearly labelled
"FICTIONAL TEST FIXTURE"), a fake LLM and mocked HTTP. No paid API is called. Coverage includes
clarification and follow-up, abstention, unsupported domains, emergency and bribery handling,
modes, deletion, pseudonymisation, Kannada, LLM answer capping, fabricated-citation blocking, LLM
outage, budget stop, document prompt injection, rate limiting, ingestion (dedupe, versioning,
reprocess, bad files, scanned PDFs, review reset, path safety, fetch allowlist and redirects),
retrieval filters, validator rules, WhatsApp verification/signature/duplicates/media/unsigned
policy, admin auth and flow, Jev request shape and fallbacks, migrations, and redaction.

---

## PostgreSQL / Docker

```bash
docker compose up --build
```

The app container runs migrations, then serves on `127.0.0.1:8000`. Ingest inside it:

```bash
docker compose exec app legaldost ingest manifest knowledge/sources/traffic_initial.yaml
```

Or run only the database and use the CLI from your virtualenv (`pip install -e ".[postgres]"`):

```bash
docker compose up -d db
```

```bash
DATABASE_URL=postgresql+psycopg://legaldost:change-me-local-only@127.0.0.1:5432/legaldost legaldost db upgrade
```

Use `127.0.0.1`, not `localhost`: the container only listens on IPv4, and on Windows `localhost`
tries IPv6 first, which makes every connection hang for several seconds.

Run the tests against PostgreSQL. A throwaway `legaldost_pytest` database is created and dropped,
and the database named in the URL is not touched:

```bash
TEST_DATABASE_URL=postgresql+psycopg://legaldost:change-me-local-only@127.0.0.1:5432/legaldost pytest
```

**Verified on 2026-10-17** (Windows, Docker Desktop, `pgvector/pgvector:pg16`):

* `legaldost db upgrade` applies `0001_initial` unchanged: `passages.embedding` is `vector(256)`,
  `passages.tsv` is a generated `tsvector`, with a GIN index on `tsv` and an HNSW
  (`vector_cosine_ops`) index on `embedding`.
* All 61 tests pass on PostgreSQL, with each test's schema built by the Alembic migration. The
  retrieval tests exercise the `to_tsquery` OR query with `id = ANY(:ids)` and the
  `EmbeddingVector` round trip. Neither needed changes. The SQLite run still passes 61/61.
* `legaldost ingest manifest knowledge/sources/traffic_initial.yaml` matches the SQLite run:
  3 sources ingested (6 + 42 + 64 passages). The same 3 failed upstream (timeout, DNS, HTML shell).
* `legaldost eval legal`: 17/17 mechanical checks pass, the same as on SQLite.

Not verified: the `app` image (`docker compose up --build`) and its in-container migration and
ingest; `reindex-embeddings` with a different `EMBEDDING_DIM`; performance at corpus scale.

## Production checklist (not done yet)

* Managed PostgreSQL with least-privilege roles, encryption at rest, backups with retention limits.
* Secrets in a secret manager. Set `ENVIRONMENT=production` (disables `/dev` and `/docs`) and a
  real `USER_ID_HASH_SECRET` (startup refuses the default).
* TLS termination, request-size limits at the proxy, WAF/rate limiting shared across instances
  (the built-in limiter is per-process).
* Durable job queue for webhook processing; scheduled `legaldost purge-expired`.
* Admin API on a private network only; rotate `ADMIN_API_TOKEN`.
* Dependency pinning and update automation (`pip-compile`/Dependabot); container image scanning.
* Monitoring of ingestion errors, abstention rate, validator flags and LLM spend.
* DPDP/legal review: [docs/privacy-and-dpdp.md](docs/privacy-and-dpdp.md).

## Known limitations

* The corpus is small and unreviewed: six areas are loaded, several important Acts are still missing. Most
  questions end in "partly supported", "no sources loaded" or abstention. That is the intended behaviour until official sources are loaded and reviewed.
* Section/paragraph labels come from numbering heuristics. Page numbers are reliable, labels
  are best-effort (recorded in each version's `extraction_notes`). Bilingual Gazette PDFs fall
  back to page-level passages.
* Extractive quote selection is lexical and sometimes picks a less useful sentence. `SOURCES`
  shows the full excerpt.
* The validator's claim-support check is lexical. It catches invented numbers, provisions and
  quotes, not subtle misreadings.
* Kannada retrieval relies on topic keywords and English expansion terms; Kannada source
  documents are not yet loaded. Assumption notes for non-Karnataka states are English-only.
* No amendment/commencement graph yet: legal status is a manually curated field.
* Escalation contacts in `knowledge/official_contacts.yaml` are marked unreviewed.

## Repository layout

```
legaldost/            application package
  api/                FastAPI app, dev chat, WhatsApp webhook, admin API, rate limiting
  channels/           WhatsApp Cloud API adapter, media interfaces
  decision/           DecisionEngine: rules (default), Jev adapter, LLM router
  domain/             typed schemas, topic/fact registry, fact extraction
  eval/               evaluation dataset schema, legal eval runner, routing benchmark
  ingestion/          fetch, extraction, segmentation, versioned ingestion service, manifests
  llm/                provider interface, Anthropic provider, usage ledger/budget
  pipeline/           orchestrator, evidence packet, generators, validator, status, formatter
  retrieval/          embeddings, hybrid retriever
knowledge/            topic/fact registry, official contacts, source manifests (no legal text)
eval/                 legal and routing evaluation datasets
migrations/           Alembic migrations (SQLite + PostgreSQL/pgvector)
docs/                 implementation plan, WhatsApp setup, Jev evaluation, privacy/DPDP
tests/                pytest suite (fictional fixtures only)
```
