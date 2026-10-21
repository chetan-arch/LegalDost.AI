"""Deterministic extraction of material facts that the *user* stated.

Rules: never infer a fact the user did not state; if two contradictory values are mentioned the
fact stays unknown so the assistant asks again.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from legaldost.domain.registry import FactDef, Registry

STATE_CODES: dict[str, str] = {
    "karnataka": "IN-KA",
    "bengaluru": "IN-KA",
    "bangalore": "IN-KA",
    "mysuru": "IN-KA",
    "mysore": "IN-KA",
    "mangaluru": "IN-KA",
    "mangalore": "IN-KA",
    "hubballi": "IN-KA",
    "hubli": "IN-KA",
    "dharwad": "IN-KA",
    "belagavi": "IN-KA",
    "belgaum": "IN-KA",
    "kalaburagi": "IN-KA",
    "udupi": "IN-KA",
    "shivamogga": "IN-KA",
    "tumakuru": "IN-KA",
    # Kannada stems without the final vowel sign so inflected forms (ಬೆಂಗಳೂರಿನಲ್ಲಿ) also match.
    "ಕರ್ನಾಟಕ": "IN-KA",
    "ಬೆಂಗಳೂರ": "IN-KA",
    "ಮೈಸೂರ": "IN-KA",
    "ಮಂಗಳೂರ": "IN-KA",
    "kerala": "IN-KL",
    "tamil nadu": "IN-TN",
    "chennai": "IN-TN",
    "maharashtra": "IN-MH",
    "mumbai": "IN-MH",
    "pune": "IN-MH",
    "delhi": "IN-DL",
    "telangana": "IN-TG",
    "hyderabad": "IN-TG",
    "andhra pradesh": "IN-AP",
    "goa": "IN-GA",
    "gujarat": "IN-GJ",
    "rajasthan": "IN-RJ",
    "uttar pradesh": "IN-UP",
    "west bengal": "IN-WB",
    "kolkata": "IN-WB",
    "punjab": "IN-PB",
    "haryana": "IN-HR",
    "bihar": "IN-BR",
    "odisha": "IN-OR",
    "madhya pradesh": "IN-MP",
    "assam": "IN-AS",
    "jharkhand": "IN-JH",
    "chhattisgarh": "IN-CT",
    "uttarakhand": "IN-UT",
    "himachal pradesh": "IN-HP",
}

JURISDICTION_NAMES = {
    "IN": "India (central law)",
    "IN-KA": "Karnataka",
    "IN-KL": "Kerala",
    "IN-TN": "Tamil Nadu",
    "IN-MH": "Maharashtra",
    "IN-DL": "Delhi",
    "IN-TG": "Telangana",
    "IN-AP": "Andhra Pradesh",
    "IN-GA": "Goa",
    "IN-GJ": "Gujarat",
    "IN-RJ": "Rajasthan",
    "IN-UP": "Uttar Pradesh",
    "IN-WB": "West Bengal",
    "IN-PB": "Punjab",
    "IN-HR": "Haryana",
    "IN-BR": "Bihar",
    "IN-OR": "Odisha",
    "IN-MP": "Madhya Pradesh",
    "IN-AS": "Assam",
    "IN-JH": "Jharkhand",
    "IN-CT": "Chhattisgarh",
    "IN-UT": "Uttarakhand",
    "IN-HP": "Himachal Pradesh",
}

NEGATION = re.compile(r"\b(not|no|isn'?t|wasn'?t|without|never)\b(\W+\w+){0,2}\W*$", re.IGNORECASE)
PROVISION_RE = re.compile(
    r"\b(section|sec\.?|s\.|rule|r\.)\s*(\d{1,4}[A-Z]?(?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*)", re.IGNORECASE
)
PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent)", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
DMY_DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
MONTH_DATE_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s*,?\s*(20\d{2})\b", re.IGNORECASE)
YES_RE = re.compile(r"^\s*(yes|yeah|yep|haan|ha|ಹೌದು)\b", re.IGNORECASE)
NO_RE = re.compile(r"^\s*(no|nope|illa|ಇಲ್ಲ)\b", re.IGNORECASE)


def _contains_phrase(text: str, phrase: str) -> int | None:
    """Return match position for phrase, honouring word boundaries for Latin script."""
    if re.search(r"[a-z]", phrase):
        m = re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text)
        return m.start() if m else None
    idx = text.find(phrase)
    return idx if idx >= 0 else None


def _negated(text: str, pos: int) -> bool:
    return bool(NEGATION.search(text[max(0, pos - 30) : pos]))


# Negates a place only when directly before it: "not in Karnataka", "outside Kerala".
PLACE_NEGATION = re.compile(r"\b(not|isn'?t|wasn'?t|never|outside)\s+(in\s+|from\s+)?$", re.IGNORECASE)


def extract_jurisdiction(text: str) -> str | None:
    lowered = text.lower()
    found: set[str] = set()
    for name, code in STATE_CODES.items():
        pos = _contains_phrase(lowered, name)
        if pos is not None and not PLACE_NEGATION.search(lowered[max(0, pos - 20) : pos]):
            found.add(code)
    return found.pop() if len(found) == 1 else None


def extract_provisions(text: str) -> list[str]:
    out: list[str] = []
    for m in PROVISION_RE.finditer(text):
        kind = "Rule" if m.group(1).lower().startswith("r") else "Section"
        number = re.sub(r"\s+", "", m.group(2))
        label = f"{kind} {number}"
        if label not in out:
            out.append(label)
    return out


RELATIVE_DATE_RE = re.compile(
    r"\b(?:(?P<n>\d{1,2}|a|an|one|few|couple of)\s+(?P<unit>days?|weeks?|months?|years?)\s+(?:ago|back)"
    r"|last\s+(?P<unit2>week|month|year))\b"
)
YEAR_ONLY_RE = re.compile(r"\b(?:in|during|since)\s+((?:19|20)\d{2})\b")


def extract_date(text: str, today: date) -> tuple[str, str] | None:
    lowered = text.lower()
    if m := ISO_DATE_RE.search(text):
        candidate = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := DMY_DATE_RE.search(text):
        candidate = (int(m.group(3)), int(m.group(2)), int(m.group(1)))
    elif m := MONTH_DATE_RE.search(text):
        candidate = (int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    elif re.search(r"\b(today|right now|just now)\b", lowered) or "ಇಂದು" in text:
        return today.isoformat(), "today"
    elif re.search(r"\byesterday\b", lowered) or "ನಿನ್ನೆ" in text:
        return (today - timedelta(days=1)).isoformat(), "yesterday"
    elif rel := RELATIVE_DATE_RE.search(lowered):
        # Approximate dates such as "last week" or "3 months ago" (the raw words are kept too).
        amount = rel.group("n")
        n = (
            1
            if amount in (None, "a", "an", "one", "last", "few", "couple of")
            else int(amount)
            if amount.isdigit()
            else 2
        )
        unit = (rel.group("unit") or rel.group("unit2")).rstrip("s")
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return (today - timedelta(days=days)).isoformat(), rel.group(0)
    elif m := YEAR_ONLY_RE.search(lowered):
        return f"{m.group(1)}-01-01", m.group(0)
    else:
        return None
    try:
        return date(*candidate).isoformat(), m.group(0)
    except ValueError:
        return None


def _extract_enum(fact: FactDef, text: str) -> str | None:
    lowered = text.lower()
    matches: set[str] = set()
    for value, phrases_by_lang in fact.values.items():
        for phrases in phrases_by_lang.values():
            for phrase in phrases:
                pos = _contains_phrase(lowered, phrase.lower())
                if pos is not None and not _negated(lowered, pos):
                    matches.add(value)
    return matches.pop() if len(matches) == 1 else None


def extract_facts(
    text: str,
    registry: Registry,
    wanted: list[str],
    pending_fact: str | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract only the facts in ``wanted`` (plus ``pending_fact``) from user text."""
    today = (now or datetime.now()).date()
    names = list(dict.fromkeys([*wanted, *([pending_fact] if pending_fact else [])]))
    facts: dict[str, dict[str, Any]] = {}
    for name in names:
        fact = registry.facts.get(name)
        if fact is None:
            continue
        value: Any = None
        raw: str | None = None
        if fact.kind == "jurisdiction":
            value = extract_jurisdiction(text)
        elif fact.kind == "enum":
            value = _extract_enum(fact, text)
        elif fact.kind == "yes_no":
            value = _extract_enum(fact, text)
            if value is None and name == pending_fact:
                if YES_RE.search(text):
                    value = "yes"
                elif NO_RE.search(text):
                    value = "no"
            if value is None and extract_provisions(text) and re.search(r"challan|notice|ಚಲನ್", text, re.I):
                value = "yes"
        elif fact.kind == "percent":
            m = PERCENT_RE.search(text)
            if m and (name == pending_fact or re.search(r"vlt|tint|transmission|glass|ಗಾಜು", text, re.I)):
                pct = float(m.group(1))
                if 0 <= pct <= 100:
                    value, raw = pct, m.group(0)
        elif fact.kind == "provision":
            provisions = extract_provisions(text)
            if provisions:
                value = provisions
        elif fact.kind == "date":
            found = extract_date(text, today)
            if found:
                value, raw = found
        if value is not None:
            facts[name] = {"value": value, "source": "user", **({"raw": raw} if raw else {})}
    return facts
