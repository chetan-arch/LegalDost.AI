"""The answer pipeline: one inbound message in, one reply out.

Order of operations (each step is a separately testable module):
commands -> language -> safety triage -> routing -> facts / clarification -> retrieval ->
evidence packet -> generation -> citation validation -> status & escalation -> formatting -> log.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from legaldost.config import Settings
from legaldost.db.models import AnswerGap, AnswerLog, Conversation, LegalSource
from legaldost.decision.base import DecisionEngine, EvidenceCandidate, RoutingDecision
from legaldost.domain.facts import JURISDICTION_NAMES, extract_facts
from legaldost.domain.registry import (
    GENERAL_DOMAIN,
    GENERAL_TOPIC,
    Registry,
    TopicDef,
    legal_term_hints,
    load_contacts,
    load_legal_terms,
)
from legaldost.domain.schemas import AnswerMode, DraftAnswer, EvidenceStatus, LegalAnswer
from legaldost.language import detect_language, requested_language
from legaldost.llm.base import LLMError, LLMProvider, MeteredLLM, UsageLedger
from legaldost.pipeline.conversation import ConversationStore
from legaldost.pipeline.evidence import build_packet, reorder
from legaldost.pipeline.formatter import render
from legaldost.pipeline.generator import ExtractiveGenerator, LLMGenerator
from legaldost.pipeline.status import determine_status
from legaldost.pipeline.validator import CitationValidator
from legaldost.pipeline.validator import _overlap as overlap
from legaldost.retrieval.coverage import corpus_domains
from legaldost.retrieval.embeddings import Embedder
from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters
from legaldost.safety import TriageCategory, triage
from legaldost.strings import t

log = logging.getLogger(__name__)

COMMANDS: dict[str, re.Pattern[str]] = {
    "delete": re.compile(r"^\s*(delete my data|delete|forget me|ನನ್ನ ಡೇಟಾ ಅಳಿಸಿ)\s*[.!]?\s*$", re.I),
    "reset": re.compile(r"^\s*(reset|start over|new question|restart)\s*[.!]?\s*$", re.I),
    "help": re.compile(r"^\s*(help|menu|\?|ಸಹಾಯ)\s*$", re.I),
    "more": re.compile(r"^\s*(more|explain|details?|explain the law|1|ವಿವರ)\s*[.!]?\s*$", re.I),
    "evidence": re.compile(
        r"^\s*(sources?|evidence|show (the )?evidence|show sources|2|ಮೂಲಗಳು|ಸಾಕ್ಷ್ಯ)\s*[.!]?\s*$", re.I
    ),
    "kannada": re.compile(r"^\s*(kannada|ಕನ್ನಡ)\s*$", re.I),
    "english": re.compile(r"^\s*(english|ಇಂಗ್ಲಿಷ್)\s*$", re.I),
}

# Words added to the retrieval query for established fact values (search hints only).
FACT_SEARCH_HINTS: dict[tuple[str, str], list[str]] = {
    ("glazing_type", "aftermarket_film"): ["film", "pasting", "glazing faced with plastics"],
    ("glazing_type", "factory_fitted"): ["manufactured", "manufacturer", "safety glass"],
}
MAX_CLARIFYING_QUESTIONS = 2
# "What can you do?"-style messages (whole message, optionally with a greeting) get the help reply.
CAPABILITY_QUESTION = re.compile(
    r"^\W*(?:(?:hi|hello|hey|namaste|hii+)\b[\W]*)?(?:please\W+)?(?:"
    r"(?:what|how)\s+(?:can|could|do|will)\s+(?:you|u)\s+(?:do|help|assist)(?:\s+me)?(?:\s+with)?(?:\s+for\s+me)?"
    r"|what\s+(?:all\s+)?(?:can|should)\s+i\s+ask(?:\s+you)?"
    r"|what\s+(?:all\s+)?(?:do\s+you|can\s+you)\s+(?:do|know|cover|answer|help\s+with)"
    r"|what\s+(?:topics|areas|laws|questions|services|features)\b.*"
    r"|(?:who|what)\s+(?:are|r)\s+(?:you|u)"
    r"|what\s+is\s+(?:this|legaldost)(?:\s+(?:app|bot|service|number))?"
    r"|how\s+(?:does|do)\s+(?:this|you|it)\s+work"
    r"|(?:can|could)\s+(?:you|u)\s+help(?:\s+me)?"
    r"|(?:i\s+)?need\s+(?:some\s+)?help|help\s+me"
    r")\W*$",
    re.IGNORECASE,
)
FINE_QUESTION = re.compile(r"\b(fine|fines|fined|penalty|challan|how much)\b", re.I)
# Topics where the user may be dealing with an officer right now.
ROADSIDE_TOPICS = {"traffic.tinted_glass", "traffic.challan", "traffic.documents"}


@dataclass
class Reply:
    text: str
    outcome: str
    answer: LegalAnswer | None = None
    routing: RoutingDecision | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class AnswerPipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        registry: Registry,
        engine: DecisionEngine,
        embedder: Embedder,
        provider: LLMProvider | None,
        channel: str = "dev",
    ) -> None:
        self.session = session
        self.settings = settings
        self.registry = registry
        self.engine = engine
        self.embedder = embedder
        self.provider = provider
        self.channel = channel
        self.store = ConversationStore(session, settings.conversation_retention_hours)
        self._corpus_cache: set[str] | None = None

    # ------------------------------------------------------------------------------------------
    def handle(self, conv: Conversation, text: str) -> Reply:
        started = time.monotonic()
        text = (text or "").strip()
        supported = self.settings.supported_languages
        language = conv.language if conv.language in supported else supported[0]
        prefix = ""
        if not conv.notice_shown:
            prefix = t("notice", language, hours=self.settings.conversation_retention_hours) + "\n\n"
            conv.notice_shown = True
        if len(text) > self.settings.max_message_chars:
            return self._done(
                conv,
                Reply(prefix + t("too_long", language, limit=self.settings.max_message_chars), "rejected"),
                started,
            )
        if not text:
            return self._done(conv, Reply(prefix + self._help(language), "help"), started)

        command = next((name for name, pattern in COMMANDS.items() if pattern.match(text)), None)
        if command:
            return self._done(conv, self._command(conv, command, language, prefix), started)

        detected = detect_language(text)
        explicit = requested_language(text)
        if detected not in supported or (explicit and explicit not in supported):
            return self._done(
                conv, Reply(prefix + t("english_only", supported[0]), "language_unsupported"), started
            )
        language = explicit or (detected if detected != "en" else language)
        conv.language = language

        if CAPABILITY_QUESTION.match(text):
            return self._done(conv, Reply(prefix + self._help(language), "help"), started)

        result = self._answer_flow(conv, text, language)
        tri = triage(text)
        if tri.needs_escalation and result.outcome not in ("answer", "emergency", "declined"):
            # Answers render their own escalation notice; other replies get it appended here.
            key = "liberty_note" if tri.category == TriageCategory.LIBERTY else "deadline_note"
            contact = load_contacts().get("legal_aid")
            aid = (
                " — ".join(x for x in [contact.name.get(language), contact.phone, contact.url] if x)
                if contact
                else ""
            )
            result.text += "\n\n⚠️ " + t(key, language, legal_aid=aid)
        result.text = prefix + result.text
        self._log_gap(text, result)
        return self._done(conv, result, started)

    # ------------------------------------------------------------------------------------------
    def _command(self, conv: Conversation, command: str, language: str, prefix: str) -> Reply:
        if command == "delete":
            self.store.delete(conv)
            return Reply(t("deleted", language), "deleted")
        if command == "reset":
            self.store.reset(conv)
            return Reply(prefix + t("reset", language), "reset")
        if command == "help":
            return Reply(prefix + self._help(language), "help")
        if command in ("kannada", "english"):
            wanted = "kn" if command == "kannada" else "en"
            if wanted not in self.settings.supported_languages:
                return Reply(prefix + t("english_only", language), "language_unsupported")
            conv.language = wanted
            return Reply(prefix + t("language_set", conv.language), "language")
        if not conv.last_answer:
            return Reply(prefix + t("no_previous", language), "no_previous")
        answer = LegalAnswer.model_validate(conv.last_answer)
        mode = AnswerMode.EXPLAIN if command == "more" else AnswerMode.EVIDENCE
        return Reply(prefix + render(answer, mode), f"mode_{mode.value}", answer=answer)

    def _corpus_domains(self) -> set[str]:
        if self._corpus_cache is None:
            self._corpus_cache = corpus_domains(self.session)
        return self._corpus_cache

    def _coverage(self, language: str) -> str:
        loaded = self._corpus_domains()
        labels = [
            d.label.get(language)
            for key, d in self.registry.domains.items()
            if key != GENERAL_DOMAIN and d.enabled and key in loaded
        ]
        return ", ".join(labels) or t("coverage_none", language)

    def _help(self, language: str) -> str:
        return t("help", language, coverage=self._coverage(language))

    @staticmethod
    def _legal_aid(language: str) -> str:
        contact = load_contacts().get("legal_aid")
        if not contact:
            return ""
        return " — ".join(x for x in [contact.name.get(language), contact.phone, contact.url] if x)

    # ------------------------------------------------------------------------------------------
    def _answer_flow(self, conv: Conversation, text: str, language: str) -> Reply:
        tri = triage(text)
        if tri.category == TriageCategory.EMERGENCY:
            phone = load_contacts().get("emergency")
            return Reply(
                t("emergency", language, phone=phone.phone if phone else "112"),
                "emergency",
                diagnostics={"triage": tri.category.value},
            )
        if tri.category == TriageCategory.PROHIBITED:
            return Reply(t("prohibited", language), "declined", diagnostics={"triage": tri.category.value})

        facts: dict[str, Any] = dict(conv.facts or {})
        awaiting: list[str] = list(facts.get("_awaiting", []))
        routing = self.engine.route(text, language, conv.topic)

        # A short reply to our clarifying question continues the pending topic.
        topic_key = routing.topic
        is_follow_up = False
        if conv.topic and (awaiting or conv.pending_question):
            candidate = self.registry.topics.get(conv.topic)
            wanted = (candidate.required_facts + candidate.optional_facts) if candidate else []
            extracted = extract_facts(text, self.registry, wanted, awaiting[0] if awaiting else None)
            if extracted and (topic_key in (None, conv.topic) or len(text.split()) <= 12):
                topic_key, is_follow_up = conv.topic, True
        if topic_key is None and routing.intent == "greeting":
            return Reply(self._help(language), "help", routing=routing)
        if topic_key is None and routing.intent == "legal_question":
            # No specific topic matched: search across everything that is loaded.
            topic_key = GENERAL_TOPIC
        if topic_key is None:
            return Reply(t("unknown_topic", language), "unknown_topic", routing=routing)

        topic = self.registry.topics[topic_key]
        if topic_key != conv.topic:
            # New subject: earlier facts may not apply. Keep only the jurisdiction the user stated.
            facts = {k: v for k, v in facts.items() if k == "jurisdiction"}
            conv.pending_question = None
            awaiting = []
        conv.topic = topic_key

        if not self.registry.domain_supported(topic.domain, self._corpus_domains()):
            label = self.registry.domains[topic.domain].label.get(language)
            summary = t("unsupported_domain", language, domain=label, coverage=self._coverage(language))
            if topic.risk == "high":
                summary += "\n\n⚠️ " + t("serious_matter_note", language, legal_aid=self._legal_aid(language))
            answer = LegalAnswer(
                kind="abstain",
                language=language,  # type: ignore[arg-type]
                summary=summary,
                topic=topic_key,
                domain=topic.domain,
            )
            conv.facts = facts
            return Reply(answer.summary, "unsupported_domain", answer=answer, routing=routing)

        wanted = topic.required_facts + topic.optional_facts
        new_facts = extract_facts(text, self.registry, wanted, awaiting[0] if awaiting else None)
        facts.update(new_facts)
        question = text if not is_follow_up else (conv.pending_question or text)
        if not is_follow_up:
            conv.pending_question = text

        missing = [f for f in topic.required_facts if f not in facts]
        if missing:
            ask = missing[:MAX_CLARIFYING_QUESTIONS]
            facts["_awaiting"] = ask
            conv.facts = facts
            lines = [t("clarify_intro", language)]
            lines += [
                f"{i}. {self.registry.facts[f].question.get(language)}" for i, f in enumerate(ask, start=1)
            ]
            lines.append(t("clarify_why", language))
            answer = LegalAnswer(
                kind="clarification",
                language=language,  # type: ignore[arg-type]
                summary="\n".join(lines),
                missing_facts=ask,
                topic=topic_key,
                domain=topic.domain,
            )
            return Reply(
                answer.summary, "clarification", answer=answer, routing=routing, diagnostics={"missing": ask}
            )

        facts.pop("_awaiting", None)
        conv.facts = facts
        answer, diag = self._grounded_answer(question, text, topic_key, topic, facts, language, routing, tri)
        conv.last_answer = answer.model_dump(mode="json")
        return Reply(
            render(answer, AnswerMode.QUICK),
            "answer" if answer.kind == "answer" else answer.kind,
            answer=answer,
            routing=routing,
            diagnostics=diag,
        )

    # ------------------------------------------------------------------------------------------
    def _grounded_answer(
        self,
        question: str,
        latest: str,
        topic_key: str,
        topic: TopicDef,
        facts: dict[str, Any],
        language: str,
        routing: RoutingDecision,
        tri: Any,
    ) -> tuple[LegalAnswer, dict[str, Any]]:
        jurisdiction = facts.get("jurisdiction", {}).get("value")
        hints = list(topic.retrieval_terms)
        anchors: list[str] = []  # derived from this question, not the topic's broad search words
        for (fact, value), words in FACT_SEARCH_HINTS.items():
            if facts.get(fact, {}).get("value") == value:
                anchors += words
        for provision in facts.get("cited_provision", {}).get("value", []) or []:
            anchors.append(str(provision))
        query_text = question if question == latest else f"{question} {latest}"
        anchors += legal_term_hints(query_text, load_legal_terms())
        hints += [h for h in anchors if h not in hints]
        # The catch-all has no topic-specific search terms, so it demands a closer word match.
        spec = QuerySpec(
            text=query_text,
            expansion_terms=hints,
            min_coverage=0.5 if topic.domain == GENERAL_DOMAIN else 0.2,
            require_phrase=topic.domain == GENERAL_DOMAIN,
            anchor_terms=anchors,
        )
        filters = RetrievalFilters(
            jurisdictions=["IN", jurisdiction] if jurisdiction else ["IN"],
            domains=None if topic.domain == GENERAL_DOMAIN else [topic.domain],
        )
        # Save conversation state before searching: the first search in a process builds the
        # vector index from every stored embedding (a minute or more on a large corpus) and must
        # not hold the SQLite write lock while it does.
        self.session.commit()
        retriever = HybridRetriever(self.session, self.embedder)
        local_model = self.provider is not None and self.provider.name == "ollama"
        max_passages = (
            min(self.settings.retrieval_max_passages, self.settings.ollama_max_passages)
            if local_model
            else self.settings.retrieval_max_passages
        )
        max_chars = (
            min(self.settings.evidence_max_chars_per_passage, self.settings.ollama_max_chars_per_passage)
            if local_model
            else self.settings.evidence_max_chars_per_passage
        )
        results = retriever.search(
            spec,
            filters,
            limit=max_passages,
            pool=self.settings.retrieval_candidate_pool,
        )
        diag: dict[str, Any] = {"retrieved": len(results), "llm_calls": 0}
        assumptions = []
        if topic.date_sensitive and "incident_date" not in facts:
            assumptions.append(t("assume_current", language))
        if topic.domain == "traffic" and FINE_QUESTION.search(query_text):
            assumptions.insert(0, t("traffic_fine_note", language))
        if jurisdiction and jurisdiction != "IN-KA":
            assumptions.append(
                f"State-specific rules for {JURISDICTION_NAMES.get(jurisdiction, jurisdiction)} are not loaded; "
                "only central sources were searched."
            )
        if topic.domain == GENERAL_DOMAIN and results:
            # The catch-all has no area of law behind it. Judgments alone (thousands of them, on
            # every subject) would let it "answer" from rulings that merely share words with the
            # question, e.g. call-record evidence for "is recording a call legal?". Same rule as
            # for areas: no law text, no answer.
            source_ids = {r.source_id for r in results}
            types = set(
                self.session.scalars(select(LegalSource.document_type).where(LegalSource.id.in_(source_ids)))
            )
            if types <= {"judgment"}:
                diag["judgments_only"] = True
                results = []
        if not results:
            summary = t("no_evidence", language, what=topic.label.get(language))
            if topic.risk == "high":
                summary += "\n\n⚠️ " + t("serious_matter_note", language, legal_aid=self._legal_aid(language))
            answer = LegalAnswer(
                kind="abstain",
                language=language,  # type: ignore[arg-type]
                summary=summary,
                topic=topic_key,
                domain=topic.domain,
                assumptions=assumptions,
            )
            return answer, diag

        packet = build_packet(self.session, query_text, results, jurisdiction, max_chars)
        order = self.engine.prioritise_evidence(
            query_text,
            [
                EvidenceCandidate(evidence_id=i.evidence_id, title=i.title, locator=i.locator, text=i.text)
                for i in packet.items
            ],
        )
        packet = reorder(packet, order)

        validator = CitationValidator(self.session)
        draft: DraftAnswer
        generator_name = "extractive"
        flags: list[str] = []
        if self.provider is not None:
            ledger = UsageLedger(
                self.session, self.settings.llm_monthly_budget_usd, self.settings.llm_max_calls_per_question
            )
            llm_gen = LLMGenerator(MeteredLLM(self.provider, ledger))
            # Release the SQLite write lock before a call that can take a minute on a local model,
            # so imports and other conversations are not blocked meanwhile.
            self.session.commit()
            try:
                draft = llm_gen.generate(
                    question if question == latest else query_text,
                    packet,
                    language,
                    facts,
                    topic,
                    "deep" if routing.needs_deep_review else "standard",
                )
                generator_name = "llm"
            except LLMError as exc:
                log.warning("LLM generation unavailable (%s); using extractive answer", type(exc).__name__)
                flags.append(f"llm_unavailable:{type(exc).__name__}")
                draft = ExtractiveGenerator().generate(query_text, packet, language)
            diag["llm_calls"] = ledger.calls_this_question
        else:
            draft = ExtractiveGenerator().generate(query_text, packet, language)

        claims, cards, report = validator.validate(
            draft, packet, facts, query_text, require_quotes=generator_name == "llm"
        )
        if generator_name == "llm" and (report.blocked or not claims):
            # Never show an unsupported definitive answer: fall back to verifiable quotes only.
            flags.append("llm_draft_blocked" if report.blocked else "llm_draft_no_valid_claims")
            prior_flags = report.flags
            draft = ExtractiveGenerator().generate(query_text, packet, language)
            claims, cards, report = validator.validate(draft, packet, facts, query_text)
            report.flags = list(dict.fromkeys(prior_flags + report.flags))
            generator_name = "extractive"
        report.flags = list(dict.fromkeys(flags + report.flags))
        if generator_name == "llm" and claims:
            # Replace any part of the model's prose that the verified points do not support.
            updates: dict[str, Any] = {}
            if report.summary_unsupported:
                # Use the verified point that best answers the user's question.
                updates["summary"] = max(claims, key=lambda c: overlap(question, c.text)).text
            if report.removed_items:
                updates["important_exceptions"] = [
                    x for x in draft.important_exceptions if x not in report.removed_items
                ]
                updates["safe_next_steps"] = [
                    x for x in draft.safe_next_steps if x not in report.removed_items
                ]
            if report.application_unsupported:
                updates["application_to_user_facts"] = ""
            if updates:
                draft = draft.model_copy(update=updates)

        missing_required = [
            f for f in topic.required_facts if f not in facts or facts[f].get("value") == "unsure"
        ]
        status, reasons, escalation = determine_status(
            draft,
            claims,
            cards,
            report,
            missing_required,
            generator_name,
            tri,
            jurisdiction,
            language,
            high_risk=topic.risk == "high",
        )
        # Quotes that matched words but not the question are not an answer: in the catch-all area,
        # or when the model's own summary could not be backed by any verified point, say so instead.
        off_target = (
            status == EvidenceStatus.NONE and (topic.domain == GENERAL_DOMAIN or report.summary_unsupported)
        ) or (
            # In the catch-all, a model draft that failed verification means the passages did not
            # answer the question; raw quotes from them would only look like an answer.
            topic.domain == GENERAL_DOMAIN
            and (
                report.summary_unsupported
                or any(f in report.flags for f in ("llm_draft_blocked", "llm_draft_no_valid_claims"))
            )
        )
        if not claims or off_target:
            if off_target:
                report.flags = list(dict.fromkeys([*report.flags, "abstained_off_target"]))
            answer = LegalAnswer(
                kind="abstain",
                language=language,  # type: ignore[arg-type]
                summary=t("no_evidence", language, what=topic.label.get(language)),
                evidence_status=status,
                status_reasons=reasons,
                validation=report,
                generator=generator_name,
                topic=topic_key,
                domain=topic.domain,
                assumptions=assumptions,
            )
            return answer, diag
        next_steps = list(draft.safe_next_steps)
        if topic_key in ROADSIDE_TOPICS and generator_name == "extractive":
            next_steps.insert(0, t("next_stay_calm", language))
        answer = LegalAnswer(
            kind="answer",
            language=language,  # type: ignore[arg-type]
            summary=draft.summary,
            legal_position=draft.legal_position,
            claims=claims,
            supporting_sources=cards,
            application_to_user_facts=draft.application_to_user_facts,
            important_exceptions=draft.important_exceptions,
            missing_facts=draft.missing_facts,
            safe_next_steps=next_steps,
            evidence_status=status,
            status_reasons=reasons,
            recommended_escalation=escalation,
            assumptions=assumptions,
            generator=generator_name,
            validation=report,
            topic=topic_key,
            domain=topic.domain,
        )
        diag.update({"citations": len(cards), "flags": report.flags})
        return answer, diag

    # ------------------------------------------------------------------------------------------
    def _log_gap(self, text: str, reply: Reply) -> None:
        """Record unanswered questions as keywords only, so the operator knows what to load next."""
        if not self.settings.gap_log_enabled:
            return
        answer = reply.answer
        flags = answer.validation.flags if answer else []
        if reply.outcome in ("abstain", "unsupported_domain", "unknown_topic"):
            reason = reply.outcome
        elif (
            answer
            and answer.kind == "answer"
            and answer.generator == "extractive"
            and any(f.startswith("llm_draft") for f in flags)
        ):
            reason = "model_answer_blocked"
        else:
            return
        terms = QuerySpec(text).distinctive_terms()
        keep = sorted(t for t in terms if len(t) >= 3 and not t.isdigit())[:8]
        now = datetime.now(UTC)
        self.session.add(
            AnswerGap(
                channel=self.channel,
                outcome=reply.outcome,
                reason=reason,
                topic=answer.topic if answer else (reply.routing.topic if reply.routing else None),
                domain=answer.domain if answer else (reply.routing.domain if reply.routing else None),
                terms=keep,
                created_at=now,
                expires_at=now + timedelta(days=self.settings.gap_log_retention_days),
            )
        )

    def _done(self, conv: Conversation, reply: Reply, started: float) -> Reply:
        latency = int((time.monotonic() - started) * 1000)
        answer = reply.answer
        self.session.add(
            AnswerLog(
                channel=self.channel,
                outcome=reply.outcome,
                intent=reply.routing.intent if reply.routing else None,
                domain=answer.domain if answer else (reply.routing.domain if reply.routing else None),
                topic=answer.topic if answer else None,
                language=answer.language if answer else None,
                evidence_status=answer.evidence_status.value if answer and answer.kind == "answer" else None,
                passages_retrieved=int(reply.diagnostics.get("retrieved", 0)),
                citations_shown=len(answer.supporting_sources) if answer else 0,
                validator_flags=list(answer.validation.flags) if answer else [],
                llm_calls=int(reply.diagnostics.get("llm_calls", 0)),
                latency_ms=latency,
            )
        )
        reply.diagnostics["latency_ms"] = latency
        return reply
