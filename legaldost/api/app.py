"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from legaldost import __version__
from legaldost.api import routes_admin, routes_dev, routes_whatsapp
from legaldost.api.services import Services, build_services
from legaldost.config import get_settings
from legaldost.db.session import get_sessionmaker
from legaldost.logging_setup import configure_logging


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


def app_factory() -> FastAPI:  # for `uvicorn --factory legaldost.api.app:app_factory`
    return create_app()
