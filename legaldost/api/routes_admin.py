"""Protected knowledge-base administration API.

Disabled (404) unless ADMIN_API_TOKEN is set. Callers send ``X-Admin-Token``. Put this behind a
private network or VPN in production as well; the token is a second layer, not the only one.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from legaldost.api.services import Services
from legaldost.config import get_settings
from legaldost.db.models import IngestionEvent, LegalSource
from legaldost.ingestion.fetch import FetchError, fetch
from legaldost.ingestion.service import IngestionService, IngestOutcome, LegalStatus, SourceSpec
from legaldost.llm.base import UsageLedger


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> Services:
    services: Services = request.app.state.services
    expected = services.settings.admin_api_token
    if expected is None:
        raise HTTPException(status_code=404)
    if not x_admin_token or not hmac.compare_digest(
        x_admin_token.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status_code=401, detail="invalid admin token")
    return services


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _session(request: Request) -> Iterator[Session]:
    services: Services = request.app.state.services
    session = services.sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _svc(request: Request, session: Session) -> IngestionService:
    services: Services = request.app.state.services
    return IngestionService(session, services.settings, services.embedder)


def _source_out(s: LegalSource) -> dict[str, Any]:
    current = next((v for v in s.versions if v.is_current), None)
    return {
        "source_key": s.source_key,
        "title": s.title,
        "document_type": s.document_type,
        "source_category": s.source_category,
        "jurisdiction": s.jurisdiction,
        "source_url": s.source_url,
        "legal_status": s.legal_status,
        "verification_status": s.verification_status,
        "is_available": s.is_available,
        "versions": len(s.versions),
        "current_version": current.id if current else None,
        "current_passages": len(current.passages) if current else 0,
    }


@router.get("/sources")
def list_sources(request: Request, session: Session = Depends(_session)) -> list[dict[str, Any]]:
    return [_source_out(s) for s in session.scalars(select(LegalSource).order_by(LegalSource.source_key))]


@router.post("/sources")
def register_source(
    spec: SourceSpec, request: Request, session: Session = Depends(_session)
) -> dict[str, Any]:
    return _source_out(_svc(request, session).register(spec))


@router.post("/sources/{source_key}/upload", response_model=IngestOutcome)
async def upload(
    source_key: str, request: Request, file: UploadFile = File(...), session: Session = Depends(_session)
) -> IngestOutcome:
    svc = _svc(request, session)
    source = svc.get_source(source_key)
    if source is None:
        raise HTTPException(status_code=404, detail="unknown source")
    limit = get_settings().ingest_max_file_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="file too large")
    # The client-supplied filename is never used as a path.
    return svc.ingest_bytes(source, data, file.content_type, fetched_url=None)


class FetchIn(BaseModel):
    url: str | None = None


@router.post("/sources/{source_key}/fetch", response_model=IngestOutcome)
def fetch_source(
    source_key: str, body: FetchIn, request: Request, session: Session = Depends(_session)
) -> IngestOutcome:
    svc = _svc(request, session)
    source = svc.get_source(source_key)
    if source is None:
        raise HTTPException(status_code=404, detail="unknown source")
    s = svc.settings
    try:
        result = fetch(
            body.url or source.source_url,
            s.ingest_allowed_domains,
            s.ingest_max_file_mb * 1024 * 1024,
            s.ingest_request_interval_seconds,
        )
    except FetchError as exc:
        return svc.record_error(source, f"fetch failed: {exc}")
    return svc.ingest_bytes(source, result.data, result.content_type, fetched_url=result.url)


@router.post("/versions/{version_id}/reprocess", response_model=IngestOutcome)
def reprocess(version_id: str, request: Request, session: Session = Depends(_session)) -> IngestOutcome:
    try:
        return _svc(request, session).reprocess(version_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class StatusIn(BaseModel):
    legal_status: LegalStatus
    note: str | None = None
    superseded_by: str | None = None
    available: bool | None = None


@router.post("/sources/{source_key}/status")
def set_status(
    source_key: str, body: StatusIn, request: Request, session: Session = Depends(_session)
) -> dict[str, Any]:
    try:
        source = _svc(request, session).set_status(
            source_key, body.legal_status, body.note, body.superseded_by, body.available
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _source_out(source)


class ReviewIn(BaseModel):
    reviewer: str


@router.post("/sources/{source_key}/review")
def review(
    source_key: str, body: ReviewIn, request: Request, session: Session = Depends(_session)
) -> dict[str, Any]:
    try:
        return _source_out(_svc(request, session).mark_reviewed(source_key, body.reviewer))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/passages/{passage_id}/provenance")
def provenance(passage_id: str, request: Request, session: Session = Depends(_session)) -> dict[str, Any]:
    try:
        return _svc(request, session).provenance(passage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ingestion-events")
def events(request: Request, limit: int = 50, session: Session = Depends(_session)) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(IngestionEvent).order_by(IngestionEvent.created_at.desc()).limit(min(limit, 500))
    )
    return [
        {
            "at": e.created_at.isoformat(),
            "type": e.event_type,
            "status": e.status,
            "source_id": e.source_id,
            "version_id": e.version_id,
            "message": e.message,
        }
        for e in rows
    ]


@router.get("/usage")
def usage(request: Request, session: Session = Depends(_session)) -> dict[str, Any]:
    s = get_settings()
    ledger = UsageLedger(session, s.llm_monthly_budget_usd, s.llm_max_calls_per_question)
    return {
        "month_spend_usd_estimate": round(ledger.month_spend(), 4),
        "monthly_budget_usd": s.llm_monthly_budget_usd,
    }
