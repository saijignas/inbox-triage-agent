"""HTTP request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent.schemas import TraceStep
from .models import DraftStatus, TriageStatus

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----------------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserOut(_Out):
    id: int
    email: str
    role: str


# ---- emails --------------------------------------------------------------------------


class EmailCreate(BaseModel):
    """Either structured fields (sender+subject+body) or `raw_text` pasted from a mail client."""

    sender: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=50_000)
    raw_text: str | None = Field(default=None, max_length=50_000)
    message_id: str | None = Field(default=None, max_length=255)
    received_at: datetime | None = None

    @model_validator(mode="after")
    def _one_form(self) -> "EmailCreate":
        structured = bool(self.sender and self.subject and self.body)
        if structured == bool(self.raw_text):
            raise ValueError("provide either raw_text or all of sender, subject and body")
        return self


class TaskOut(_Out):
    id: int
    description: str
    due_hint: str | None
    priority: str


class DraftOut(_Out):
    id: int
    email_id: int
    body: str
    edited_body: str | None
    final_body: str
    tone: str
    status: DraftStatus
    created_at: datetime
    decided_at: datetime | None
    email_subject: str | None = None
    email_sender: str | None = None


class TriageOut(_Out):
    status: TriageStatus
    category: str | None
    urgency: str | None
    needs_reply: bool | None
    summary: str | None
    error_code: str | None
    error_message: str | None
    provider: str | None
    attempts: int
    trace: list[TraceStep]
    updated_at: datetime


class EmailSummary(_Out):
    id: int
    sender: str
    subject: str
    received_at: datetime
    triage_status: TriageStatus | None = None
    category: str | None = None
    urgency: str | None = None
    draft_status: DraftStatus | None = None


class EmailDetail(_Out):
    id: int
    sender: str
    subject: str
    body: str
    received_at: datetime
    triage: TriageOut | None
    tasks: list[TaskOut]
    draft: DraftOut | None


class TriageStarted(BaseModel):
    email_id: int
    status: TriageStatus
    started: bool  # False when triage already ran / is in progress (idempotent no-op)


class SeedOut(BaseModel):
    added: int
    total: int


# ---- drafts --------------------------------------------------------------------------


class DraftPatch(BaseModel):
    edited_body: str = Field(min_length=1, max_length=4000)
