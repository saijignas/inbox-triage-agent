"""FastAPI application factory.

`create_app` takes optional overrides so tests can inject an in-memory DB and a FakeLLM.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from .agent import FakeLLM, GeminiLLM, LLMProvider
from .api import auth_routes, draft_routes, email_routes
from .config import Settings
from .db import Base, make_engine, make_session_factory
from . import models  # noqa: F401  (register tables on Base.metadata)


def build_provider_factory(settings: Settings) -> Callable[[], LLMProvider]:
    if settings.llm_provider == "fake":
        return lambda: FakeLLM()
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        key, model = settings.gemini_api_key, settings.gemini_model
        return lambda: GeminiLLM(api_key=key, model=model)
    raise RuntimeError(f"Unknown LLM_PROVIDER '{settings.llm_provider}' (use 'fake' or 'gemini')")


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    provider_factory: Callable[[], LLMProvider] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = None
    if session_factory is None:
        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
    factory = provider_factory or build_provider_factory(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # create_all keeps first-run simple; Alembic migrations are a documented next step.
        Base.metadata.create_all(session_factory.kw["bind"])
        yield

    app = FastAPI(title="Inbox Triage Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.provider_factory = factory
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(auth_routes.router)
    app.include_router(email_routes.router)
    app.include_router(draft_routes.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "provider": settings.llm_provider}

    return app


app = create_app()
