"""Render a ``LegalAnswer`` as WhatsApp-friendly text in one of three modes."""

from __future__ import annotations

from legaldost.domain.registry import load_contacts
from legaldost.domain.schemas import AnswerMode, Escalation, LegalAnswer, SourceCard
from legaldost.strings import t

WHATSAPP_LIMIT = 4096


def _contact_line(key: str, language: str) -> str:
    contacts = load_contacts()
    c = contacts.get(key)
    if not c:
        return ""
    parts = [c.name.get(language)]
    if c.phone:
        parts.append(c.phone)
    if c.url:
        parts.append(c.url)
    return " — ".join(parts)


def _card_ref(card: SourceCard, idx: int) -> str:
    return f"[{idx}] {card.title}, {card.reference}"


def _date_bits(card: SourceCard, language: str) -> str:
    bits = []
    if card.judgment_date:
        bits.append(f"judgment {card.judgment_date.isoformat()}")
    if card.publication_date:
        bits.append(f"published {card.publication_date.isoformat()}")
    if card.commencement_date:
        bits.append(f"in force from {card.commencement_date.isoformat()}")
    bits.append(
        t("status_unknown", language) if card.legal_status == "unknown" else f"status: {card.legal_status}"
    )
    if card.verification_status != "reviewer_verified":
        bits.append(t("unverified_source", language))
    return "; ".join(bits)


def _escalation(answer: LegalAnswer) -> str | None:
    lang = answer.language
    if answer.recommended_escalation == Escalation.LEGAL_AID:
        return t("liberty_note", lang, legal_aid=_contact_line("legal_aid", lang))
    if answer.recommended_escalation == Escalation.SERIOUS_MATTER:
        return t("serious_matter_note", lang, legal_aid=_contact_line("legal_aid", lang))
    if answer.recommended_escalation == Escalation.ADVOCATE:
        return t("deadline_note", lang, legal_aid=_contact_line("legal_aid", lang))
    return None


def render(answer: LegalAnswer, mode: AnswerMode = AnswerMode.QUICK) -> str:
    lang = answer.language
    if answer.kind != "answer":
        return answer.summary
    status_line = f"*{t('label_status', lang)}:* {t('status_' + answer.evidence_status.value, lang)}"
    index = {c.evidence_id: i for i, c in enumerate(answer.supporting_sources, start=1)}

    def cite(eids: list[str]) -> str:
        nums = [str(index[e]) for e in eids if e in index]
        return f" [{', '.join(nums)}]" if nums else ""

    lines: list[str] = []
    if esc := _escalation(answer):
        lines += [f"⚠️ {esc}", ""]

    if mode == AnswerMode.QUICK:
        interpreted = answer.generator != "extractive"
        # 1. TL;DR first.
        lines += [f"📌 *{t('h_tldr', lang)}:* {answer.summary}"]
        # 2. What the law says, in plain words (quotes only when nothing was interpreted).
        if answer.claims:
            lines += ["", f"*{t('h_law_simple' if interpreted else 'h_law', lang)}:*"]
            for claim in answer.claims[:3]:
                lines.append(f"• {claim.text}{cite(claim.evidence_ids)}")
                if claim.quote and not interpreted:
                    lines.append(f'  "{claim.quote}"')
        # 3. How it may apply, and what to do.
        if answer.application_to_user_facts:
            lines += ["", f"*{t('h_apply', lang)}:* {answer.application_to_user_facts}"]
        if answer.safe_next_steps:
            lines += ["", f"*{t('h_next', lang)}:*"] + [f"• {x}" for x in answer.safe_next_steps[:2]]
        # 4. Limits worth knowing.
        keep = answer.important_exceptions[:1] + answer.assumptions[:1] + answer.status_reasons[:1]
        if keep:
            lines += ["", f"*{t('h_exceptions', lang)}:*"] + [f"• {x}" for x in keep]
        # 5. Sources.
        if answer.supporting_sources:
            lines += ["", f"*{t('h_sources', lang)}:*"]
            for i, card in enumerate(answer.supporting_sources[:3], start=1):
                lines.append(f"{_card_ref(card, i)}\n{card.url}")
                if card.binding_note:
                    lines.append(f"⚖️ {card.binding_note}")
        lines += ["", status_line]
        if interpreted:
            lines.append(f"_{t('ai_summary_note', lang)}_")
        lines += ["", t("footer_quick", lang)]

    elif mode == AnswerMode.EXPLAIN:
        lines += [status_line, "", answer.summary]
        if answer.legal_position:
            lines += ["", answer.legal_position]
        if answer.claims:
            lines += ["", f"*{t('h_law', lang)}:*"]
            lines += [f"• {c.text}{cite(c.evidence_ids)}" for c in answer.claims]
        if answer.application_to_user_facts:
            lines += ["", f"*{t('h_apply', lang)}:* {answer.application_to_user_facts}"]
        if answer.important_exceptions:
            lines += ["", f"*{t('h_exceptions', lang)}:*"] + [f"• {x}" for x in answer.important_exceptions]
        missing = answer.missing_facts + answer.status_reasons
        if missing:
            lines += ["", f"*{t('h_missing', lang)}:*"] + [f"• {x}" for x in missing]
        if answer.assumptions:
            lines += ["", f"*{t('h_assumptions', lang)}:*"] + [f"• {x}" for x in answer.assumptions]
        if answer.safe_next_steps:
            lines += ["", f"*{t('h_next', lang)}:*"] + [f"• {x}" for x in answer.safe_next_steps]
        if answer.supporting_sources:
            lines += ["", f"*{t('h_sources', lang)}:*"]
            for i, card in enumerate(answer.supporting_sources, start=1):
                lines.append(
                    f"{_card_ref(card, i)} — {t('cat_' + card.source_category.value, lang)}\n{card.url}"
                )

    else:  # EVIDENCE
        lines += [status_line, "", f"*{t('h_evidence', lang)}:*"]
        if lang == "kn" and (note := t("kn_quotes_english", lang)):
            lines.append(note)
        for i, card in enumerate(answer.supporting_sources, start=1):
            lines += [
                "",
                f"*[{i}] {card.title}*",
                f"{card.reference} · {t('cat_' + card.source_category.value, lang)} · {card.jurisdiction}",
                _date_bits(card, lang),
                f'"{card.excerpt}"',
                card.url,
            ]
            if card.binding_note:
                lines.append(f"⚖️ {card.binding_note}")
            if card.host_note:
                lines.append(f"ℹ️ {card.host_note}")
        if answer.status_reasons:
            lines += ["", f"*{t('h_missing', lang)}:*"] + [f"• {x}" for x in answer.status_reasons]

    lines += ["", t("disclaimer", lang)]
    return "\n".join(lines).strip()


def split_for_whatsapp(text: str, limit: int = WHATSAPP_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            parts.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        parts.append(current)
    return parts
