"""``legaldost`` command-line tool (operator use; requires shell access to the server)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from legaldost.config import PROJECT_ROOT, get_settings
from legaldost.db.models import IngestionEvent, LegalSource, Passage, ProcessedEvent
from legaldost.db.session import session_scope
from legaldost.ingestion.fetch import FetchError, fetch
from legaldost.ingestion.manifest import load_manifest
from legaldost.ingestion.service import IngestionService
from legaldost.retrieval.embeddings import get_embedder


def _svc(session: Session) -> IngestionService:
    return IngestionService(session, get_settings(), get_embedder())


def cmd_db_upgrade(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    print("database is at the latest migration")
    return 0


def cmd_ingest_manifest(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.path))
    settings = get_settings()
    failures = 0
    for entry in manifest.entries:
        with session_scope() as session:
            svc = _svc(session)
            source = svc.register(entry.source)
            if args.register_only:
                print(f"registered  {entry.source.source_key}")
                continue
            base = Path(args.path).parent.resolve()
            local = (base / entry.local_file).resolve() if entry.local_file else None
            if local is not None and base not in local.parents:
                outcome = svc.record_error(source, "local_file must stay inside the manifest's folder")
            elif local is not None and local.is_file():
                outcome = svc.ingest_bytes(source, local.read_bytes(), None, fetched_url=None)
            elif local is not None and not entry.fetch_url:
                outcome = svc.record_error(source, f"local file not found: {entry.local_file}")
            elif entry.fetch_url:
                try:
                    result = fetch(
                        str(entry.fetch_url),
                        settings.ingest_allowed_domains,
                        settings.ingest_max_file_mb * 1024 * 1024,
                        settings.ingest_request_interval_seconds,
                    )
                    outcome = svc.ingest_bytes(
                        source, result.data, result.content_type, fetched_url=result.url
                    )
                except FetchError as exc:
                    outcome = svc.record_error(source, f"fetch failed: {exc}")
            else:
                print(f"registered  {entry.source.source_key} (no document location)")
                continue
        failures += outcome.status == "failed"
        print(
            f"{outcome.status:<10} {entry.source.source_key}  passages={outcome.passages}  {outcome.message[:160]}"
        )
    for key in manifest.skipped:
        print(f"skipped    {key}  (enabled: false; fill in source_url/local_file to load it)")
    return 1 if failures and args.strict else 0


def cmd_ingest_file(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    with session_scope() as session:
        svc = _svc(session)
        source = svc.get_source(args.source_key)
        if source is None:
            print("unknown source; register it first (manifest or admin API)", file=sys.stderr)
            return 2
        outcome = svc.ingest_bytes(source, path.read_bytes(), None, fetched_url=None)
    print(outcome.model_dump_json(indent=2))
    return 0 if outcome.status != "failed" else 1


def cmd_ingest_fetch(args: argparse.Namespace) -> int:
    settings = get_settings()
    with session_scope() as session:
        svc = _svc(session)
        source = svc.get_source(args.source_key)
        if source is None:
            print("unknown source", file=sys.stderr)
            return 2
        try:
            result = fetch(
                args.url or source.source_url,
                settings.ingest_allowed_domains,
                settings.ingest_max_file_mb * 1024 * 1024,
                settings.ingest_request_interval_seconds,
            )
            outcome = svc.ingest_bytes(source, result.data, result.content_type, fetched_url=result.url)
        except FetchError as exc:
            outcome = svc.record_error(source, f"fetch failed: {exc}")
    print(outcome.model_dump_json(indent=2))
    return 0 if outcome.status != "failed" else 1


def cmd_reprocess(args: argparse.Namespace) -> int:
    from legaldost.db.models import DocumentVersion

    with session_scope() as session:
        svc = _svc(session)
        if args.all_current:
            ids = [
                v.id
                for v in session.scalars(select(DocumentVersion).where(DocumentVersion.is_current.is_(True)))
            ]
        elif args.version_id:
            ids = [args.version_id]
        else:
            print("give a version_id or --all-current", file=sys.stderr)
            return 2
        for vid in ids:
            outcome = svc.reprocess(vid)
            print(f"{outcome.status:<10} {outcome.source_key}  passages={outcome.passages}")
    return 0


def cmd_sources_list(_: argparse.Namespace) -> int:
    with session_scope() as session:
        for s in session.scalars(select(LegalSource).order_by(LegalSource.source_key)):
            current = next((v for v in s.versions if v.is_current), None)
            print(
                f"{s.source_key:<55} {s.document_type:<16} {s.source_category:<19} status={s.legal_status:<9} "
                f"verify={s.verification_status:<18} versions={len(s.versions)} "
                f"passages={len(current.passages) if current else 0}"
            )
    return 0


def cmd_sources_status(args: argparse.Namespace) -> int:
    with session_scope() as session:
        _svc(session).set_status(
            args.source_key,
            args.legal_status,
            args.note,
            args.superseded_by,
            None if args.available is None else args.available == "yes",
        )
    print("updated")
    return 0


def cmd_sources_review(args: argparse.Namespace) -> int:
    with session_scope() as session:
        _svc(session).mark_reviewed(args.source_key, args.reviewer)
    print("marked reviewer_verified")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    with session_scope() as session:
        rows = session.scalars(
            select(IngestionEvent).order_by(IngestionEvent.created_at.desc()).limit(args.limit)
        )
        for e in rows:
            print(f"{e.created_at:%Y-%m-%d %H:%M:%S} {e.status:<6} {e.event_type:<18} {e.message[:150]}")
    return 0


def cmd_provenance(args: argparse.Namespace) -> int:
    with session_scope() as session:
        print(json.dumps(_svc(session).provenance(args.passage_id), indent=2, ensure_ascii=False))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from legaldost.retrieval.search import HybridRetriever, QuerySpec, RetrievalFilters

    with session_scope() as session:
        results = HybridRetriever(session, get_embedder()).search(
            QuerySpec(args.query), RetrievalFilters(jurisdictions=args.jurisdiction or None), limit=args.limit
        )
        for r in results:
            p = session.get(Passage, r.passage_id)
            assert p is not None
            print(
                f"{r.score:.4f} lex={r.lexical_score:.2f} vec={r.vector_score:.2f} {p.source.source_key} "
                f"[{p.locator}] {p.text[:140].replace(chr(10), ' ')}"
            )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from legaldost.api.processing import process_text
    from legaldost.api.services import build_services
    from legaldost.db.session import get_sessionmaker

    services = build_services(get_settings(), get_sessionmaker())
    reply = process_text(services, "cli", args.session, args.message)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(reply.text)
    print(f"\n[outcome={reply.outcome} {json.dumps(reply.diagnostics, default=str)}]")
    return 0


def cmd_purge(_: argparse.Namespace) -> int:
    from datetime import UTC, datetime, timedelta

    from legaldost.pipeline.conversation import ConversationStore

    settings = get_settings()
    with session_scope() as session:
        n = ConversationStore(session, settings.conversation_retention_hours).purge_expired()
        cutoff = datetime.now(UTC) - timedelta(days=7)
        m = session.execute(delete(ProcessedEvent).where(ProcessedEvent.received_at < cutoff)).rowcount  # type: ignore[attr-defined]
    print(f"purged {n} expired conversation(s) and {m} old webhook event id(s)")
    return 0


def cmd_reindex(_: argparse.Namespace) -> int:
    embedder = get_embedder()
    with session_scope() as session:
        passages = list(session.scalars(select(Passage)))
        for i in range(0, len(passages), 64):
            batch = passages[i : i + 64]
            for p, vec in zip(batch, embedder.embed([p.text for p in batch]), strict=True):
                p.embedding = vec
    print(f"re-embedded {len(passages)} passages with {embedder.name}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from legaldost.eval.runner import run_legal_eval

    return run_legal_eval(Path(args.dataset), Path(args.out) if args.out else None)


def cmd_eval_models(args: argparse.Namespace) -> int:
    from legaldost.eval.model_compare import run_model_comparison

    return run_model_comparison([m.strip() for m in args.models.split(",")], Path(args.out))


def cmd_eval_routing(args: argparse.Namespace) -> int:
    from legaldost.eval.routing import run_routing_benchmark

    return run_routing_benchmark(
        Path(args.dataset), args.engines.split(","), Path(args.out) if args.out else None
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="legaldost")
    sub = p.add_subparsers(dest="cmd", required=True)

    db = sub.add_parser("db").add_subparsers(dest="sub", required=True)
    db.add_parser("upgrade", help="apply migrations").set_defaults(func=cmd_db_upgrade)

    ing = sub.add_parser("ingest").add_subparsers(dest="sub", required=True)
    m = ing.add_parser("manifest", help="register and ingest every source in a manifest")
    m.add_argument("path")
    m.add_argument("--register-only", action="store_true")
    m.add_argument("--strict", action="store_true", help="exit non-zero if any source fails")
    m.set_defaults(func=cmd_ingest_manifest)
    f = ing.add_parser("file", help="ingest a local PDF/text file as a new version of a source")
    f.add_argument("source_key")
    f.add_argument("path")
    f.set_defaults(func=cmd_ingest_file)
    fe = ing.add_parser("fetch", help="download and ingest a registered source")
    fe.add_argument("source_key")
    fe.add_argument("--url")
    fe.set_defaults(func=cmd_ingest_fetch)
    r = ing.add_parser("reprocess", help="re-run extraction for a stored version")
    r.add_argument("version_id", nargs="?")
    r.add_argument("--all-current", action="store_true", help="re-extract every current version")
    r.set_defaults(func=cmd_reprocess)

    src = sub.add_parser("sources").add_subparsers(dest="sub", required=True)
    src.add_parser("list").set_defaults(func=cmd_sources_list)
    st = src.add_parser("status", help="set legal status (never deletes history)")
    st.add_argument("source_key")
    st.add_argument(
        "legal_status",
        choices=[
            "unknown",
            "in_force",
            "amended",
            "partially_in_force",
            "superseded",
            "repealed",
            "withdrawn",
        ],
    )
    st.add_argument("--note")
    st.add_argument("--superseded-by")
    st.add_argument("--available", choices=["yes", "no"])
    st.set_defaults(func=cmd_sources_status)
    rv = src.add_parser("review", help="record advocate review of a source's metadata and text")
    rv.add_argument("source_key")
    rv.add_argument("--reviewer", required=True)
    rv.set_defaults(func=cmd_sources_review)
    ev = src.add_parser("events", help="show recent ingestion events and errors")
    ev.add_argument("--limit", type=int, default=30)
    ev.set_defaults(func=cmd_events)

    pv = sub.add_parser("provenance", help="show where a passage came from")
    pv.add_argument("passage_id")
    pv.set_defaults(func=cmd_provenance)
    se = sub.add_parser("search", help="debug retrieval")
    se.add_argument("query")
    se.add_argument("--jurisdiction", action="append")
    se.add_argument("--limit", type=int, default=6)
    se.set_defaults(func=cmd_search)
    ask = sub.add_parser("ask", help="ask a question through the full pipeline")
    ask.add_argument("message")
    ask.add_argument("--session", default="cli-user")
    ask.set_defaults(func=cmd_ask)
    sub.add_parser("purge-expired", help="delete expired conversations").set_defaults(func=cmd_purge)
    sub.add_parser("reindex-embeddings", help="recompute embeddings").set_defaults(func=cmd_reindex)

    evp = sub.add_parser("eval").add_subparsers(dest="sub", required=True)
    le = evp.add_parser("legal", help="run the legal evaluation set against the loaded corpus")
    le.add_argument("--dataset", default=str(PROJECT_ROOT / "eval" / "legal_eval.yaml"))
    le.add_argument("--out")
    le.set_defaults(func=cmd_eval)
    ro = evp.add_parser("routing", help="benchmark decision engines")
    ro.add_argument("--dataset", default=str(PROJECT_ROOT / "eval" / "routing_eval.yaml"))
    ro.add_argument("--engines", default="rules")
    ro.add_argument("--out")
    ro.set_defaults(func=cmd_eval_routing)
    mo = evp.add_parser("models", help="compare local Ollama models on corpus questions")
    mo.add_argument("--models", default="qwen3:8b")
    mo.add_argument("--out", default=str(PROJECT_ROOT / "data" / "model_compare.json"))
    mo.set_defaults(func=cmd_eval_models)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
