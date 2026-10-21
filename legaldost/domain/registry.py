"""Loader for ``knowledge/topics.yaml`` and ``knowledge/official_contacts.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from legaldost.config import get_settings

GENERAL_DOMAIN = "general"
GENERAL_TOPIC = "general.legal"


class Localized(BaseModel):
    en: str
    kn: str | None = None

    def get(self, language: str) -> str:
        return (self.kn if language == "kn" and self.kn else None) or self.en


class DomainDef(BaseModel):
    enabled: bool = True
    label: Localized


class FactDef(BaseModel):
    kind: Literal["jurisdiction", "enum", "percent", "yes_no", "provision", "date"]
    question: Localized
    values: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


class TopicDef(BaseModel):
    domain: str
    label: Localized
    keywords: dict[str, list[str]] = Field(default_factory=dict)
    retrieval_terms: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    optional_facts: list[str] = Field(default_factory=list)
    date_sensitive: bool = False
    risk: Literal["normal", "high"] = "normal"


class Registry(BaseModel):
    review_status: str = "unreviewed"
    domains: dict[str, DomainDef]
    facts: dict[str, FactDef]
    topics: dict[str, TopicDef]

    def topic(self, key: str | None) -> TopicDef | None:
        return self.topics.get(key) if key else None

    def domain_enabled(self, domain: str | None) -> bool:
        return bool(domain and domain in self.domains and self.domains[domain].enabled)

    def domain_supported(self, domain: str | None, corpus_domains: set[str]) -> bool:
        """Enabled in configuration AND backed by at least one loaded source."""
        if not self.domain_enabled(domain):
            return False
        if domain == GENERAL_DOMAIN:
            return bool(corpus_domains)
        return domain in corpus_domains


class Contact(BaseModel):
    name: Localized
    phone: str | None = None
    url: str | None = None
    verify_at: str
    last_checked: str | None = None


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


@lru_cache
def load_registry(path: str | None = None) -> Registry:
    file = Path(path) if path else get_settings().knowledge_dir / "topics.yaml"
    registry = Registry.model_validate(_load_yaml(file))
    for key, topic in registry.topics.items():
        if topic.domain not in registry.domains:
            raise ValueError(f"topic {key} references unknown domain {topic.domain}")
        for fact in [*topic.required_facts, *topic.optional_facts]:
            if fact not in registry.facts:
                raise ValueError(f"topic {key} references unknown fact {fact}")
    return registry


@lru_cache
def load_legal_terms(path: str | None = None) -> dict[str, list[str]]:
    """Everyday word or phrase (lowercase) -> statutory search terms (``knowledge/legal_terms.yaml``)."""
    file = Path(path) if path else get_settings().knowledge_dir / "legal_terms.yaml"
    if not file.exists():
        return {}
    data = _load_yaml(file)
    return {str(k).lower(): [str(t) for t in v] for k, v in (data.get("terms") or {}).items()}


def legal_term_hints(text: str, terms: dict[str, list[str]]) -> list[str]:
    """Statutory search terms for every everyday word/phrase found (whole words) in ``text``."""
    import re

    lowered = text.lower()
    hints: list[str] = []
    for phrase, mapped in terms.items():
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lowered):
            hints += [m for m in mapped if m not in hints]
    return hints


@lru_cache
def load_contacts(path: str | None = None) -> dict[str, Contact]:
    file = Path(path) if path else get_settings().knowledge_dir / "official_contacts.yaml"
    data = _load_yaml(file)
    return {k: Contact.model_validate(v) for k, v in data.get("contacts", {}).items()}
