"""Text normalisation and tokenisation shared by retrieval and validation."""

from __future__ import annotations

import hashlib
import re
import unicodedata

STOPWORDS = frozenset(
    "a an the and or of to in on for by with at from as is are was were be been being this that these "
    "those it its i me my we our you your he she they them their can could should would will shall may "
    "might must do does did have has had not no if then than so such any all which who whom what when "
    "where why how there here into under over about upon also other said per".split()  # noqa: SIM905
)

# Latin alphanumerics, Kannada block (U+0C80-U+0CFF), Devanagari block (U+0900-U+097F).
TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?|[ಀ-೿]+|[ऀ-ॿ]+")
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> str:
    """Normalise for comparison: NFKC, unified quotes/dashes, lowercase, collapsed whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).lower()
    return _WS.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize(text))


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


def stem(token: str) -> str:
    """Very light suffix stripping so 'fined'/'fines' meet 'fine'. Not linguistic stemming."""
    for suffix in ("ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix) and not token.isdigit():
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
REFERENCE_RE = re.compile(
    r"\b(section|sec\.?|rule|sub-rule|sub-section|article|regulation|clause)\s*(\d{1,4}[a-z]?)", re.IGNORECASE
)


_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "million": 1_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
}
_NUMBER_WORD_RE = re.compile(r"[a-z]+")


def number_words_in(text: str) -> set[str]:
    """Numbers written in words, e.g. "one thousand" -> "1000", "twenty-five lakh" -> "2500000".

    Statutes usually spell out amounts and periods; model answers usually use digits."""
    out: set[str] = set()
    total = current = 0
    active = False
    for word in _NUMBER_WORD_RE.findall(normalize(text).replace("-", " ")):
        if word in _UNITS:
            current += _UNITS[word]
            active = True
        elif word in _SCALES and active:
            scale = _SCALES[word]
            if scale == 100:
                current *= 100
            else:
                total += current * scale
                current = 0
        elif word == "and" and active:
            continue
        else:
            if active:
                out.add(str(total + current))
            total = current = 0
            active = False
    if active:
        out.add(str(total + current))
    return out


def numbers_in(text: str) -> set[str]:
    digits = {m.group(1).rstrip(".") for m in NUMBER_RE.finditer(normalize(text).replace(",", ""))}
    return digits | number_words_in(text)


def references_in(text: str) -> set[str]:
    out = set()
    for m in REFERENCE_RE.finditer(normalize(text)):
        kind = m.group(1).lower().rstrip(".")
        kind = {"sec": "section", "sub-section": "section", "sub-rule": "rule"}.get(kind, kind)
        out.add(f"{kind} {m.group(2).lower()}")
    return out
