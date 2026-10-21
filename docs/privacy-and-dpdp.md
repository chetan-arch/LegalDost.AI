# Privacy design and India's data-protection framework

**This is an engineering summary, not legal advice. Every item marked ⚖️ needs review by
qualified Indian counsel before launch.** Having this document or a privacy notice does not make
the product compliant.

## 1. Framework and phased commencement

* **Digital Personal Data Protection Act, 2023** (Act No. 22 of 2023).
* **Digital Personal Data Protection Rules, 2025**, notified in November 2025 (reported as
  G.S.R. 846(E) dated 13 November 2025). Reported phasing:
  * on notification: rules on the Data Protection Board (rules 1, 2, 17–21);
  * after 12 months (≈ November 2026): consent-manager rule (rule 4);
  * after 18 months (≈ May 2027): most substantive obligations, including notice, security
    safeguards, breach intimation, retention/erasure, children's data and significant data
    fiduciaries (rules 3, 5–16, 22, 23).

  ⚖️ These dates come from law-firm commentary (e.g. AZB & Partners, S.S. Rana & Co.), not from
  the Gazette text. Confirm against the official notification. Sources:
  [AZB](https://www.azbpartners.com/bank/indias-digital-personal-data-protection-act-phased-rollout-and-key-compliance-milestones/),
  [S.S. Rana](https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/).

## 2. Obligations likely to apply, and what the code does today

| Area | Likely requirement (⚖️ confirm) | Current implementation | Gap |
|---|---|---|---|
| Notice | Clear notice of data, purpose, rights, grievance contact before or at consent | Short first-message notice (`strings.notice`) | Full notice text, link to policy, Kannada review, grievance officer details |
| Consent / legitimate use | Free, specific, informed consent for processing; withdrawal as easy as giving it | User-initiated chat only; `DELETE MY DATA` command | Explicit consent capture & record; withdrawal flow wording |
| Purpose & minimisation | Process only what's needed for the purpose | Phone number stored only as HMAC; no message text in logs; facts limited to the registry | Review whether `pending_question` / `last_answer` retention is necessary |
| Retention & erasure | Erase when purpose served / consent withdrawn | `CONVERSATION_RETENTION_HOURS` (default 72) + `legaldost purge-expired`; expired rows are also dropped on next contact | Schedule purge (cron); define retention for diagnostics and usage tables; backups |
| Security safeguards | Reasonable safeguards, incl. encryption, access control, logging | HMAC verification, admin token, upload limits, redacting log formatter | Encryption at rest, secret manager, DB roles, audit log, pen test |
| Breach intimation | Notify the Board and affected users | None | Incident-response runbook |
| Children | Verifiable parental consent for under-18s | None: the bot cannot verify age | ⚖️ Decide approach (age gate, scope restriction) |
| Rights | Access, correction, erasure, grievance redressal, nomination | Erasure via command only | Access/correction requests, grievance channel, response SLAs |
| Processors & transfers | Contracts with processors; cross-border transfer subject to government restrictions | Optional LLM (Anthropic) and Jev receive question text and evidence; Meta processes WhatsApp traffic | DPAs, transfer assessment, provider retention settings, notice disclosure |

No private conversation is used for model training. Any future use would need a separate,
explicit, reviewed consent process.

## 3. Other legal questions for counsel ⚖️

* Whether providing legal information through an automated service raises issues under the
  Advocates Act, 1961 or Bar Council of India rules, and how disclaimers must be worded.
* Status of IT Act, 2000 s. 43A and the SPDI Rules, 2011 during the DPDP transition.
* Whether any intermediary obligations under the IT Rules, 2021 apply.
* Liability posture for incorrect information; terms of use.
* Use and redistribution terms of each legal source (e.g. secondary hosts of judgments).
* Meta's WhatsApp Business and Commerce policies for a legal-information service.

## 4. Deletion mechanism (documented for users and operators)

* User: send `DELETE MY DATA` → the conversation row (facts, last answer, pseudonymous key) is
  deleted immediately. Diagnostic `answer_logs` rows contain no user identifier or message text.
* Operator: `legaldost purge-expired` deletes expired conversations and webhook ids older than
  7 days. Run it on a schedule.
