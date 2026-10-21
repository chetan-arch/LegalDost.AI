"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI

from legaldost import __version__
from legaldost.api import routes_admin, routes_dev, routes_whatsapp
from legaldost.api.services import Services, build_services
from legaldost.config import get_settings
from legaldost.db.session import get_sessionmaker
from legaldost.logging_setup import configure_logging

log = logging.getLogger(__name__)


def create_app(services: Services | None = None) -> FastAPI:
    settings = services.settings if services else get_settings()
    if services is None:
        configure_logging(settings.log_level)
        if (
            settings.environment == "production"
            and settings.user_id_hash_secret.get_secret_value() == "dev-only-change-me"
        ):
            raise RuntimeError("USER_ID_HASH_SECRET must be set in production")
        services = build_services(settings, get_sessionmaker())
    app = FastAPI(
        title="LegalDost",
        version=__version__,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    app.state.services = services
    app.include_router(routes_whatsapp.router)
    app.include_router(routes_admin.router)
    if settings.environment != "production":
        app.include_router(routes_dev.router)

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        s = app.state.services
        return {
            "status": "ok",
            "version": __version__,
            "environment": s.settings.environment,
            "llm_provider": s.provider.name if s.provider else "none (extractive mode)",
            "decision_engine": s.engine.name,
            "whatsapp_outbound_configured": s.whatsapp is not None,
        }

    return app


def _warm_up(services: Services) -> None:
    """Load the embedding model and build the vector index before the first message arrives."""
    from legaldost.retrieval.search import HybridRetriever

    try:
        with services.sessionmaker() as session:
            retriever = HybridRetriever(session, services.embedder)
            retriever.vectors.search(session, services.embedder.embed_query("warm up"), 1)
        log.info("search index warmed up")
    except Exception:  # noqa: BLE001 - warm-up is best effort; the first request retries
        log.exception("search warm-up failed")


def app_factory() -> FastAPI:  # for `uvicorn --factory legaldost.api.app:app_factory`
    app = create_app()
    threading.Thread(target=_warm_up, args=(app.state.services,), daemon=True, name="warm-up").start()
    return app
