"""Source manifests: curated YAML lists of sources to register and fetch."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl

from legaldost.ingestion.service import SourceSpec


class ManifestEntry(BaseModel):
    source: SourceSpec
    fetch_url: HttpUrl | None = None
    local_file: str | None = None
    notes: str | None = None


class Manifest(BaseModel):
    name: str
    description: str = ""
    entries: list[ManifestEntry] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list, description="source_keys with enabled: false")


def load_manifest(path: Path) -> Manifest:
    """Parse a manifest. Entries with ``enabled: false`` are listed in ``skipped`` and not validated,
    so a template can hold placeholders until an operator fills in the real URL and file."""
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    entries, skipped = [], []
    for item in raw.get("sources", []):
        if item.pop("enabled", True) is False:
            skipped.append(str(item.get("source_key")))
            continue
        fetch_url = item.pop("fetch_url", None)
        local_file = item.pop("local_file", None)
        notes = item.pop("notes", None)
        entries.append(
            ManifestEntry(
                source=SourceSpec.model_validate(item),
                fetch_url=fetch_url,
                local_file=local_file,
                notes=notes,
            )
        )
    return Manifest(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        entries=entries,
        skipped=skipped,
    )
