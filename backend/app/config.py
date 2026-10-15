"""Runtime configuration, read from environment variables.

Nothing here logs or prints secret values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_DEV_SECRET = "dev-insecure-secret-do-not-use-in-prod"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    app_env: str = "dev"
    database_url: str = "sqlite:///./triage.db"
    jwt_secret: str = field(default=_DEV_SECRET, repr=False)
    jwt_expire_minutes: int = 60
    llm_provider: str = "fake"  # "fake" | "gemini"
    gemini_api_key: str | None = field(default=None, repr=False)  # never shown in repr/logs
    gemini_model: str = "gemini-2.5-flash"
    agent_max_steps: int = 8
    agent_timeout_seconds: int = 30
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    @staticmethod
    def from_env() -> "Settings":
        app_env = os.environ.get("APP_ENV", "dev")
        secret = os.environ.get("JWT_SECRET")
        if not secret:
            if app_env != "dev":
                raise RuntimeError("JWT_SECRET must be set when APP_ENV is not 'dev'")
            secret = _DEV_SECRET
        origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
        return Settings(
            app_env=app_env,
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./triage.db"),
            jwt_secret=secret,
            jwt_expire_minutes=_int("JWT_EXPIRE_MINUTES", 60),
            llm_provider=os.environ.get("LLM_PROVIDER", "fake").lower(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            agent_max_steps=_int("AGENT_MAX_STEPS", 8),
            agent_timeout_seconds=_int("AGENT_TIMEOUT_SECONDS", 30),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )
