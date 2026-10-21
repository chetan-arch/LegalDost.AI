"""Bulk import of court judgments from the open Indian judgment datasets on AWS Open Data.

* Supreme Court: https://registry.opendata.aws/indian-supreme-court-judgments/
  ``metadata/parquet/year=YYYY/metadata.parquet`` and ``data/pdf/year=YYYY/english/<path>_EN.pdf``
* High Courts: https://registry.opendata.aws/indian-high-court-judgments/
  ``metadata/parquet/year=YYYY/court=CC/bench=B/metadata.parquet`` and
  ``data/pdf/year=YYYY/court=CC/bench=B/<file name from pdf_link>`` (Karnataka = court ``29_3``).

Both are maintained by Dattam Labs under CC-BY-4.0 and sourced from the courts' / eCourts websites.
They are convenient copies, not certified copies, so every judgment is registered as a
``secondary`` source with an attribution note. Imports are resumable: judgments already ingested
are skipped.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import HttpUrl
from sqlalchemy.orm import Session

from legaldost.config import Settings
from legaldost.db.models import DocumentVersion, LegalSource
from legaldost.decision.rules import _score
from legaldost.domain.registry import GENERAL_DOMAIN, Registry
from legaldost.ingestion.service import IngestionService, SourceSpec

log = logging.getLogger(__name__)

SC_BASE = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com"
HC_BASE = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
ATTRIBUTION = (
    "Copy from the {name} open dataset (Dattam Labs, CC-BY-4.0, https://registry.opendata.aws/{slug}/), "
    "sourced from the court's website; not a certified copy."
)
# Procedural one-liners that rarely help a citizen; skipped for High Court imports.
HC_SKIP_DISPOSALS = re.compile(
    r"non[- ]prosecution|withdrawn|adjourn|transferred|not pressed|abated|infructuous|rejected as not maintainable",
    re.IGNORECASE,
)
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


@dataclass
class JudgmentRecord:
    source_key: str
    title: str
    court: str
    court_level: str
    jurisdiction: str
    judgment_date: date | None
    pdf_url: str
    identifiers: dict[str, Any]
    dataset_name: str
    dataset_slug: str


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text_value = str(value).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text_value[:19], fmt).date()
        except ValueError:
            continue
    return None


def _slug(text_value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text_value.lower()).strip("-")[:80]


class JudgmentDatasets:
    def __init__(self, cache_dir: Path, client: httpx.Client | None = None) -> None:
        self.cache_dir = cache_dir
        self.http = client or httpx.Client(timeout=120, follow_redirects=False)

    def _parquet(self, url: str, dest: Path) -> list[dict[str, Any]]:
        import pyarrow.parquet as pq

        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            resp = self.http.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return pq.read_table(dest).to_pylist()

    def _list_prefixes(self, base: str, prefix: str) -> list[str]:
        resp = self.http.get(f"{base}/", params={"list-type": "2", "delimiter": "/", "prefix": prefix})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)  # noqa: S314 - AWS S3 listing over HTTPS
        return [e.text or "" for e in root.findall("s3:CommonPrefixes/s3:Prefix", _S3_NS)]

    def _list_keys(self, base: str, prefix: str) -> set[str]:
        """All object keys under ``prefix`` (S3 pages of 1,000)."""
        keys: set[str] = set()
        token: str | None = None
        while True:
            params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                params["continuation-token"] = token
            resp = self.http.get(f"{base}/", params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)  # noqa: S314 - AWS S3 listing over HTTPS
            keys.update(e.text or "" for e in root.findall("s3:Contents/s3:Key", _S3_NS))
            token_el = root.find("s3:NextContinuationToken", _S3_NS)
            if token_el is None or not token_el.text:
                return keys
            token = token_el.text

    # -- Supreme Court -------------------------------------------------------------------------
    def supreme_court(self, year: int) -> Iterator[JudgmentRecord]:
        rows = self._parquet(
            f"{SC_BASE}/metadata/parquet/year={year}/metadata.parquet",
            self.cache_dir / "sc" / f"{year}.parquet",
        )
        for r in rows:
            if not r.get("path") or "ENG" not in str(r.get("available_languages") or "ENG"):
                continue
            nc = str(r.get("nc_display") or r.get("case_id") or r["path"])
            yield JudgmentRecord(
                source_key=f"sc-{_slug(nc)}-{_slug(str(r['path']))}"[:119],
                title=" ".join(str(r.get("title") or "Supreme Court judgment").split())[:300],
                court="Supreme Court of India",
                court_level="supreme_court",
                jurisdiction="IN",
                judgment_date=_parse_date(r.get("decision_date")),
                pdf_url=f"{SC_BASE}/data/pdf/year={year}/english/{r['path']}_EN.pdf",
                identifiers={k: r.get(k) for k in ("citation", "case_id", "cnr", "nc_display") if r.get(k)},
                dataset_name="Indian Supreme Court Judgments",
                dataset_slug="indian-supreme-court-judgments",
            )

    # -- High Courts -----------------------------------------------------------------------------
    def high_court(
        self, year: int, court: str = "29_3", jurisdiction: str = "IN-KA"
    ) -> Iterator[JudgmentRecord]:
        prefix = f"metadata/parquet/year={year}/court={court}/"
        for bench_prefix in self._list_prefixes(HC_BASE, prefix):
            bench = bench_prefix.rstrip("/").split("bench=")[-1]
            rows = self._parquet(
                f"{HC_BASE}/{bench_prefix}metadata.parquet",
                self.cache_dir / "hc" / court / str(year) / f"{bench}.parquet",
            )
            # The metadata's pdf_exists flag is unreliable (all "False" for Karnataka 2024 while
            # the PDFs are present), so check against the bucket listing instead.
            pdf_prefix = f"data/pdf/year={year}/court={court}/bench={bench}/"
            present = {k.rsplit("/", 1)[-1] for k in self._list_keys(HC_BASE, pdf_prefix)}
            for r in rows:
                if not r.get("pdf_link") or str(r["pdf_link"]).split("/")[-1] not in present:
                    continue
                if HC_SKIP_DISPOSALS.search(str(r.get("disposal_nature") or "")):
                    continue
                file_name = str(r["pdf_link"]).split("/")[-1]
                yield JudgmentRecord(
                    source_key=f"hc-{court.replace('_', '-')}-{_slug(file_name.removesuffix('.pdf'))}"[:119],
                    title=" ".join(str(r.get("title") or "High Court judgment").split())[:300],
                    court=str(r.get("court") or "High Court"),
                    court_level="high_court",
                    jurisdiction=jurisdiction,
                    judgment_date=_parse_date(r.get("decision_date")),
                    pdf_url=f"{HC_BASE}/data/pdf/year={year}/court={court}/bench={bench}/{file_name}",
                    identifiers={k: r.get(k) for k in ("cnr", "disposal_nature", "judge") if r.get(k)}
                    | {"bench": bench},
                    dataset_name="Indian High Court Judgments",
                    dataset_slug="indian-high-court-judgments",
                )


def classify_domains(text_value: str, registry: Registry, max_domains: int = 3) -> list[str]:
    """Tag a judgment with legal areas using the topic keywords, from its opening text."""
    head = text_value[:8000]
    scores: dict[str, int] = {}
    for topic in registry.topics.values():
        if topic.domain == GENERAL_DOMAIN:
            continue
        phrases = [p for plist in topic.keywords.values() for p in plist]
        score = _score(head, phrases)
        if score:
            scores[topic.domain] = max(scores.get(topic.domain, 0), score)
    ranked = [d for d, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s >= 2][:max_domains]
    return [*ranked, GENERAL_DOMAIN]


@dataclass
class ImportStats:
    seen: int = 0
    skipped_existing: int = 0
    imported: int = 0
    failed: int = 0


def import_judgments(
    session_factory: Callable[[], Session],
    settings: Settings,
    service_factory: Callable[[Session], IngestionService],
    registry: Registry,
    records: Iterator[JudgmentRecord],
    limit: int | None = None,
    title_filter: re.Pattern[str] | None = None,
    workers: int = 4,
    progress: Callable[[ImportStats], None] | None = None,
) -> ImportStats:
    """Download, ingest and tag judgments. Downloads run in parallel; database work is sequential."""
    stats = ImportStats()
    selected: list[JudgmentRecord] = []
    with session_factory() as session:
        existing = {
            k
            for (k,) in session.query(LegalSource.source_key).filter(LegalSource.document_type == "judgment")
        }
    for rec in records:
        if title_filter and not title_filter.search(rec.title):
            continue
        stats.seen += 1
        if rec.source_key in existing:
            stats.skipped_existing += 1
            continue
        existing.add(rec.source_key)  # also skips repeats within this batch
        selected.append(rec)
        if limit and len(selected) >= limit:
            break

    def download(rec: JudgmentRecord) -> tuple[JudgmentRecord, bytes | None, str | None]:
        try:
            resp = httpx.get(rec.pdf_url, timeout=120)
            if resp.status_code != 200:
                return rec, None, f"HTTP {resp.status_code}"
            if len(resp.content) > settings.ingest_max_file_mb * 1024 * 1024:
                return rec, None, "file too large"
            return rec, resp.content, None
        except httpx.HTTPError as exc:
            return rec, None, type(exc).__name__

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rec, data, error in pool.map(download, selected):
            with session_factory() as session:
                svc = service_factory(session)
                # Slow work (PDF text, embeddings) before the first write, so the lock is held briefly.
                prepared = svc.prepare(data, "application/pdf", "judgment") if data is not None else None
                source = svc.register(
                    SourceSpec(
                        source_key=rec.source_key,
                        title=rec.title,
                        issuing_authority=rec.court,
                        document_type="judgment",
                        source_category="secondary",
                        jurisdiction=rec.jurisdiction,
                        court_level=rec.court_level,
                        legal_domains=[GENERAL_DOMAIN],
                        identifiers=rec.identifiers,
                        source_url=HttpUrl(rec.pdf_url),
                        host_note=ATTRIBUTION.format(name=rec.dataset_name, slug=rec.dataset_slug),
                        languages=["en"],
                        judgment_date=rec.judgment_date,
                        legal_status="unknown",
                        licensing_note="CC-BY-4.0 (Dattam Labs). Attribute the dataset when republishing.",
                    )
                )
                if data is None:
                    svc.record_error(source, f"download failed: {error}")
                    stats.failed += 1
                else:
                    outcome = svc.ingest_bytes(
                        source, data, "application/pdf", fetched_url=rec.pdf_url, prepared=prepared
                    )
                    if outcome.status == "failed":
                        stats.failed += 1
                    else:
                        version = session.get(DocumentVersion, outcome.version_id)
                        passages = sorted(version.passages, key=lambda p: p.ordinal)[:12] if version else []
                        source.legal_domains = classify_domains(" ".join(p.text for p in passages), registry)
                        stats.imported += 1
                session.commit()
            if progress and (stats.imported + stats.failed) % 25 == 0:
                progress(stats)
    return stats
