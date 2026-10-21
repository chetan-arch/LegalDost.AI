import io

import httpx
import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from legaldost.db.models import DocumentVersion, IngestionEvent, Passage
from legaldost.ingestion.fetch import FetchError, check_url, fetch
from tests.conftest import RULES_TEXT, _spec


def test_ingest_creates_located_passages(ingest, session) -> None:
    source = ingest.register(_spec("rules-a"))
    outcome = ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    assert outcome.status == "created"
    passages = session.scalars(
        select(Passage).where(Passage.source_id == source.id).order_by(Passage.ordinal)
    ).all()
    labels = [p.section_label for p in passages]
    assert "3" in labels and "4" in labels
    assert next(p for p in passages if p.section_label == "3").locator.startswith("r. 3")
    assert source.verification_status == "fetched_unreviewed"  # fetched is not the same as reviewed


def test_duplicate_ingestion_is_noop_and_new_content_versions(ingest, session) -> None:
    source = ingest.register(_spec("rules-b"))
    first = ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    dup = ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    assert dup.status == "duplicate" and dup.version_id == first.version_id
    second = ingest.ingest_bytes(
        source, (RULES_TEXT + "6. Extra. Added later for tests.\n").encode(), "text/plain"
    )
    session.flush()
    versions = session.scalars(select(DocumentVersion).where(DocumentVersion.source_id == source.id)).all()
    assert len(versions) == 2
    assert [v.is_current for v in sorted(versions, key=lambda v: v.version_no)] == [False, True]
    assert second.status == "created"


def test_reprocess_rebuilds_passages(ingest, session) -> None:
    source = ingest.register(_spec("rules-c"))
    outcome = ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    again = ingest.reprocess(outcome.version_id)
    assert again.passages == outcome.passages


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", "empty"),
        (b"<!doctype html><html>app shell</html>", "HTML page"),
        (b"\x89PNG\r\n\x1a\n\xff\xfe\xfd", "unsupported file type"),
    ],
)
def test_bad_documents_are_rejected_and_logged(ingest, session, data, expected) -> None:
    source = ingest.register(_spec("bad-doc"))
    outcome = ingest.ingest_bytes(source, data, None)
    assert outcome.status == "failed" and expected in outcome.message
    session.flush()
    events = session.scalars(select(IngestionEvent).where(IngestionEvent.event_type == "ingest_failed")).all()
    assert events


def test_scanned_pdf_without_text_layer_fails_clearly(ingest) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    source = ingest.register(_spec("scan"))
    outcome = ingest.ingest_bytes(source, buf.getvalue(), "application/pdf")
    assert outcome.status == "failed" and "no text layer" in outcome.message


def test_status_changes_keep_history(ingest, session) -> None:
    source = ingest.register(_spec("rules-d"))
    ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    ingest.set_status("rules-d", "superseded", note="test")
    session.flush()
    assert source.legal_status == "superseded"
    assert session.scalars(select(Passage).where(Passage.source_id == source.id)).first() is not None


def test_review_requires_ingested_version(ingest) -> None:
    ingest.register(_spec("rules-e"))
    with pytest.raises(ValueError):
        ingest.mark_reviewed("rules-e", "Adv. Test")


def test_metadata_change_resets_review(ingest, session) -> None:
    source = ingest.register(_spec("rules-f"))
    ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    session.flush()
    ingest.mark_reviewed("rules-f", "Adv. Test")
    ingest.register(_spec("rules-f", title="Changed title (FICTIONAL TEST FIXTURE)"))
    assert source.verification_status == "fetched_unreviewed"


def test_storage_path_cannot_escape(ingest) -> None:
    with pytest.raises(ValueError):
        ingest._storage_path("..", "../../etc/passwd")


def test_provenance(ingest, session) -> None:
    source = ingest.register(_spec("rules-g"))
    ingest.ingest_bytes(source, RULES_TEXT.encode(), "text/plain")
    session.flush()
    passage = session.scalars(select(Passage).where(Passage.source_id == source.id)).first()
    prov = ingest.provenance(passage.id)
    assert prov["source"]["source_url"] == "https://example.test/rules-g.txt"
    assert len(prov["version"]["content_sha256"]) == 64


def test_fetch_url_policy() -> None:
    with pytest.raises(FetchError):
        check_url("http://egazette.gov.in/x.pdf", ["egazette.gov.in"])
    with pytest.raises(FetchError):
        check_url("https://evil.example/x.pdf", ["egazette.gov.in"])
    check_url("https://egazette.gov.in/x.pdf", ["egazette.gov.in"])


def test_fetch_rechecks_redirect_hosts_and_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "egazette.gov.in" and request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://evil.example/doc.pdf"})
        if request.url.path == "/big":
            return httpx.Response(200, content=b"%PDF-" + b"x" * 2000)
        return httpx.Response(200, content=b"%PDF-1.4 small")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="not in INGEST_ALLOWED_DOMAINS"):
        fetch("https://egazette.gov.in/redirect", ["egazette.gov.in"], 10_000, 0, client=client)
    with pytest.raises(FetchError, match="larger than limit"):
        fetch("https://egazette.gov.in/big", ["egazette.gov.in"], 1000, 0, client=client)
    assert fetch("https://egazette.gov.in/ok", ["egazette.gov.in"], 1000, 0, client=client).data.startswith(
        b"%PDF"
    )
