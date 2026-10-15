"""Typed contracts for the agent: tool arguments, LLM messages, and the run trace.

Every tool argument coming from a model is validated against these Pydantic models
before any tool code runs. `extra="forbid"` means a hallucinated field is an error,
not something silently ignored.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "meeting_request",
    "billing",
    "support_request",
    "newsletter",
    "spam",
    "recruiting",
    "personal",
    "internal_update",
]
Urgency = Literal["low", "medium", "high"]
Tone = Literal["formal", "friendly", "concise"]

CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]
URGENCIES: tuple[str, ...] = Urgency.__args__  # type: ignore[attr-defined]
# Categories where drafting a reply is a policy violation (checked inside the draft tool).
NO_REPLY_CATEGORIES: frozenset[str] = frozenset({"spam", "newsletter"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- tool arguments -------------------------------------------------------------------


class ClassifyEmailArgs(_Strict):
    category: Category
    urgency: Urgency


class TaskItem(_Strict):
    description: str = Field(min_length=3, max_length=300)
    due_hint: str | None = Field(default=None, max_length=100)
    priority: Urgency = "medium"


class ExtractTasksArgs(_Strict):
    tasks: list[TaskItem] = Field(max_length=10)


class SearchPastEmailsArgs(_Strict):
    query: str = Field(min_length=2, max_length=200)


class DraftReplyArgs(_Strict):
    body: str = Field(min_length=10, max_length=4000)
    tone: Tone = "formal"


# ---- LLM <-> loop messages ------------------------------------------------------------


class ToolCall(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Opaque provider-specific state that must be replayed verbatim on the next turn
    # (e.g. Gemini's thought signature on a function-call part). Never serialized or traced.
    provider_state: Any = Field(default=None, exclude=True, repr=False)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call: ToolCall | None = None  # set on assistant messages that call a tool
    tool_name: str | None = None  # set on tool-result messages
    is_error: bool = False


class LLMResponse(BaseModel):
    """Exactly one of tool_call / final should be set."""

    tool_call: ToolCall | None = None
    final: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema from the Pydantic args model


# ---- trace / run result ---------------------------------------------------------------


class TraceStep(BaseModel):
    step: int
    tool: str  # tool name, "llm" for provider failures/retries, or "final"
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    latency_ms: float = 0.0


class AgentRun(BaseModel):
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    category: str | None = None
    urgency: str | None = None
    tasks: list[TaskItem] = Field(default_factory=list)
    draft_body: str | None = None
    draft_tone: str | None = None
    summary: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)

    @property
    def needs_reply(self) -> bool:
        return self.draft_body is not None


class EmailInput(BaseModel):
    id: int | None = None
    sender: str
    subject: str
    body: str
